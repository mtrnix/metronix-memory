"""Plugin system — discovers and manages metronix-core extensions.

Enterprise plugins register via Python entry points (group="metronix.plugins").
Core discovers them at startup, calls plugin.register(manager), then wires
the collected extensions into the FastAPI application.

Usage — writing a plugin (e.g. metronix-enterprise):

    # pyproject.toml:
    # [project.entry-points."metronix.plugins"]
    # enterprise = "metronix_enterprise.plugin:EnterprisePlugin"

    class EnterprisePlugin:
        name = "enterprise"
        version = "1.0.0"

        def register(self, manager: PluginManager) -> None:
            manager.register_auth_provider(SAMLAuthBackend())
            manager.register_routes(enterprise_router, prefix="/api/v1/enterprise")
            manager.register_event_handler(QUERY_EXECUTED, audit_handler)
            manager.register_pipeline_hook("pre_search", EnrichQueryHook())
"""

from __future__ import annotations

import importlib.metadata
from typing import Any, Protocol, runtime_checkable

import structlog

from metronix.core.events import EventBus, EventHandlerCallable
from metronix.core.interfaces import AuthBackendInterface, PipelineHook

logger = structlog.get_logger()


@runtime_checkable
class MetronixPlugin(Protocol):
    """Interface every metronix plugin must satisfy.

    The entry point value must be a class (not an instance) implementing
    this protocol. Core calls ``PluginClass()`` to instantiate, then
    ``plugin.register(manager)``.

    Attributes:
        name:    Short identifier, e.g. "enterprise". Used in logs.
        version: Semver string, e.g. "1.2.0".
    """

    name: str
    version: str

    def register(self, manager: PluginManager) -> None:
        """Register all extensions this plugin provides.

        Called once at startup. Use manager.register_* to add
        auth providers, routes, event handlers, pipeline hooks, etc.
        """
        ...


