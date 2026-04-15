"""
Processador de requisicoes HTTP para extracao via API.
"""

import asyncio
from typing import Any

import httpx

from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError


@register_processor("http_request")
class HttpRequestProcessor(BaseNodeProcessor):
    """Executa uma chamada HTTP com suporte a templates no payload."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        method = str(resolved_config.get("method", "GET")).upper()
        url = resolved_config.get("url")
        headers = resolved_config.get("headers") or {}
        query_params = resolved_config.get("query_params") or {}
        body = resolved_config.get("body")
        output_field = str(resolved_config.get("output_field", "data"))
        timeout_seconds = float(resolved_config.get("timeout_seconds", 30.0))
        fail_on_error = bool(resolved_config.get("fail_on_error", True))

        if not url:
            raise NodeProcessingError(
                f"No HTTP '{node_id}': url e obrigatoria."
            )

        try:
            response_payload = asyncio.run(
                self._execute_request(
                    method=method,
                    url=str(url),
                    headers=headers if isinstance(headers, dict) else {},
                    query_params=query_params if isinstance(query_params, dict) else {},
                    body=body,
                    timeout_seconds=timeout_seconds,
                )
            )
        except NodeProcessingError:
            if fail_on_error:
                raise
            return {
                "node_id": node_id,
                "status": "failed",
                output_field: None,
            }

        return {
            "node_id": node_id,
            "status": "completed",
            "output_field": output_field,
            output_field: response_payload["data"],
            "status_code": response_payload["status_code"],
            "response_headers": response_payload["headers"],
        }

    async def _execute_request(
        self,
        method: str,
        url: str,
        headers: dict[str, Any],
        query_params: dict[str, Any],
        body: Any,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        """Executa a chamada HTTP de forma assincrona com tratamento uniforme."""
        timeout = httpx.Timeout(timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                request_kwargs: dict[str, Any] = {
                    "method": method,
                    "url": url,
                    "headers": {
                        str(key): str(value)
                        for key, value in headers.items()
                        if value is not None
                    },
                    "params": query_params,
                }
                if isinstance(body, (dict, list)):
                    request_kwargs["json"] = body
                elif body is not None:
                    request_kwargs["content"] = str(body)

                response = await client.request(**request_kwargs)
                response.raise_for_status()
            except httpx.TimeoutException as exc:
                raise NodeProcessingError(
                    f"Timeout na requisicao HTTP para '{url}'."
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise NodeProcessingError(
                    f"Resposta HTTP invalida ({exc.response.status_code}) para '{url}'."
                ) from exc
            except httpx.HTTPError as exc:
                raise NodeProcessingError(
                    f"Falha ao executar requisicao HTTP para '{url}': {exc}"
                ) from exc

        return {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "data": self._parse_response(response),
        }

    @staticmethod
    def _parse_response(response: httpx.Response) -> Any:
        """Tenta ler JSON; se nao for possivel, retorna texto bruto."""
        content_type = response.headers.get("content-type", "").lower()
        if "application/json" in content_type:
            return response.json()

        try:
            return response.json()
        except ValueError:
            return response.text
