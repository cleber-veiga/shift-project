"""
Processador do no de entrada de API REST paginada.

Faz requisicoes HTTP em loop seguindo a estrategia de paginacao configurada,
extrai o array de registros de cada resposta via ``data_path`` (notacao de
pontos: ``$.data.items``) e materializa tudo em DuckDB usando ``JsonlStreamer``.

Estrategia de memoria
---------------------
Cada pagina e processada e descartada antes de buscar a proxima.
O ``JsonlStreamer`` grava em disco incrementalmente, de modo que o consumo
de RAM do processo Python e proporcional ao tamanho de uma unica pagina,
nao ao volume total de dados.

Tipos de paginacao suportados
------------------------------
none
    Requisicao unica. Toda a resposta e ingerida de uma vez.

offset
    Incrementa o parametro de offset a cada pagina.
    pagination_config: {offset_param="offset", limit_param="limit", limit=100}

page_number
    Incrementa o numero da pagina a cada requisicao.
    pagination_config: {page_param="page", page_size_param="per_page", page_size=100, start_page=1}

cursor
    Extrai o cursor da resposta e o passa como parametro da proxima requisicao.
    pagination_config: {cursor_param="cursor", next_cursor_path="$.meta.next_cursor"}

next_url
    Extrai a URL da proxima pagina diretamente da resposta.
    pagination_config: {next_url_path="$.links.next"}

Autenticacao suportada (campo ``auth``)
----------------------------------------
bearer  : {"type": "bearer", "token": "..."}
basic   : {"type": "basic", "username": "...", "password": "..."}
api_key : {"type": "api_key", "header": "X-API-Key", "value": "..."}

Configuracao completa:
- url              : URL base da API (obrigatorio)
- method           : metodo HTTP (padrao: "GET")
- headers          : headers adicionais (dict)
- body             : corpo da requisicao (para POST/PUT)
- data_path        : JSONPath para o array de registros (padrao: "$")
- auth             : dict de autenticacao (opcional)
- pagination_type  : "none" | "offset" | "page_number" | "cursor" | "next_url"
- pagination_config: dict com parametros especificos da paginacao
- max_records      : limite total de registros (None = sem limite)
- max_pages        : limite de paginas como salvaguarda contra loops infinitos
- timeout_seconds  : timeout por requisicao em segundos (padrao: 30)
- output_field     : nome do campo de saida (padrao: "data")
"""

from typing import Any
from uuid import uuid4

import httpx

from app.core.config import settings
from app.data_pipelines.duckdb_storage import JsonlStreamer
from app.services.workflow.nodes import BaseNodeProcessor, register_processor
from app.services.workflow.nodes.exceptions import NodeProcessingError

_DEFAULT_MAX_PAGES = 10_000   # salvaguarda contra loops infinitos
_DEFAULT_TIMEOUT = 30.0