class PluginManager:
    """Central registry for all plugin-provided extensions.

    Created once in ``create_app()``, stored in ``app.state.plugin_manager``.
    Plugins call ``register_*`` methods during ``plugin.register(manager)``.
    After discovery, ``apply_to_app(app)`` wires everything into FastAPI.

    All getters return copies of internal lists to prevent mutation.
    """

    def __init__(self) -> None:
        self._auth_provider: AuthBackendInterface | None = None
        self._middlewares: list[tuple[type, dict[str, Any]]] = []
        # Stored as (router, prefix) — router is Any to avoid FastAPI import in L0
        self._routes: list[tuple[Any, str]] = []
        self._pipeline_hooks: dict[str, list[PipelineHook]] = {}
        self._sso_providers: list[Any] = []
        self._event_bus: EventBus = EventBus()
        self._loaded_plugins: list[str] = []

    # ------------------------------------------------------------------
    # Registration API — called by plugins inside register()
    # ------------------------------------------------------------------

    def register_auth_provider(self, provider: AuthBackendInterface) -> None:
        """Replace the default JWT auth with a custom backend (SAML, OIDC, etc.).

        Only one auth provider is active at a time. A second registration
        overwrites the first and logs a warning.

        Args:
            provider: An implementation of AuthBackendInterface.
        """
        if self._auth_provider is not None:
            logger.warning(
                "plugin_manager.auth_provider.overwrite",
                previous=type(self._auth_provider).__name__,
                new=type(provider).__name__,
            )
        self._auth_provider = provider
        logger.info(
            "plugin_manager.auth_provider.registered",
            provider=type(provider).__name__,
        )

    def register_middleware(self, middleware_class: type, **kwargs: Any) -> None:
        """Add a Starlette/FastAPI middleware class.

        kwargs are forwarded to ``app.add_middleware(middleware_class, **kwargs)``.
        Plugin middlewares are applied after the core middlewares (CORS, OptionalAuth).

        Args:
            middleware_class: The middleware class to register.
            **kwargs: Additional keyword arguments for the middleware constructor.
        """
        self._middlewares.append((middleware_class, kwargs))
        logger.info(
            "plugin_manager.middleware.registered",
            middleware=middleware_class.__name__,
        )

    def register_event_handler(
        self,
        event_name: str,
        handler: EventHandlerCallable,
    ) -> None:
        """Subscribe an async handler to a core event.

        Use the event name constants from ``metronix.core.events``
        (e.g. DOCUMENT_INDEXED, QUERY_EXECUTED).

        Args:
            event_name: Name of the event to subscribe to.
            handler: Async callable ``(event_name: str, payload: dict) -> None``.
        """
        self._event_bus.subscribe(event_name, handler)

    def register_routes(self, router: Any, prefix: str = "") -> None:
        """Add an APIRouter to be included in the FastAPI application.

        Routes are included after all core routes to avoid prefix conflicts.

        Args:
            router: A ``fastapi.APIRouter`` instance.
            prefix: URL prefix, e.g. ``"/api/v1/enterprise"``.
        """
        self._routes.append((router, prefix))
        logger.info("plugin_manager.routes.registered", prefix=prefix or "(no prefix)")

    def register_pipeline_hook(self, hook_name: str, hook: PipelineHook) -> None:
        """Register a hook in the search or ingestion pipeline.

        Hook names follow the convention ``"{stage}_{point}"``:
        - ``"pre_search"`` / ``"post_search"``
        - ``"pre_chunk"`` / ``"post_chunk"``
        - ``"pre_index"`` / ``"post_index"``

        Each hook receives a context dict and must return it (possibly modified).

        Args:
            hook_name: Stage identifier.
            hook: Callable matching PipelineHook protocol.
        """
        if hook_name not in self._pipeline_hooks:
            self._pipeline_hooks[hook_name] = []
        self._pipeline_hooks[hook_name].append(hook)
        logger.info(
            "plugin_manager.pipeline_hook.registered",
            hook_name=hook_name,
            hook=type(hook).__name__,
        )

    def register_sso_provider(self, provider: Any) -> None:
        """Register an SSO provider (enterprise auth extension).

        Providers are stored and exposed via ``get_sso_providers()`` to
        enterprise auth routes that need them.

        Args:
            provider: An SSO provider instance (interface defined by enterprise).
        """
        self._sso_providers.append(provider)
        logger.info(
            "plugin_manager.sso_provider.registered",
            provider=type(provider).__name__,
        )

    # ------------------------------------------------------------------
    # Query API — called by core at runtime
    # ------------------------------------------------------------------

    def get_auth_provider(self) -> AuthBackendInterface | None:
        """Return the plugin-registered auth provider.

        Returns:
            AuthBackendInterface if a plugin registered one, None otherwise.
            None means core should use the default JWT auth.
        """
        return self._auth_provider

    def get_event_bus(self) -> EventBus:
        """Return the shared event bus.

        Core uses this to emit events; plugins subscribe via register_event_handler.
        """
        return self._event_bus

    def get_middlewares(self) -> list[tuple[type, dict[str, Any]]]:
        """Return a copy of registered (middleware_class, kwargs) pairs."""
        return list(self._middlewares)

    def get_routes(self) -> list[tuple[Any, str]]:
        """Return a copy of registered (router, prefix) pairs."""
        return list(self._routes)

    def get_pipeline_hooks(self, hook_name: str) -> list[PipelineHook]:
        """Return all hooks registered for a pipeline stage.

        Args:
            hook_name: Pipeline stage identifier (e.g. "pre_search").

        Returns:
            List of hooks in registration order, empty list if none registered.
        """
        return list(self._pipeline_hooks.get(hook_name, []))

    def get_sso_providers(self) -> list[Any]:
        """Return a copy of registered SSO providers."""
        return list(self._sso_providers)

    @property
    def loaded_plugins(self) -> list[str]:
        """Names of successfully loaded plugins, in load order."""
        return list(self._loaded_plugins)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _record_loaded(self, name: str) -> None:
        """Mark a plugin as successfully loaded. Called by discover_plugins."""
        self._loaded_plugins.append(name)

    def apply_to_app(self, app: Any) -> None:
        """Wire all registered extensions into a FastAPI application.

        Called once in create_app() after plugin discovery. Applies:
        - Middlewares (via app.add_middleware)
        - Routes (via app.include_router)

        Args:
            app: The FastAPI application instance.
        """
        for middleware_class, kwargs in self._middlewares:
            app.add_middleware(middleware_class, **kwargs)
            logger.info(
                "plugin_manager.middleware.applied",
                middleware=middleware_class.__name__,
            )

        for router, prefix in self._routes:
            app.include_router(router, prefix=prefix)
            logger.info(
                "plugin_manager.routes.applied",
                prefix=prefix or "(no prefix)",
            )


def discover_plugins(manager: PluginManager) -> None:
    """Discover and load all installed metronix plugins via entry points.

    Scans the ``"metronix.plugins"`` entry point group. Each entry point
    must resolve to a class implementing ``MetronixPlugin``.

    Fault-tolerant: a failing plugin is logged and skipped. Core always
    starts regardless of plugin failures.

    Args:
        manager: The PluginManager passed to each plugin's register().
    """
    try:
        eps = importlib.metadata.entry_points(group="metronix.plugins")
    except Exception as exc:
        logger.error("plugin_discovery.entry_points_failed", error=str(exc))
        return

    for ep in eps:
        plugin_name = ep.name
        try:
            plugin_cls = ep.load()
            plugin = plugin_cls()
            plugin.register(manager)
            manager._record_loaded(plugin_name)
            logger.info(
                "plugin.loaded",
                name=plugin_name,
                version=getattr(plugin, "version", "unknown"),
            )
        except Exception as exc:
            logger.error(
                "plugin.load_failed",
                name=plugin_name,
                error=str(exc),
                exc_info=True,
            )

    if manager.loaded_plugins:
        logger.info("plugins.discovery_complete", plugins=manager.loaded_plugins)
    else:
        logger.debug("plugins.none_found", group="metronix.plugins")
