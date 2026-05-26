"""FastAPI application factory.

Creates and configures the FastAPI app with all routers,
middleware, and lifespan events. Uses the factory pattern
so tests can create isolated app instances.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from metatron.api.middleware import OptionalAuthMiddleware
from metatron.api.routes import (
    admin,
    agents,
    asoc_chat,
    asoc_workspace,
    auth,
    benchmarker,
    chat,
    config,
    connections,
    dashboard,
    documents,
    files,
    graph,
    health,
    knowledge,
    memory,
    skills,
    snapshots,
    sync,
    users,
    workspaces,
)
from metatron.core.config import Settings
from metatron.core.logging import configure_logging
from metatron.core.plugin import PluginManager, discover_plugins

logger = structlog.get_logger()


# MCP server instance — imported to register tools
import metatron.mcp.tools  # noqa: F401 — registers @mcp.tool() decorators
from metatron.mcp.server import mcp as mcp_server


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — startup and shutdown logic.

    Startup: configure logging, initialize stores, register connectors.
    Shutdown: close all connections gracefully.
    """
    settings: Settings = app.state.settings
    configure_logging(
        log_level=settings.log_level,
        json_output=settings.env != "development",
    )
    logger.info("app.startup", env=settings.env, port=settings.port)
    logger.info(
        "app.feature_flags",
        splade_enabled=settings.splade_enabled,
        hyde_enabled=settings.hyde_enabled,
        adaptive_rrf_enabled=settings.adaptive_rrf_enabled,
        hierarchical_chunking_enabled=settings.hierarchical_chunking_enabled,
        reranker_enabled=settings.reranker_enabled,
        graph_extraction_enabled=settings.graph_extraction_enabled,
    )

    # Apply pending database migrations before serving traffic.
    # Advisory lock ensures only one replica runs migrations when several
    # instances start simultaneously. Failures are non-fatal — the app
    # continues if the schema is already up to date.
    try:
        import asyncio

        from metatron.storage.migrations import run_migrations_sync

        await asyncio.to_thread(
            run_migrations_sync, settings.postgres_sync_dsn, settings.postgres_dsn
        )
    except Exception as exc:
        logger.error("migrations.failed", error=str(exc))

    # Ensure Memgraph property indexes exist (idempotent, non-fatal)
    try:
        import asyncio as _asyncio

        from metatron.storage.neo4j_graph import ensure_graph_indexes

        await _asyncio.to_thread(ensure_graph_indexes)
    except Exception as exc:
        logger.warning("neo4j.indexes.failed", error=str(exc))

    # One-time migration: env-var credentials → DB connections (idempotent)
    try:
        from metatron.storage.migrate_env_connections import migrate_env_to_db

        mig = await migrate_env_to_db(
            postgres_dsn=settings.postgres_dsn,
            workspace_id=settings.default_workspace_id,
            fernet_key=settings.fernet_key,
        )
        if mig["created"]:
            logger.info("env_migration.done", created=mig["created"])
    except Exception as exc:
        logger.warning("env_migration.failed", error=str(exc))

    # Recover from any syncs interrupted by a previous shutdown.
    # Reset `sync_logs.running` → `failed` and `connections.syncing` → `error`.
    try:
        import asyncio as _asyncio

        from metatron.storage.recovery import recover_interrupted_syncs

        rec = await _asyncio.to_thread(recover_interrupted_syncs)
        if rec["sync_logs_reset"] or rec["connections_reset"]:
            logger.info(
                "sync.recovery.applied",
                sync_logs_reset=rec["sync_logs_reset"],
                connections_reset=rec["connections_reset"],
            )
    except Exception as exc:
        logger.warning("sync.recovery.startup_failed", error=str(exc))

    # --- Shared DB engine for user store + API key store ---
    _user_engine = None
    try:
        from sqlalchemy.ext.asyncio import create_async_engine as _create_engine

        _user_engine = _create_engine(settings.postgres_dsn)
    except Exception as exc:
        logger.error("db_engine.init.failed", error=str(exc))

    # --- User store ---
    try:
        if _user_engine is None:
            raise RuntimeError("DB engine not initialized")
        from metatron.auth.user_store import UserStore

        user_store = UserStore(_user_engine)
        logger.info("user_store.init.starting")
        await user_store.ensure_schema()
        logger.info("user_store.schema.done")
        seeded = await user_store.seed_admin(settings.auth_password)
        if seeded:
            logger.info("user_store.admin.seeded", email="admin@metatron.local")
        app.state.user_store = user_store
        logger.info("user_store.ready")
    except Exception as exc:
        import traceback

        logger.error("user_store.init.failed", error=str(exc))
        traceback.print_exc()

    # --- Platform user mapper ---
    try:
        if _user_engine is None:
            raise RuntimeError("DB engine not initialized")
        from metatron.auth.user_mapping import PlatformUserMapper

        platform_mapper = PlatformUserMapper(_user_engine, user_store)
        await platform_mapper.ensure_schema()
        app.state.platform_mapper = platform_mapper
        logger.info("platform_mapper.ready")
    except Exception as exc:
        logger.warning("platform_mapper.init.failed", error=str(exc))

    # --- API Key store (personal keys for /v1 endpoints) ---
    try:
        if _user_engine is None:
            raise RuntimeError("DB engine not initialized")
        from metatron.auth.api_key_store import ApiKeyStore

        api_key_store = ApiKeyStore(_user_engine)
        await api_key_store.ensure_schema()
        app.state.api_key_store = api_key_store
        logger.info("api_key_store.ready")
    except Exception as exc:
        logger.error("api_key_store.init.failed", error=str(exc))

    # --- Open WebUI sync (bundled scenario) ---
    if settings.openwebui_url:
        try:
            from metatron.auth.openwebui_sync import OpenWebUISync

            owui_sync = OpenWebUISync(
                owui_url=settings.openwebui_url,
                metatron_url=settings.openwebui_metatron_url,
                admin_email="admin@metatron.local",
                admin_password=settings.auth_password,
            )
            await owui_sync.ensure_admin()
            app.state.owui_sync = owui_sync
            logger.info("owui_sync.configured", url=settings.openwebui_url)
        except Exception as exc:
            logger.warning("owui_sync.init.failed", error=str(exc))

    # --- PostgresStore (shared) ---
    from metatron.storage.postgres import PostgresStore

    store = PostgresStore(settings.postgres_dsn)
    app.state.postgres = store

    # --- ASOC admin-mode MCP client (MTRNIX-370 Phase 3) ---
    # Constructed once; shared by BootstrapRunner connector factory and
    # AsocSyncCron connector factory below.  AsocConnector.set_mcp_client()
    # injects it into each per-workspace connector instance.
    _asoc_admin_mcp: Any = None
    try:
        from metatron.integrations.asoc_mcp_client import (
            AsocMcpClient as _AdminMcpClient,
        )

        _asoc_admin_mcp = _AdminMcpClient.from_settings_admin(settings)
        if _asoc_admin_mcp is not None:
            app.state.asoc_admin_mcp_client = _asoc_admin_mcp
            logger.info(
                "asoc.admin_mcp_client.ready",
                mcp_url=settings.asoc_mcp_url or "(disabled)",
            )
        else:
            app.state.asoc_admin_mcp_client = None
            logger.warning(
                "asoc.admin_mcp_client.disabled",
                reason="ASOC_MCP_ADMIN_TOKEN not set — AsocConnector sync will fail at runtime",
            )
    except Exception as exc:
        logger.warning("asoc.admin_mcp_client.init_failed", error=str(exc))
        app.state.asoc_admin_mcp_client = None

    # --- ASOC workspace bootstrap infrastructure (MTRNIX-352, T2) ---
    _bootstrap_runner_task = None
    try:
        import asyncio as _asyncio

        from sqlalchemy.ext.asyncio import create_async_engine as _create_async_engine

        from metatron.workspaces.bootstrap.cron import BootstrapRetryCron as _RetryCron
        from metatron.workspaces.bootstrap.runner import BootstrapRunner as _BootstrapRunner
        from metatron.workspaces.bootstrap.store import BootstrapStateStore as _BootstrapStateStore
        from metatron.workspaces.manager import WorkspaceManager as _WsManager

        _bs_engine = getattr(app.state, "memory_pg_engine", None)
        if _bs_engine is None:
            _bs_engine = _create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
            app.state.memory_pg_engine = _bs_engine

        _bootstrap_store = _BootstrapStateStore(_bs_engine)
        app.state.bootstrap_state_store = _bootstrap_store

        def _connector_factory(workspace_id: str, source: str, config: dict[str, Any]) -> Any:
            from metatron.connectors.asoc import AsocConnector as _AsocConnector

            if source != "asoc":
                raise NotImplementedError(f"No connector available for source '{source}'")
            connector = _AsocConnector()
            # configure() is sync-compatible but is an async def — call synchronously
            # via asyncio.get_event_loop().run_until_complete() is not available here
            # because we are already inside the event loop.  Instead we store the
            # config and let the caller (BootstrapJob) call configure() asynchronously.
            # The BootstrapRunner calls connector_factory synchronously; we store the
            # config on the connector for deferred configure().
            # NOTE: BootstrapJob calls connector.fetch() after construction — the
            # async configure() path is used by the sync_cron's _make_asoc_connector.
            # Here we set internal state directly (avoids async call from sync context).
            connector._project_id = config.get("project_id", "")
            connector._instance_id = config.get("asoc_instance_id", "")
            # Inject the shared admin MCP client.
            _admin_mcp = getattr(app.state, "asoc_admin_mcp_client", None)
            if _admin_mcp is not None:
                connector.set_mcp_client(_admin_mcp)
            return connector

        async def _ingest_fn(documents: list[Any], workspace_id: str, **kwargs: Any) -> None:
            from metatron.ingestion.pipeline import ingest_documents

            await ingest_documents(documents, workspace_id, **kwargs)

        _bs_runner = _BootstrapRunner(
            state_store=_bootstrap_store,
            connector_factory=_connector_factory,
            ingest_fn=_ingest_fn,
            settings=settings,
        )
        app.state.bootstrap_runner = _bs_runner

        # Reclaim crash-orphaned bootstrapping rows from a previous crash.
        reclaimed = await _bs_runner.reclaim_stale_bootstrapping(
            stale_after_seconds=settings.asoc_bootstrap_stale_after_seconds,
        )
        if reclaimed:
            logger.info("bootstrap.reclaim.done", count=reclaimed)

        # Wire workspace_manager_async with all ASOC deps.
        from metatron.chat.persistence import ChatPersistence as _ChatPersistence

        _chat_pers = _ChatPersistence(_bs_engine)

        _ws_mgr_async = _WsManager(
            use_persistence=True,
            bootstrap_store=_bootstrap_store,
            chat_persistence=_chat_pers,
            pg_store=store,
            bootstrap_runner=_bs_runner,
        )
        app.state.workspace_manager_async = _ws_mgr_async

        # Start the retry cron.
        async def _stub_config_resolver(
            workspace_id: str,
        ) -> tuple[str, dict[str, Any]]:
            # TODO(T7): resolve (source, config) from connections table.
            raise NotImplementedError(
                f"config_resolver not yet wired for workspace '{workspace_id}'. "
                "Relies on in-memory task cache for retries within same process lifetime."
            )

        _retry_cron = _RetryCron(
            state_store=_bootstrap_store,
            runner=_bs_runner,
            config_resolver=_stub_config_resolver,
            interval_seconds=settings.asoc_bootstrap_retry_interval_seconds,
            max_attempts=settings.asoc_bootstrap_retry_max_attempts,
        )
        _bootstrap_runner_task = _asyncio.create_task(
            _retry_cron.run_forever(), name="bootstrap-retry-cron"
        )
        app.state.bootstrap_retry_cron_task = _bootstrap_runner_task
        logger.info("bootstrap.retry_cron.started")
    except Exception as exc:
        logger.warning("bootstrap.init.failed", error=str(exc))

    # --- ASOC delta-sync cron (MTRNIX-357, T7) ---
    # Runs in-process alongside BootstrapRetryCron. Polls bootstrap_state for
    # state='ready' workspaces and runs incremental AsocConnector.fetch() every
    # asoc_sync_interval_seconds. Per-workspace failures are isolated and logged.
    try:
        import asyncio as _asyncio_sync

        from metatron.workspaces.bootstrap.sync_cron import AsocSyncCron

        _bs_store_for_sync = getattr(app.state, "bootstrap_state_store", None)
        if _bs_store_for_sync is None:
            raise RuntimeError(
                "bootstrap_state_store not available — "
                "ASOC bootstrap init (T2) must succeed before T7 sync cron starts."
            )

        async def _make_asoc_connector(workspace_id: str) -> Any:
            """Resolve ASOC connection config from DB and return a configured AsocConnector."""
            from metatron.connectors.asoc import AsocConnector
            from metatron.core.models import Connection as _Connection

            _pg = getattr(app.state, "postgres", None)
            fernet_key = settings.fernet_key
            if _pg is None or not fernet_key:
                raise RuntimeError(
                    "postgres store or fernet_key not available — "
                    "cannot resolve ASOC connection for delta-sync."
                )
            # Find the 'asoc' connection for this workspace.
            connections_list = await _pg.list_connections(workspace_id, fernet_key)
            asoc_connections = [c for c in connections_list if c["connector_type"] == "asoc"]
            if not asoc_connections:
                raise RuntimeError(
                    f"No ASOC connection found for workspace '{workspace_id}' — "
                    "delta-sync requires a registered 'asoc' connector."
                )
            connection_id = asoc_connections[0]["id"]
            # Fetch with plaintext config for configure().
            conn_data = await _pg.get_connection_decrypted(connection_id, fernet_key)
            if conn_data is None:
                raise RuntimeError(
                    f"ASOC connection '{connection_id}' disappeared between list and get."
                )
            connection_obj = _Connection(
                id=conn_data["id"],
                workspace_id=conn_data["workspace_id"],
                connector_type=conn_data["connector_type"],
            )
            connector = AsocConnector()
            await connector.configure(connection_obj, conn_data["config"])
            # Inject the shared admin-mode MCP client (MTRNIX-370 Phase 3).
            _admin_mcp_for_sync = getattr(app.state, "asoc_admin_mcp_client", None)
            if _admin_mcp_for_sync is not None:
                connector.set_mcp_client(_admin_mcp_for_sync)
            return connector

        async def _ingest_documents_for_sync(documents: list[Any], workspace_id: str) -> None:
            from metatron.ingestion.pipeline import ingest_documents

            await ingest_documents(documents, workspace_id, incremental=True)

        _asoc_sync_cron = AsocSyncCron(
            state_store=_bs_store_for_sync,
            connector_factory=_make_asoc_connector,
            ingest_fn=_ingest_documents_for_sync,
            interval_seconds=settings.asoc_sync_interval_seconds,
            max_concurrent_workspaces=settings.asoc_sync_max_concurrent_workspaces,
        )
        _asoc_sync_task = _asyncio_sync.create_task(
            _asoc_sync_cron.run_forever(), name="asoc-sync-cron"
        )
        app.state.asoc_sync_cron = _asoc_sync_cron
        app.state.asoc_sync_task = _asoc_sync_task
        logger.info(
            "asoc.sync_cron.started",
            interval_seconds=settings.asoc_sync_interval_seconds,
            max_concurrent=settings.asoc_sync_max_concurrent_workspaces,
        )
    except Exception as exc:
        logger.warning("asoc.sync_cron.init_failed", error=str(exc))
        app.state.asoc_sync_cron = None
        app.state.asoc_sync_task = None

    # --- Channel manager (starts bots from DB config) ---
    if not getattr(app.state, "channel_manager", None):
        try:
            from metatron.agent.router import AgentRouter
            from metatron.channels.manager import ChannelManager

            agent_router = AgentRouter(settings=settings)
            channel_manager = ChannelManager(router=agent_router, store=store)
            started = await channel_manager.start_channels_from_db(
                fernet_key=settings.fernet_key,
                default_workspace_id=settings.default_workspace_id,
            )
            app.state.channel_manager = channel_manager
            logger.info("channel_manager.started", channels=started)
        except Exception as exc:
            logger.warning("channel_manager.startup_failed", error=str(exc))

    # --- ASOC session auth (MTRNIX-370 Phase 2a) ---
    # Validates X-ASOC-Session headers by calling asoc_get_current_user via
    # the user-mode MCP client. Requires asoc_mcp_admin_token to be set; if
    # not configured, app.state.asoc_session_auth is set to None so that the
    # asoc_chat_auth dependency returns 503 (fail-closed).
    try:
        from metatron.auth.asoc_session import AsocSessionAuth as _AsocSessionAuth
        from metatron.integrations.asoc_mcp_client import (
            AsocMcpClient as _AsocMcpClientForSession,
        )

        if settings.asoc_mcp_admin_token:
            _session_mcp = _AsocMcpClientForSession(
                url=settings.asoc_mcp_url,
                allowed_tools=settings.asoc_mcp_allowed_tools,
                request_timeout_seconds=settings.asoc_mcp_request_timeout_seconds,
                tool_list_cache_ttl_seconds=settings.asoc_mcp_tool_list_cache_ttl_seconds,
                retry_attempts=settings.asoc_mcp_retry_attempts,
                mode="user",
                admin_token=settings.asoc_mcp_admin_token,
            )
            app.state.asoc_session_auth = _AsocSessionAuth(
                mcp_client=_session_mcp,
                ttl_seconds=settings.asoc_session_cache_ttl_seconds,
            )
            logger.info(
                "asoc.session_auth.ready",
                ttl_seconds=settings.asoc_session_cache_ttl_seconds,
            )
        else:
            app.state.asoc_session_auth = None
            logger.warning(
                "asoc.session_auth.disabled",
                reason="ASOC_MCP_ADMIN_TOKEN not set",
            )
    except Exception as exc:
        logger.warning("asoc.session_auth.init_failed", error=str(exc))
        app.state.asoc_session_auth = None

    # --- ASOC MCP client (T6) + visibility filter (T5) + chat orchestrator (T4) ---
    # All components are initialised even if the LLM endpoint is not configured yet
    # (is_available=False) so the route can return 503 from
    # get_asoc_chat_orchestrator instead of a startup-time crash.
    # T5 (AsocVisibilityFilter) now uses the same user-mode AsocMcpClient as T6 —
    # constructed here so T5 and T6 share one client instance (MTRNIX-370 Phase 2b).
    _asoc_mcp_client = None
    _asoc_chat_provider = None
    try:
        from metatron.chat.asoc_orchestrator import AsocChatOrchestrator as _Orchestrator
        from metatron.chat.asoc_rate_limit import InMemoryTokenBucket as _Bucket
        from metatron.integrations.asoc_mcp_client import (
            AsocMcpClient as _AsocMcpClient,
        )
        from metatron.integrations.asoc_visibility import (
            AsocVisibilityFilter as _AsocVisibilityFilter,
        )
        from metatron.llm.asoc_chat_provider import (
            AsocStreamingChatProvider as _AsocProvider,
        )

        _asoc_mcp_client = _AsocMcpClient(
            url=settings.asoc_mcp_url,
            allowed_tools=settings.asoc_mcp_allowed_tools,
            request_timeout_seconds=settings.asoc_mcp_request_timeout_seconds,
            tool_list_cache_ttl_seconds=settings.asoc_mcp_tool_list_cache_ttl_seconds,
            retry_attempts=settings.asoc_mcp_retry_attempts,
            mode="user",
            admin_token=settings.asoc_mcp_admin_token or None,
        )
        app.state.asoc_mcp_client = _asoc_mcp_client

        # T5: visibility filter — uses user-mode MCP client; no separate httpx client.
        # asoc_base_url is still used by T1 (AsocConnector, Phase 3) — kept in Settings.
        _asoc_visibility_filter = _AsocVisibilityFilter.from_settings(
            settings, mcp_client=_asoc_mcp_client
        )
        app.state.asoc_visibility_filter = _asoc_visibility_filter
        logger.info(
            "asoc.visibility_filter.ready",
            mcp_url=settings.asoc_mcp_url or "(disabled)",
        )

        _asoc_chat_provider = _AsocProvider(
            base_url=settings.metatron_chat_api_base,
            api_key=settings.metatron_chat_api_key,
            model=settings.metatron_chat_model,
            temperature=settings.metatron_chat_temperature,
            max_tokens=settings.metatron_chat_max_tokens,
        )
        app.state.asoc_chat_provider = _asoc_chat_provider

        _asoc_rate_limiter = _Bucket(
            rate_per_min=settings.chat_rate_limit_per_min,
        )
        app.state.asoc_rate_limiter = _asoc_rate_limiter

        # ChatPersistence reuses the shared PG engine wired by bootstrap above.
        _chat_pers_orch = getattr(app.state, "workspace_manager_async", None)
        # Extract the chat persistence that bootstrap already created, or build one.
        _orch_chat_pers = None
        if _chat_pers_orch is not None:
            _orch_chat_pers = getattr(_chat_pers_orch, "_chat_persistence", None)
        if _orch_chat_pers is None:
            from metatron.chat.persistence import ChatPersistence as _ChatPers

            _bs_engine2 = app.state.memory_pg_engine
            _orch_chat_pers = _ChatPers(_bs_engine2)

        _asoc_orchestrator = _Orchestrator(
            persistence=_orch_chat_pers,
            bootstrap_store=app.state.bootstrap_state_store,
            asoc_visibility_filter=_asoc_visibility_filter,
            asoc_mcp_client=_asoc_mcp_client,
            asoc_chat_provider=_asoc_chat_provider,
            rate_limiter=_asoc_rate_limiter,
            settings=settings,
        )
        app.state.asoc_chat_orchestrator = _asoc_orchestrator
        logger.info(
            "asoc.chat_orchestrator.ready",
            llm_available=_asoc_chat_provider.is_available,
            model=settings.metatron_chat_model,
        )
    except Exception as exc:
        logger.warning("asoc.chat_orchestrator.init_failed", error=str(exc))
        app.state.asoc_chat_orchestrator = None
        app.state.asoc_visibility_filter = None

    # Initialize MCP session manager (required for streamable-http transport)
    async with mcp_server.session_manager.run():
        logger.info("mcp.session_manager.started")
        yield

    # Shutdown
    logger.info("app.shutdown")
    cm = getattr(app.state, "channel_manager", None)
    if cm is not None:
        await cm.stop_all()
    owui_sync = getattr(app.state, "owui_sync", None)
    if owui_sync and owui_sync._client:
        await owui_sync._client.close()

    # --- ASOC bootstrap shutdown ---
    cron_task = getattr(app.state, "bootstrap_retry_cron_task", None)
    if cron_task is not None and not cron_task.done():
        cron_task.cancel()
        import contextlib as _cl

        with _cl.suppress(Exception):
            await cron_task
    bs_runner = getattr(app.state, "bootstrap_runner", None)
    if bs_runner is not None:
        import contextlib as _cl2

        with _cl2.suppress(Exception):
            await bs_runner.shutdown()

    # --- ASOC delta-sync cron shutdown (MTRNIX-357, T7) ---
    sync_cron = getattr(app.state, "asoc_sync_cron", None)
    sync_task = getattr(app.state, "asoc_sync_task", None)
    if sync_cron is not None:
        sync_cron.stop()
    if sync_task is not None and not sync_task.done():
        sync_task.cancel()
        import contextlib as _cl_sync

        with _cl_sync.suppress(Exception):
            await sync_task

    # --- ASOC chat provider + MCP client shutdown ---
    # Note: AsocVisibilityFilter no longer holds its own httpx client (MTRNIX-370
    # Phase 2b — transport is now via the shared asoc_mcp_client below). No separate
    # aclose() call needed for the visibility filter.
    asoc_provider = getattr(app.state, "asoc_chat_provider", None)
    if asoc_provider is not None:
        import contextlib as _cl4

        with _cl4.suppress(Exception):
            await asoc_provider.aclose()

    asoc_mcp = getattr(app.state, "asoc_mcp_client", None)
    if asoc_mcp is not None and hasattr(asoc_mcp, "aclose"):
        import contextlib as _cl5

        with _cl5.suppress(Exception):
            await asoc_mcp.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a configured FastAPI application.

    Args:
        settings: App settings. If None, loaded from environment.

    Returns:
        Configured FastAPI instance.
    """
    if settings is None:
        settings = Settings()

    app = FastAPI(
        title="Metatron Core",
        description="AI knowledge agent for teams",
        version="0.1.0",
        lifespan=lifespan,
        redirect_slashes=False,
    )
    app.state.settings = settings

    # --- Plugin discovery (must happen before middleware/routes) ---
    plugin_manager = PluginManager()
    discover_plugins(plugin_manager)
    app.state.plugin_manager = plugin_manager

    # --- Subscribe core event handlers ---
    from metatron.core.events import SYNC_COMPLETED
    from metatron.retrieval.channels import on_sync_completed

    plugin_manager.get_event_bus().subscribe(SYNC_COMPLETED, on_sync_completed)

    # --- Subscribe activity logger (WS4 S6) ---
    if settings.activity_log_enabled:
        from sqlalchemy.ext.asyncio import create_async_engine

        from metatron.activity.logger import ActivityLogger
        from metatron.storage.activity_pg import ActivityStore

        # Reuse/initialize the shared PG engine stored on app.state (also used by
        # memory/ and agents/ dependencies). Create on demand if no earlier
        # dependency has run yet.
        engine = getattr(app.state, "memory_pg_engine", None)
        if engine is None:
            engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
            app.state.memory_pg_engine = engine

        activity_store = ActivityStore(engine)
        activity_logger_instance = ActivityLogger(store=activity_store)
        activity_logger_instance.subscribe(plugin_manager.get_event_bus())
        app.state.activity_store = activity_store
        app.state.activity_logger = activity_logger_instance
        logger.info("activity_logger.subscribed")

        # Point the MCP tool wrapper at this bus (WS4 S6).
        from metatron.mcp import server as _mcp_mod

        _mcp_mod.set_activity_bus_getter(lambda: plugin_manager.get_event_bus())

    # Enterprise plugin requires auth — auto-enable if any plugin loaded
    if plugin_manager.loaded_plugins and not settings.auth_enabled:
        settings = settings.model_copy(update={"auth_enabled": True})
        app.state.settings = settings
        logger.info("auth.auto_enabled", reason="enterprise plugin loaded")

    # CORS — credentials are only safe with explicit origins, not wildcard
    origins = settings.cors_origins_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=origins != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ASOC-specific CORS — browser-facing ASOC frontend origins.
    # For MVP this applies globally; ASOC chat is the only endpoint expected to be
    # called cross-origin from a browser. Refactor to per-route CORS if other
    # endpoints need different origins.
    if settings.asoc_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.asoc_allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-ASOC-Session"],
        )

    # Plugin middlewares — added before OptionalAuth so they become inner layers.
    # Starlette prepends each add_middleware call, so the last-added runs first.
    # Order: OptionalAuthMiddleware (outermost) → plugin middlewares → CORS → routes.
    # This ensures core JWT auth always sets request.state.user before RBAC checks it.
    for middleware_class, kwargs in plugin_manager.get_middlewares():
        app.add_middleware(middleware_class, **kwargs)
        logger.info("plugin.middleware.applied", middleware=middleware_class.__name__)

    # Auth middleware — added last, becomes outermost, runs first on every request
    app.add_middleware(OptionalAuthMiddleware)

    from metatron.api.middleware.agent_id import AgentIdContextMiddleware

    app.add_middleware(AgentIdContextMiddleware)

    # Register core route modules
    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(skills.router, prefix="/api/v1")
    app.include_router(connections.router, prefix="/api/v1")
    app.include_router(documents.router, prefix="/api/v1")
    app.include_router(workspaces.router, prefix="/api/v1")
    app.include_router(sync.router, prefix="/api/v1")
    app.include_router(benchmarker.router, prefix="/api/v1")
    app.include_router(dashboard.router, prefix="/api/v1")
    app.include_router(files.router, prefix="/api/v1")
    app.include_router(graph.router, prefix="/api/v1")
    app.include_router(config.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(memory.router, prefix="/api/v1")
    app.include_router(knowledge.router, prefix="/api/v1")
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(snapshots.router, prefix="/api/v1")
    app.include_router(asoc_chat.router, prefix="/api/v1/asoc")
    app.include_router(asoc_workspace.router, prefix="/api/v1")

    from metatron.api.routes.finops import router as finops_router

    app.include_router(finops_router, prefix="/api/v1")

    from metatron.api.routes.openwebui_import import router as owui_import_router

    app.include_router(owui_import_router, prefix="/api/v1")

    # OpenAI-compatible API (for Open WebUI integration)
    if settings.openai_compat_enabled:
        from metatron.api.routes.openai_compat import router as openai_compat_router

        app.include_router(openai_compat_router)

    # Lazy import benchmarker module router (optional dependency)
    try:
        from metatron.benchmarker.api import router as benchmarker_module_router

        app.include_router(benchmarker_module_router, prefix="/api/v1/benchmarker")
        logger.info("Benchmarker module loaded successfully")
    except ImportError as e:
        logger.warning(
            "Benchmarker module not available (missing optional dependencies): %s",
            e,
        )

    # Plugin routes — included after all core routes
    for router, prefix in plugin_manager.get_routes():
        app.include_router(router, prefix=prefix)
        logger.info("plugin.routes.applied", prefix=prefix or "(no prefix)")

    # Mount MCP server at /mcp
    # streamable_http_app() creates session_manager (initialized in lifespan).
    # We add the ASGI handler as a direct route — Starlette Mount breaks POST
    # without trailing slash (405), and methods=None confuses FastAPI.
    from starlette.routing import Route as StarletteRoute

    mcp_starlette_app = mcp_server.streamable_http_app()
    mcp_asgi_handler = mcp_starlette_app.routes[0].endpoint
    app.routes.append(
        StarletteRoute("/mcp", endpoint=mcp_asgi_handler, methods=["GET", "POST", "DELETE"]),
    )

    return app


def main() -> None:
    """Entry point for `metatron` CLI command."""
    settings = Settings()
    configure_logging(
        log_level=settings.log_level,
        json_output=settings.env != "development",
    )
    uvicorn.run(
        "metatron.api.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=settings.port,
        reload=settings.env == "development",
    )