@register_processor("api_input")
class ApiInputNodeProcessor(BaseNodeProcessor):
    """Extrai dados de APIs REST paginadas e materializa em DuckDB via streaming."""

    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_config = self.resolve_data(config, context)
        url = resolved_config.get("url")
        method = str(resolved_config.get("method", "GET")).upper()
        headers: dict[str, str] = resolved_config.get("headers") or {}
        body = resolved_config.get("body")
        data_path = str(resolved_config.get("data_path", "$"))
        auth_config: dict[str, Any] | None = resolved_config.get("auth")
        pagination_type = str(resolved_config.get("pagination_type", "none")).lower()
        pagination_config: dict[str, Any] = resolved_config.get("pagination_config") or {}
        preview_max_rows: int | None = context.get("_preview_max_rows")
        configured_max_records = resolved_config.get("max_records")
        max_records: int | None = (
            preview_max_rows
            if preview_max_rows is not None
            else (int(configured_max_records) if configured_max_records is not None else settings.EXTRACT_DEFAULT_MAX_ROWS)
        )
        max_pages = int(resolved_config.get("max_pages", _DEFAULT_MAX_PAGES))
        timeout_seconds = float(resolved_config.get("timeout_seconds", _DEFAULT_TIMEOUT))
        output_field = str(resolved_config.get("output_field", "data"))

        if not url:
            raise NodeProcessingError(
                f"No api_input '{node_id}': 'url' e obrigatorio."
            )

        valid_types = {"none", "offset", "page_number", "cursor", "next_url"}
        if pagination_type not in valid_types:
            raise NodeProcessingError(
                f"No api_input '{node_id}': pagination_type '{pagination_type}' invalido. "
                f"Opcoes: {sorted(valid_types)}"
            )

        execution_id = str(
            context.get("execution_id") or context.get("workflow_id") or uuid4()
        )

        # Monta headers de autenticacao
        auth_headers = _build_auth_headers(auth_config, node_id)
        all_headers = {**headers, **auth_headers}

        # Monta a autenticacao HTTPx para basic auth
        httpx_auth = _build_httpx_auth(auth_config)

        timeout = httpx.Timeout(connect=10.0, read=timeout_seconds, write=30.0, pool=5.0)

        with JsonlStreamer(execution_id, node_id) as streamer:
            _paginate(
                streamer=streamer,
                node_id=node_id,
                base_url=str(url),
                method=method,
                headers=all_headers,
                body=body,
                data_path=data_path,
                pagination_type=pagination_type,
                pagination_config=pagination_config,
                max_records=max_records,
                max_pages=max_pages,
                timeout=timeout,
                auth=httpx_auth,
            )

        if streamer.reference is None:
            raise NodeProcessingError(
                f"No api_input '{node_id}': API nao retornou nenhum registro."
            )

        return {
            "node_id": node_id,
            "status": "completed",
            "row_count": streamer.row_count,
            "output_field": output_field,
            output_field: streamer.reference,
        }


# ---------------------------------------------------------------------------
# Motor de paginacao
# ---------------------------------------------------------------------------

def _paginate(
    streamer: JsonlStreamer,
    node_id: str,
    base_url: str,
    method: str,
    headers: dict[str, str],
    body: Any,
    data_path: str,
    pagination_type: str,
    pagination_config: dict[str, Any],
    max_records: int | None,
    max_pages: int,
    timeout: httpx.Timeout,
    auth: Any,
) -> None:
    """Executa as requisicoes em loop de acordo com o tipo de paginacao."""
    with httpx.Client(
        headers=headers,
        timeout=timeout,
        auth=auth,
        follow_redirects=True,
    ) as client:
        if pagination_type == "none":
            _fetch_single(client, streamer, node_id, base_url, method, body, data_path)

        elif pagination_type == "offset":
            _paginate_offset(
                client, streamer, node_id, base_url, method, body,
                data_path, pagination_config, max_records, max_pages,
            )

        elif pagination_type == "page_number":
            _paginate_page_number(
                client, streamer, node_id, base_url, method, body,
                data_path, pagination_config, max_records, max_pages,
            )

        elif pagination_type == "cursor":
            _paginate_cursor(
                client, streamer, node_id, base_url, method, body,
                data_path, pagination_config, max_records, max_pages,
            )

        elif pagination_type == "next_url":
            _paginate_next_url(
                client, streamer, node_id, base_url, method, body,
                data_path, pagination_config, max_records, max_pages,
            )


