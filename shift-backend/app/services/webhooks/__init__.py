"""Modulos de seguranca e limites operacionais dos webhooks de saida."""

from app.services.webhooks.url_validator import (  # noqa: F401
    WebhookUrlError,
    validate_webhook_url,
)
