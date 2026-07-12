"""Uvicorn entry point for the standalone Core Agent HTTP app."""

from .http_agent_app import create_default_core_agent_http_app

app = create_default_core_agent_http_app()

__all__ = ["app"]
