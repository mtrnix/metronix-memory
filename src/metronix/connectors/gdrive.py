"""Google Drive connector — fetches Docs, Sheets, Slides, and binary files.

Uses google-api-python-client with a Service Account key JSON. The service
account sees files/folders explicitly shared with its email, or content on a
Shared Drive it has been added to. The Google SDK is synchronous, so blocking
calls run in ``asyncio.to_thread``. Pure formatting lives in gdrive_processing.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime

import structlog

from metronix.connectors.gdrive_processing import FOLDER_MIME, build_document, export_format
from metronix.core.interfaces import ConnectorInterface
from metronix.core.models import Connection, Document
from metronix.ingestion.upload import is_allowed_upload, parse_upload

logger = structlog.get_logger()

_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_NUM_RETRIES = 5
_MAX_FILE_BYTES = 1_000_000
_DRIVE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_FILE_FIELDS = "id, name, mimeType, modifiedTime, owners, webViewLink, size, parents, trashed"
_FIELDS = f"nextPageToken, files({_FILE_FIELDS})"
_CHANGE_FIELDS = (
    f"nextPageToken, newStartPageToken, changes(removed, fileId, file({_FILE_FIELDS}))"
)


class GDriveConnector(ConnectorInterface):
    """Fetches files from Google Drive shared with a service account.

    Config keys (decrypted_config):
    - credentials_json: Service Account key JSON (required).
    Optional scoping: folder_id, shared_drive_id.
    """

    source_role: str = "knowledge_base"

    def __init__(self) -> None:
        self._service = None
        self._config: dict[str, str] = {}
        self._resume_cursor: str | None = None
        self._next_cursor: str | None = None

    def load_cursor(self, cursor: str | None) -> None:
        self._resume_cursor = cursor

    def take_cursor(self) -> str | None:
        return self._next_cursor

    def _build_credentials(self, config: dict[str, str]):
        """Build Drive credentials from the service account key JSON."""
        creds_json = (config.get("credentials_json") or "").strip()
        if not creds_json:
            raise ValueError("gdrive requires a Service Account JSON (credentials_json)")
        from google.oauth2 import service_account

        info = json.loads(creds_json)
        return service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)

    def _build_service(self, config: dict[str, str]):
        """Build the Drive v3 service (blocking — RSA parse + discovery)."""
        from googleapiclient.discovery import build

        creds = self._build_credentials(config)
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    def _process_file(self, meta: dict, workspace_id: str) -> Document | None:
        """Export (Google-native) or download (binary) a single file → Document.

        Returns None for oversized binaries and unsupported MIME types (skipped).
        """
        mime = meta.get("mimeType", "")
        name = meta.get("name", "")
        file_id = meta.get("id", "")

        export = export_format(mime)
        if export is not None:
            export_mime, _note = export
            # export_media does NOT accept supportsAllDrives.
            data = (
                self._service.files()
                .export_media(fileId=file_id, mimeType=export_mime)
                .execute(num_retries=_NUM_RETRIES)
            )
            text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)
            return build_document(meta, text, workspace_id)

        if is_allowed_upload(name):
            size = int(meta["size"]) if str(meta.get("size", "")).isdigit() else 0
            if size > _MAX_FILE_BYTES:
                logger.warning("gdrive.file.too_large", file_id=file_id, name=name, size=size)
                return None
            data = (
                self._service.files()
                .get_media(fileId=file_id, supportsAllDrives=True)
                .execute(num_retries=_NUM_RETRIES)
            )
            text = parse_upload(name, data)
            return build_document(meta, text, workspace_id)

        logger.debug("gdrive.file.skip_unsupported", file_id=file_id, mime=mime, name=name)
        return None

    @staticmethod
    def _validate_scope_ids(config: dict[str, str]) -> None:
        """Reject malformed folder/drive ids up front — they are interpolated
        into Drive query strings, so a stray quote or text yields an opaque API
        error instead of a clear config error. Drive ids are ``[A-Za-z0-9_-]+``."""
        for key in ("folder_id", "shared_drive_id"):
            value = (config.get(key) or "").strip()
            if value and not _DRIVE_ID_RE.match(value):
                raise ValueError(
                    f"gdrive: invalid {key} {value!r} — expected a Drive id "
                    "([A-Za-z0-9_-]+), e.g. the part after /folders/ in the URL"
                )

    async def configure(self, connection: Connection, decrypted_config: dict[str, str]) -> None:
        logger.info("gdrive.configure", connector_id=connection.id)
        self._validate_scope_ids(decrypted_config)
        self._config = decrypted_config
        # build() + credential construction are blocking; keep off the event loop.
        self._service = await asyncio.to_thread(self._build_service, decrypted_config)

    def _list_raw(self, q: str, *, drive_scoped: bool) -> list[dict]:
        """Paginate files.list for a query, returning all file metadata dicts."""
        params: dict = {
            "q": q,
            "pageSize": 1000,
            "fields": _FIELDS,
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        drive_id = self._config.get("shared_drive_id")
        if drive_scoped and drive_id:
            params["corpora"] = "drive"
            params["driveId"] = drive_id
        out: list[dict] = []
        page_token: str | None = None
        while True:
            if page_token:
                params["pageToken"] = page_token
            resp = self._service.files().list(**params).execute(num_retries=_NUM_RETRIES)
            out.extend(resp.get("files", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return out

    def _walk_folder(self, root: str) -> list[dict]:
        """BFS a folder subtree, returning all non-folder file metas.

        Used only by the full sweep (``since`` is None); incremental change
        detection is handled separately via the Changes API.
        """
        scoped = bool(self._config.get("shared_drive_id"))
        files: list[dict] = []
        queue: list[str] = [root]
        while queue:
            parent = queue.pop()
            q = f"trashed = false and '{parent}' in parents"
            for child in self._list_raw(q, drive_scoped=scoped):
                if child.get("mimeType") == FOLDER_MIME:
                    queue.append(child["id"])
                else:
                    files.append(child)
        return files

    def _collect_files(self) -> list[dict]:
        """Full-sweep listing: resolve scope → all non-folder file metas."""
        folder_id = self._config.get("folder_id")
        if folder_id:
            return self._walk_folder(folder_id)
        if self._config.get("shared_drive_id"):
            # Whole Shared Drive: a drive-scoped list is flat across the drive.
            metas = self._list_raw("trashed = false", drive_scoped=True)
            return [m for m in metas if m.get("mimeType") != FOLDER_MIME]
        # No explicit scope → everything shared with the service account.
        return self._collect_shared()

    def _collect_shared(self) -> list[dict]:
        """Everything shared with the account: loose shared files + the full
        contents of shared folders.

        A plain listing does not surface "shared with me" items nor recurse into
        shared folders (a service account's own My Drive is empty), so discover
        the shared roots via ``sharedWithMe = true`` and BFS each shared folder.
        """
        roots = self._list_raw("trashed = false and sharedWithMe = true", drive_scoped=False)
        files: list[dict] = []
        for item in roots:
            if item.get("mimeType") == FOLDER_MIME:
                files.extend(self._walk_folder(item["id"]))
            else:
                files.append(item)
        return files

    def _get_start_page_token(self) -> str:
        params: dict = {"supportsAllDrives": True}
        drive_id = self._config.get("shared_drive_id")
        if drive_id:
            params["driveId"] = drive_id
        resp = (
            self._service.changes().getStartPageToken(**params).execute(num_retries=_NUM_RETRIES)
        )
        return resp["startPageToken"]

    def _build_docs(self, metas: list[dict], workspace_id: str) -> list[Document]:
        documents: list[Document] = []
        for meta in metas:
            try:
                doc = self._process_file(meta, workspace_id)
                if doc is not None:
                    documents.append(doc)
            except Exception as exc:  # noqa: BLE001 — one bad file must not abort sync
                logger.warning("gdrive.file.error", file_id=meta.get("id"), error=str(exc))
        return documents

    def _collect_changes(self, cursor: str) -> list[dict]:
        """Page changes.list from ``cursor``; return in-scope non-folder file metas.

        Skips removed/trashed entries (deletions are out of scope). Sets
        ``self._next_cursor`` to the final newStartPageToken. Raises HttpError.
        """
        params: dict = {
            "spaces": "drive",
            "includeItemsFromAllDrives": True,
            "supportsAllDrives": True,
            "pageSize": 1000,
            "fields": _CHANGE_FIELDS,
        }
        drive_id = self._config.get("shared_drive_id")
        if drive_id:
            params["driveId"] = drive_id

        # Scope filtering: shared-drive is scoped by driveId and no-scope takes
        # everything, so only folder_id needs an ancestry check against the set
        # of folders under folder_id (changes.list can't be scoped to a subtree).
        scope_ids = self._folder_scope_ids() if self._config.get("folder_id") else None

        files: list[dict] = []
        token = cursor
        while True:
            params["pageToken"] = token
            resp = self._service.changes().list(**params).execute(num_retries=_NUM_RETRIES)
            for change in resp.get("changes", []):
                if change.get("removed"):
                    continue
                meta = change.get("file")
                if not meta or meta.get("trashed"):
                    continue
                if meta.get("mimeType") == FOLDER_MIME:
                    continue
                if scope_ids is not None and not any(
                    p in scope_ids for p in (meta.get("parents") or [])
                ):
                    continue
                files.append(meta)
            next_token = resp.get("nextPageToken")
            if next_token:
                token = next_token
                continue
            self._next_cursor = resp.get("newStartPageToken")
            break
        return files

    def _folder_scope_ids(self) -> set[str]:
        """Set of folder ids under (and including) folder_id — for ancestry scoping."""
        root = self._config["folder_id"]
        scoped = bool(self._config.get("shared_drive_id"))
        ids: set[str] = {root}
        queue: list[str] = [root]
        while queue:
            parent = queue.pop()
            q = f"trashed = false and '{parent}' in parents and mimeType = '{FOLDER_MIME}'"
            for child in self._list_raw(q, drive_scoped=scoped):
                cid = child["id"]
                if cid not in ids:
                    ids.add(cid)
                    queue.append(cid)
        return ids

    def _incremental(self, workspace_id: str, cursor: str) -> list[Document]:
        metas = self._collect_changes(cursor)
        return self._build_docs(metas, workspace_id)

    def _full_sweep(self, workspace_id: str) -> list[Document]:
        # Capture the page token BEFORE listing: a file added during the sweep
        # then reappears in the next changes.list (deduped downstream) rather
        # than being lost between the sweep and an end-of-sweep token.
        self._next_cursor = self._get_start_page_token()
        metas = self._collect_files()
        return self._build_docs(metas, workspace_id)

    async def fetch(self, workspace_id: str, since: datetime | None = None) -> list[Document]:
        logger.info("gdrive.fetch.started", workspace_id=workspace_id, since=since)
        if self._service is None:
            raise RuntimeError("Connector not configured — call configure() first")
        from googleapiclient.errors import HttpError

        # since is None (first sync / force_full) or no stored cursor → full sweep
        # (also captures a fresh page token). Otherwise pull incremental changes.
        if since is None or not self._resume_cursor:
            documents = await asyncio.to_thread(self._full_sweep, workspace_id)
        else:
            try:
                documents = await asyncio.to_thread(
                    self._incremental, workspace_id, self._resume_cursor
                )
            except HttpError as exc:
                status = getattr(getattr(exc, "resp", None), "status", None)
                if status == 410:
                    # Expired/invalid page token (fullSyncRequired) → full resync.
                    logger.warning("gdrive.cursor.expired", workspace_id=workspace_id)
                    documents = await asyncio.to_thread(self._full_sweep, workspace_id)
                else:
                    raise

        logger.info("gdrive.fetch.done", documents=len(documents))
        return documents

    async def health_check(self) -> bool:
        """Probe credentials + reachability against the configured access path.

        The probe lists one file scoped exactly like a real sync — a Shared Drive,
        the configured folder, or ``sharedWithMe`` — so a bad folder id or an
        unreachable host surfaces here. Note it cannot distinguish "scope is
        accessible but empty" from "nothing shared": both return an empty list
        without error, so an empty-but-valid setup still reads healthy. It
        confirms the connector *can* talk to Drive, not that content exists.
        """
        if self._service is None:
            return False
        try:
            params: dict = {
                "pageSize": 1,
                "fields": "files(id)",
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
            }
            drive_id = self._config.get("shared_drive_id")
            folder_id = self._config.get("folder_id")
            # Mirror _collect_files' scope priority exactly (folder_id first), so
            # the probe exercises the SAME path the sync will use. Checking the
            # Shared Drive root first would false-green a bad folder_id nested in
            # an accessible drive.
            if folder_id:
                # Exercise the configured folder (also catches a bad folder id).
                # Drive-scope it when the folder lives in a Shared Drive, matching
                # _walk_folder's drive_scoped=bool(shared_drive_id).
                params["q"] = f"trashed = false and '{folder_id}' in parents"
                if drive_id:
                    params["corpora"] = "drive"
                    params["driveId"] = drive_id
            elif drive_id:
                # Whole Shared Drive: a Service Account with only Shared-Drive
                # access returns nothing under the default corpora="user".
                params["corpora"] = "drive"
                params["driveId"] = drive_id
                params["q"] = "trashed = false"
            else:
                # Default scope mirrors the sync: what is shared with the account.
                params["q"] = "trashed = false and sharedWithMe = true"
            await asyncio.to_thread(
                lambda: self._service.files().list(**params).execute(num_retries=_NUM_RETRIES)
            )
            return True
        except Exception:
            return False
