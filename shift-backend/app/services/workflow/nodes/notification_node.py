"""
Processador do no de notificacao.

Envia alertas durante o fluxo via webhook, Slack ou e-mail.
Nao altera os dados — retorna a referencia upstream intacta (pass-through).

O campo ``message`` suporta placeholders resolvidos via ``resolve_template``
antes do envio, permitindo incluir valores do contexto de execucao
(ex: ``{{upstream_results.assert_1.status}}``).

Canais suportados
-----------------
webhook
    Envia POST JSON para a URL configurada.
    credentials: {url, headers?, payload_template?}
    Se ``payload_template`` nao for informado, envia ``{"message": "<msg>"}``.

slack
    Envia mensagem via Incoming Webhook do Slack.
    credentials: {webhook_url}

email
    Envia e-mail via SMTP com STARTTLS.
    credentials: {smtp_host, smtp_port, smtp_user?, smtp_password?,
                  from, to (str ou lista), subject?}

Configuracao:
- channel      : "webhook" | "slack" | "email"
- message      : texto da mensagem (suporta placeholders)
- credentials  : dict com dados de autenticacao do canal
- output_field : nome do campo de saida (padrao: "data")
"""

import logging
import smtplib
from email.mime.text import MIMEText
from typing import Any

import httpx

from app.data_pipelines.duckdb_storage import find_duckdb_reference
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError

logger = logging.getLogger(__name__)

_VALID_CHANNELS = {"webhook", "slack", "email"}


@register_processor("notification")
class NotificationNodeProcessor(BaseNodeProcessor):
    """Envia alertas via webhook, Slack ou e-mail sem alterar o fluxo de dados."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        # Resolve o template da mensagem antes de processar o restante do config
        # para que placeholders acessem o contexto completo (incluindo upstream_results).
        raw_message = config.get("message", "")
        message = self.resolve_template(str(raw_message), context) if raw_message else ""

        config_without_message = {k: v for k, v in config.items() if k != "message"}
        resolved_config = self.resolve_data(config_without_message, context)

        channel = str(resolved_config.get("channel", "webhook")).lower()
        credentials: dict[str, Any] = resolved_config.get("credentials") or {}
        output_field = str(resolved_config.get("output_field", "data"))

        if channel not in _VALID_CHANNELS:
            raise NodeProcessingError(
                f"No notification '{node_id}': channel deve ser um de {_VALID_CHANNELS}."
            )

        if channel == "webhook":
            self._send_webhook(node_id, message, credentials)
        elif channel == "slack":
            self._send_slack(node_id, message, credentials)
        elif channel == "email":
            self._send_email(node_id, message, credentials)

        # Pass-through: localiza e devolve a referencia upstream sem modificar.
        output_data = self._find_passthrough(context)

        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            output_field: output_data,
        }

    # ------------------------------------------------------------------
    # Canais de envio
    # ------------------------------------------------------------------

    def _send_webhook(self, node_id: str, message: str, credentials: dict) -> None:
        url = credentials.get("url")
        if not url:
            raise NodeProcessingError(
                f"No notification '{node_id}': 'credentials.url' e obrigatorio para webhook."
            )
        headers: dict = credentials.get("headers") or {"Content-Type": "application/json"}
        payload: dict = dict(credentials.get("payload_template") or {})
        if not payload:
            payload = {"message": message}
        elif "message" not in payload:
            payload["message"] = message

        with httpx.Client(timeout=30.0) as client:
            response = client.post(str(url), json=payload, headers=headers)

        if response.is_error:
            raise NodeProcessingError(
                f"No notification '{node_id}': webhook retornou HTTP {response.status_code}."
            )
        logger.info("Notificacao webhook enviada pelo no '%s'.", node_id)

    def _send_slack(self, node_id: str, message: str, credentials: dict) -> None:
        webhook_url = credentials.get("webhook_url")
        if not webhook_url:
            raise NodeProcessingError(
                f"No notification '{node_id}': 'credentials.webhook_url' e obrigatorio para Slack."
            )
        with httpx.Client(timeout=30.0) as client:
            response = client.post(str(webhook_url), json={"text": message})

        if response.is_error:
            raise NodeProcessingError(
                f"No notification '{node_id}': Slack retornou HTTP {response.status_code}."
            )
        logger.info("Notificacao Slack enviada pelo no '%s'.", node_id)

    def _send_email(self, node_id: str, message: str, credentials: dict) -> None:
        smtp_host = str(credentials.get("smtp_host", "localhost"))
        smtp_port = int(credentials.get("smtp_port", 587))
        smtp_user = credentials.get("smtp_user")
        smtp_password = credentials.get("smtp_password")
        from_addr = credentials.get("from")
        to_addrs = credentials.get("to")
        subject = str(credentials.get("subject", "Notificacao Shift"))

        if not from_addr or not to_addrs:
            raise NodeProcessingError(
                f"No notification '{node_id}': 'credentials.from' e 'credentials.to' "
                "sao obrigatorios para email."
            )

        recipients: list[str] = (
            [to_addrs] if isinstance(to_addrs, str) else list(to_addrs)
        )

        msg = MIMEText(message, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = str(from_addr)
        msg["To"] = ", ".join(recipients)

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            if smtp_user and smtp_password:
                server.login(str(smtp_user), str(smtp_password))
            server.sendmail(str(from_addr), recipients, msg.as_string())

        logger.info("Notificacao email enviada pelo no '%s'.", node_id)

    # ------------------------------------------------------------------
    # Pass-through helper
    # ------------------------------------------------------------------

    @staticmethod
    def _find_passthrough(context: dict[str, Any]) -> Any:
        """
        Localiza o valor de saida do ultimo no upstream para repassar intacto.

        Prioriza referencia DuckDB; caso nao exista (ex: upstream e trigger ou
        HTTP), retorna o payload bruto do ultimo upstream.
        """
        upstream_results: dict[str, Any] = context.get("upstream_results", {})
        if not upstream_results:
            return None

        last_result = list(upstream_results.values())[-1]

        ref = find_duckdb_reference(last_result)
        if ref is not None:
            return ref

        if isinstance(last_result, dict):
            output_field_name = last_result.get("output_field")
            if isinstance(output_field_name, str) and output_field_name in last_result:
                return last_result[output_field_name]

        return last_result