def _fetch_single(
    client: httpx.Client,
    streamer: JsonlStreamer,
    node_id: str,
    url: str,
    method: str,
    body: Any,
    data_path: str,
    extra_params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Faz uma unica requisicao, extrai os registros e os grava no streamer."""
    response = _execute_request(client, node_id, url, method, body, extra_params or {})
    records = _extract_records(response, data_path)
    if records:
        streamer.write_batch(records)
    return records


def _paginate_offset(
    client: httpx.Client,
    streamer: JsonlStreamer,
    node_id: str,
    base_url: str,
    method: str,
    body: Any,
    data_path: str,
    cfg: dict[str, Any],
    max_records: int | None,
    max_pages: int,
) -> None:
    """
    Paginacao por offset: incrementa o param de offset ate a API retornar
    menos registros do que o limite (indicando ultima pagina).
    """
    offset_param = str(cfg.get("offset_param", "offset"))
    limit_param = str(cfg.get("limit_param", "limit"))
    limit = int(cfg.get("limit", 100))
    offset = int(cfg.get("initial_offset", 0))

    for page_num in range(max_pages):
        params = {offset_param: offset, limit_param: limit}
        response = _execute_request(client, node_id, base_url, method, body, params)
        records = _extract_records(response, data_path)

        if not records:
            break

        streamer.write_batch(records)
        offset += len(records)

        if max_records and streamer.row_count >= max_records:
            break
        if len(records) < limit:
            # Ultima pagina (retornou menos do que o limite pedido)
            break

        if page_num == max_pages - 1:
            raise NodeProcessingError(
                f"No api_input '{node_id}': limite de paginas ({max_pages}) atingido "
                "antes do fim da paginacao por offset. Aumente 'max_pages'."
            )


def _paginate_page_number(
    client: httpx.Client,
    streamer: JsonlStreamer,
    node_id: str,
    base_url: str,
    method: str,
    body: Any,
    data_path: str,
    cfg: dict[str, Any],
    max_records: int | None,
    max_pages: int,
) -> None:
    """Paginacao por numero de pagina: incrementa page=1,2,3,..."""
    page_param = str(cfg.get("page_param", "page"))
    page_size_param = str(cfg.get("page_size_param", "per_page"))
    page_size = int(cfg.get("page_size", 100))
    page = int(cfg.get("start_page", 1))

    for _ in range(max_pages):
        params = {page_param: page, page_size_param: page_size}
        response = _execute_request(client, node_id, base_url, method, body, params)
        records = _extract_records(response, data_path)

        if not records:
            break

        streamer.write_batch(records)
        page += 1

        if max_records and streamer.row_count >= max_records:
            break
        if len(records) < page_size:
            break
    else:
        raise NodeProcessingError(
            f"No api_input '{node_id}': limite de paginas ({max_pages}) atingido. "
            "Aumente 'max_pages'."
        )


def _paginate_cursor(
    client: httpx.Client,
    streamer: JsonlStreamer,
    node_id: str,
    base_url: str,
    method: str,
    body: Any,
    data_path: str,
    cfg: dict[str, Any],
    max_records: int | None,
    max_pages: int,
) -> None:
    """
    Paginacao por cursor: extrai o proximo cursor da resposta e
    o passa como parametro na proxima requisicao.
    """
    cursor_param = str(cfg.get("cursor_param", "cursor"))
    next_cursor_path = str(cfg.get("next_cursor_path", "$.meta.next_cursor"))
    cursor: str | None = cfg.get("initial_cursor")

    for _ in range(max_pages):
        params = {cursor_param: cursor} if cursor is not None else {}
        response = _execute_request(client, node_id, base_url, method, body, params)
        records = _extract_records(response, data_path)

        if not records:
            break

        streamer.write_batch(records)

        if max_records and streamer.row_count >= max_records:
            break

        next_cursor = _resolve_path(response, next_cursor_path)
        if not next_cursor:
            break  # Sem proximo cursor: ultima pagina

        cursor = str(next_cursor)
    else:
        raise NodeProcessingError(
            f"No api_input '{node_id}': limite de paginas ({max_pages}) atingido. "
            "Aumente 'max_pages'."
        )


def _paginate_next_url(
    client: httpx.Client,
    streamer: JsonlStreamer,
    node_id: str,
    base_url: str,
    method: str,
    body: Any,
    data_path: str,
    cfg: dict[str, Any],
    max_records: int | None,
    max_pages: int,
) -> None:
    """
    Paginacao por URL: extrai a URL da proxima pagina da resposta e
    a usa como destino da proxima requisicao.
    """
    next_url_path = str(cfg.get("next_url_path", "$.next"))
    current_url: str | None = base_url

    for _ in range(max_pages):
        if not current_url:
            break

        response = _execute_request(client, node_id, current_url, method, body, {})
        records = _extract_records(response, data_path)

        if records:
            streamer.write_batch(records)

        if max_records and streamer.row_count >= max_records:
            break

        next_url = _resolve_path(response, next_url_path)
        current_url = str(next_url) if next_url else None

        if not current_url:
            break
    else:
        raise NodeProcessingError(
            f"No api_input '{node_id}': limite de paginas ({max_pages}) atingido. "
            "Aumente 'max_pages'."
        )


# ---------------------------------------------------------------------------
# Auxiliares HTTP
# ---------------------------------------------------------------------------

def _execute_request(
    client: httpx.Client,
    node_id: str,
    url: str,
    method: str,
    body: Any,
    params: dict[str, Any],
) -> Any:
    """Executa uma requisicao e retorna o JSON decodificado."""
    try:
        kwargs: dict[str, Any] = {"params": params}
        if body is not None:
            if isinstance(body, (dict, list)):
                kwargs["json"] = body
            else:
                kwargs["content"] = str(body).encode()

        response = client.request(method, url, **kwargs)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "json" in content_type or response.text.strip().startswith(("{", "[")):
            return response.json()
        # Resposta nao-JSON: retorna como string para que _extract_records trate
        return response.text

    except httpx.HTTPStatusError as exc:
        raise NodeProcessingError(
            f"No api_input '{node_id}': API retornou HTTP {exc.response.status_code} "
            f"em {url}"
        ) from exc
    except httpx.RequestError as exc:
        raise NodeProcessingError(
            f"No api_input '{node_id}': erro de rede — {exc}"
        ) from exc


def _build_auth_headers(auth_config: dict[str, Any] | None, node_id: str) -> dict[str, str]:
    """Monta headers de autenticacao a partir da configuracao."""
    if not auth_config:
        return {}

    auth_type = str(auth_config.get("type", "")).lower()

    if auth_type == "bearer":
        token = auth_config.get("token")
        if not token:
            raise NodeProcessingError(
                f"No api_input '{node_id}': auth.token e obrigatorio para bearer."
            )
        return {"Authorization": f"Bearer {token}"}

    if auth_type == "api_key":
        header = str(auth_config.get("header", "X-API-Key"))
        value = auth_config.get("value")
        if not value:
            raise NodeProcessingError(
                f"No api_input '{node_id}': auth.value e obrigatorio para api_key."
            )
        return {header: str(value)}

    # basic e tratado pelo httpx.BasicAuth
    return {}


def _build_httpx_auth(auth_config: dict[str, Any] | None) -> Any:
    """Retorna objeto httpx.BasicAuth se configurado, None caso contrario."""
    if not auth_config:
        return None
    if str(auth_config.get("type", "")).lower() == "basic":
        return httpx.BasicAuth(
            username=str(auth_config.get("username", "")),
            password=str(auth_config.get("password", "")),
        )
    return None


# ---------------------------------------------------------------------------
# Auxiliares de dados
# ---------------------------------------------------------------------------

def _extract_records(response_data: Any, data_path: str) -> list[dict[str, Any]]:
    """
    Extrai o array de registros da resposta usando o data_path.

    - Se data_path='$' ou vazio, usa a raiz da resposta.
    - Se o resultado for uma lista, retorna-a.
    - Se for um dict, encapsula em lista.
    - Outros tipos retornam [{"value": valor}].
    """
    if not data_path or data_path == "$":
        data = response_data
    else:
        data = _resolve_path(response_data, data_path)

    if data is None:
        return []
    if isinstance(data, list):
        return [
            item if isinstance(item, dict) else {"value": item}
            for item in data
        ]
    if isinstance(data, dict):
        return [data]
    return [{"value": data}]


def _resolve_path(obj: Any, path: str) -> Any:
    """
    Resolvedor simples de JSONPath com notacao de pontos.

    Suporta:
        $                   → raiz
        $.key               → obj["key"]
        $.key.subkey        → obj["key"]["subkey"]
        $.items[0]          → nao suportado (retorna None)

    Para JSONPath completo, use a biblioteca ``jsonpath-ng``.
    """
    if not path or path == "$":
        return obj

    # Remove prefixo '$.' ou '$'
    normalized = path.lstrip("$").lstrip(".")
    if not normalized:
        return obj

    parts = normalized.split(".")
    current = obj
    for part in parts:
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            idx = int(part)
            current = current[idx] if 0 <= idx < len(current) else None
        else:
            return None
        if current is None:
            return None

    return current
