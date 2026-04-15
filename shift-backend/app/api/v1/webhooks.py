"""Compatibilidade para imports legados do router de webhooks."""

from app.api.v1.endpoints.webhooks import router

__all__ = ["router"]
