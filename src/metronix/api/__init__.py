"""API layer — FastAPI HTTP endpoints. Top layer, depends on everything."""

from metronix.api.app import create_app

__all__ = ["create_app"]
