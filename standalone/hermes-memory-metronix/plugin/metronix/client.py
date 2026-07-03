from __future__ import annotations

import threading
from typing import Any
from urllib.parse import urlencode

import requests


class MetronixClient:
    """Thin synchronous REST client for the standalone Hermes plugin."""

    def __init__(
        self,
        *,
        base_url: str,
        workspace_id: str,
        auth_token: str = "",
        email: str = "",
        password: str = "",
        timeout: float = 20.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._workspace_id = workspace_id
        self._auth_token = auth_token
        self._email = email
        self._password = password
        self._timeout = timeout
        self._session = requests.Session()
        self._login_lock = threading.Lock()

    def search_memory(
        self,
        *,
        query: str,
        top_k: int,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"query": query, "top_k": top_k}
        if agent_id:
            payload["agent_id"] = agent_id
        data = self._request("POST", "/api/v1/memory/search", json=payload)
        return list(data.get("results", []))

    def create_memory(
        self,
        *,
        content: str,
        agent_id: str,
        scope: str,
        kind: str,
        source_type: str,
        tags: list[str] | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "content": content,
            "agent_id": agent_id,
            "scope": scope,
            "kind": kind,
            "source_type": source_type,
            "tags": tags or [],
            "metadata": metadata or {},
        }
        if session_id:
            payload["session_id"] = session_id
        return self._request("POST", "/api/v1/memory/records", json=payload)

    def store_document(
        self,
        *,
        content: str,
        title: str | None = None,
        doc_label: str | None = None,
        source_type: str = "memory",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"content": content, "source_type": source_type}
        if title:
            payload["title"] = title
        if doc_label:
            payload["doc_label"] = doc_label
        if metadata:
            payload["metadata"] = metadata
        return self._request("POST", "/api/v1/knowledge/store", json=payload)

    def ping(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/auth/me")

    def delete_memory(self, record_id: str) -> None:
        self._request("DELETE", f"/api/v1/memory/records/{record_id}")

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = dict(kwargs.pop("headers", {}) or {})
        query = urlencode({"workspace_id": self._workspace_id})
        url = f"{self._base_url}{path}?{query}"
        response = self._send_request(method, url, headers=headers, **kwargs)
        if response.status_code == 401 and self._email and self._password:
            self._auth_token = ""
            response = self._send_request(method, url, headers=headers, **kwargs)
        response.raise_for_status()
        if not response.content:
            return {}
        return dict(response.json())

    def _send_request(self, method: str, url: str, *, headers: dict[str, Any], **kwargs: Any):
        request_headers = dict(headers)
        token = self._get_token()
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        return self._session.request(
            method,
            url,
            headers=request_headers,
            timeout=self._timeout,
            **kwargs,
        )

    def _get_token(self) -> str:
        if self._auth_token:
            return self._auth_token
        if not (self._email and self._password):
            return ""
        with self._login_lock:
            if self._auth_token:
                return self._auth_token
            response = self._session.post(
                f"{self._base_url}/api/v1/auth/login",
                json={"email": self._email, "password": self._password},
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
            self._auth_token = str(data.get("token", "") or "")
            return self._auth_token
