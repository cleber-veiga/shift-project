"""
Schemas Pydantic para workflows do React Flow.
Usa discriminated unions para validar configuracoes por tipo de no.
"""

from datetime import datetime
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# --- Operacoes de Transformacao Legadas ---

class RenameOperation(BaseModel):
    """Renomeia um campo de origem para um novo nome."""

    op: Literal["rename"]
    field_from: str
    field_to: str


class FilterOperation(BaseModel):
    """Filtra registros com base em uma condicao simples."""

    op: Literal["filter"]
    field: str
    operator: Literal["eq", "ne", "gt", "lt", "gte", "lte", "contains"]
    value: Any


TransformOperation = Annotated[
    Union[RenameOperation, FilterOperation],
    Field(discriminator="op"),
]


# --- Configuracoes de Transformacao em DuckDB ---

class MapperFieldConfig(BaseModel):
    """Mapeia um campo de origem para um destino, com transformacao opcional."""

    model_config = ConfigDict(extra="allow")

    source: str | None = None
    target: str
    expression: str | None = None  # expressao SQL computada (ex: UPPER("col"))
    type: str | None = None        # tipo de saida para TRY_CAST (string, integer, ...)


class MapperNodeConfig(BaseModel):
    """Configuracao do no de mapper."""

    type: Literal["mapper"]
    mappings: list[MapperFieldConfig]
    drop_unmapped: bool = False
    output_field: str = "data"


class FilterConditionConfig(BaseModel):
    """Representa uma condicao individual de filtro."""

    field: str | None = None
    expression: str | None = None
    operator: Literal[
        "eq",
        "ne",
        "gt",
        "lt",
        "gte",
        "lte",
        "contains",
        "in",
        "not_in",
        "is_null",
        "is_not_null",
    ]
    value: Any | None = None


class FilterNodeConfig(BaseModel):
    """Configuracao do no de filtro."""

    type: Literal["filter"]
    conditions: list[FilterConditionConfig]
    logic: Literal["and", "or"] = "and"
    output_field: str = "data"


class AggregationItemConfig(BaseModel):
    """Define uma agregacao sobre uma coluna."""

    column: str | None = None
    operation: Literal["sum", "avg", "count", "max", "min"]
    alias: str


class AggregatorNodeConfig(BaseModel):
    """Configuracao do no de agregacao."""

    type: Literal["aggregator"]
    group_by: list[str] = Field(default_factory=list)
    aggregations: list[AggregationItemConfig]
    output_field: str = "data"


class MathExpressionConfig(BaseModel):
    """Cria ou atualiza coluna com base em uma expressao matematica."""

    target_column: str
    expression: str


class MathNodeConfig(BaseModel):
    """Configuracao do no matematico."""

    type: Literal["math"]
    expressions: list[MathExpressionConfig]
    output_field: str = "data"


class CodeNodeConfig(BaseModel):
    """Configuracao do no de codigo customizado."""

    type: Literal["code"]
    code: str
    result_variable: str = "result"
    output_field: str = "data"


# --- Configuracoes por Tipo de No ---

class ExtractNodeConfig(BaseModel):
    """Configuracao do no legado de extracao SQL."""

    type: Literal["extractNode"]
    connection_id: UUID = Field(..., description="ID do conector cadastrado na plataforma")
    query: str | None = None
    table_name: str | None = None
    chunk_size: int = 1000
    max_rows: int | None = None
    output_field: str = "data"


class SqlDatabaseNodeConfig(BaseModel):
    """Configuracao explicita para extracao SQL com streaming."""

    type: Literal["sql_database"]
    connection_id: UUID = Field(..., description="ID do conector cadastrado na plataforma")
    query: str | None = None
    table_name: str | None = None
    chunk_size: int = 1000
    max_rows: int | None = None
    output_field: str = "data"


class HttpRequestNodeConfig(BaseModel):
    """Configuracao do no de requisicao HTTP."""

    type: Literal["http_request"]
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] = "GET"
    url: str
    headers: dict[str, Any] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    body: Any | None = None
    timeout_seconds: float = 30.0
    fail_on_error: bool = True
    output_field: str = "data"


class TransformNodeConfig(BaseModel):
    """Configuracao do no legado de transformacao de dados."""

    type: Literal["transformNode"]
    operations: list[TransformOperation]


class LoadNodeConfig(BaseModel):
    """Configuracao do no de carga de dados."""

    type: Literal["loadNode"]
    connection_id: UUID = Field(..., description="ID do conector de destino")
    target_table: str
    write_disposition: Literal["append", "replace", "merge"] = "append"


class AINodeConfig(BaseModel):
    """Configuracao do no de inteligencia artificial / LLM."""

    type: Literal["aiNode"]
    prompt_template: str
    model_name: str = "gpt-4"
    temperature: float = 0.7


class ManualTriggerNodeConfig(BaseModel):
    """Configuracao do no de trigger manual."""

    type: Literal["manual"]


class WebhookAuthConfig(BaseModel):
    """Configuracao de autenticacao para o webhook de entrada.

    TODO: mover secrets para connections_encrypted quando o loader
    suportar referencias indiretas. Por enquanto os valores ficam em
    claro no definition do workflow.
    """

    type: Literal["none", "header", "basic", "jwt"] = "none"
    # header auth
    header_name: str | None = None
    header_value: str | None = None
    # basic auth
    username: str | None = None
    password: str | None = None
    # jwt
    jwt_secret: str | None = None
    jwt_algorithm: Literal["HS256", "HS384", "HS512", "RS256"] = "HS256"


class WebhookTriggerNodeConfig(BaseModel):
    """Configuracao do no de trigger webhook (estilo n8n)."""

    type: Literal["webhook"]

    http_method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"] = "POST"
    path: str | None = Field(
        default=None,
        description=(
            "Path opcional para expor a URL customizada. Se omitido, a URL "
            "publica usa o workflow_id. Pode conter letras, numeros, hifen "
            "e barras."
        ),
        pattern=r"^[a-zA-Z0-9/_\-]+$",
        max_length=255,
    )

    authentication: WebhookAuthConfig = Field(default_factory=WebhookAuthConfig)

    respond_mode: Literal[
        "immediately",
        "on_finish",
        "using_respond_node",
    ] = "immediately"
    response_code: int = Field(default=200, ge=100, le=599)
    response_data: Literal[
        "first_entry_json",
        "all_entries",
        "no_body",
    ] = "first_entry_json"
    response_headers: dict[str, str] = Field(default_factory=dict)

    raw_body: bool = Field(
        default=False,
        description="Quando True, nao tenta parse JSON - guarda bytes em base64.",
    )
    binary_property: str | None = Field(
        default=None,
        description="Se informado, encaminha o body como arquivo binario nesta chave.",
    )

    allowed_origins: str | None = Field(
        default=None,
        description="CSV de origens permitidas (ou '*'); None desabilita CORS.",
    )

    output_field: str = "data"


class CronTriggerNodeConfig(BaseModel):
    """Configuracao do no de trigger por cron."""

    type: Literal["cron"]
    cron_expression: str
    timezone: str = "UTC"


class PollingTriggerNodeConfig(BaseModel):
    """Configuracao do no de polling."""

    type: Literal["polling"]
    connection_id: UUID = Field(..., description="ID do conector a ser monitorado")
    query: str


class TriggerNodeConfig(BaseModel):
    """Configuracao do no de trigger legado."""

    type: Literal["triggerNode"]
    trigger_type: Literal["schedule", "cron", "webhook", "manual", "polling"]
    cron_expression: str | None = None


# ---------------------------------------------------------------------------
# Configuracoes dos novos nos de entrada alternativos
# ---------------------------------------------------------------------------

class CsvInputNodeConfig(BaseModel):
    """Configuracao do no de leitura de arquivo CSV local ou remoto."""

    type: Literal["csv_input"]
    url: str = Field(..., description="Caminho local ou URL HTTP/S3 do arquivo CSV")
    delimiter: str = Field(default=",", min_length=1, max_length=1)
    has_header: bool = True
    encoding: str = "utf-8"
    null_padding: bool = True
    output_field: str = "data"


class ExcelInputNodeConfig(BaseModel):
    """Configuracao do no de leitura de planilha Excel (.xlsx)."""

    type: Literal["excel_input"]
    url: str = Field(..., description="Caminho local ou URL HTTP/HTTPS do arquivo Excel")
    sheet_name: str | int | None = Field(
        default=None,
        description="Nome ou indice (0-based) da aba; None = primeira aba",
    )
    header_row: int = Field(default=0, ge=0, description="Indice (0-based) da linha de cabecalho")
    skip_empty: bool = True
    output_field: str = "data"


class ApiAuthConfig(BaseModel):
    """Configuracao de autenticacao para o no de API."""

    type: Literal["bearer", "basic", "api_key"]
    # bearer
    token: str | None = None
    # basic
    username: str | None = None
    password: str | None = None
    # api_key
    header: str | None = Field(default=None, description="Nome do header (ex: X-API-Key)")
    value: str | None = None


class ApiInputNodeConfig(BaseModel):
    """Configuracao do no de extracao de API REST paginada."""

    type: Literal["api_input"]
    url: str = Field(..., description="URL base da API")
    method: Literal["GET", "POST", "PUT", "PATCH"] = "GET"
    headers: dict[str, Any] = Field(default_factory=dict)
    body: Any | None = None
    data_path: str = Field(
        default="$",
        description="JSONPath para o array de registros na resposta (ex: $.data.items)",
    )
    auth: ApiAuthConfig | None = None
    pagination_type: Literal["none", "offset", "page_number", "cursor", "next_url"] = "none"
    pagination_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Parametros especificos da estrategia de paginacao",
    )
    max_records: int | None = Field(default=None, description="Limite total de registros")
    max_pages: int = Field(default=10_000, description="Limite de paginas como salvaguarda")
    timeout_seconds: float = 30.0
    output_field: str = "data"


class InlineDataNodeConfig(BaseModel):
    """Configuracao do no de dados estaticos embutidos no workflow."""

    type: Literal["inline_data"]
    data: list[dict[str, Any]] | dict[str, Any] | str = Field(
        ...,
        description="Lista de dicts, dict unico, ou string JSON valida",
    )
    output_field: str = "data"


NodeConfig = Annotated[
    Union[
        ExtractNodeConfig,
        SqlDatabaseNodeConfig,
        HttpRequestNodeConfig,
        MapperNodeConfig,
        FilterNodeConfig,
        AggregatorNodeConfig,
        MathNodeConfig,
        CodeNodeConfig,
        TransformNodeConfig,
        LoadNodeConfig,
        AINodeConfig,
        ManualTriggerNodeConfig,
        WebhookTriggerNodeConfig,
        CronTriggerNodeConfig,
        PollingTriggerNodeConfig,
        TriggerNodeConfig,
        CsvInputNodeConfig,
        ExcelInputNodeConfig,
        ApiInputNodeConfig,
        InlineDataNodeConfig,
    ],
    Field(discriminator="type"),
]


# --- Estrutura do Workflow (React Flow) ---

class WorkflowNode(BaseModel):
    """Representa um no no canvas do React Flow."""

    id: str
    type: str
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})
    data: NodeConfig


class WorkflowEdge(BaseModel):
    """Representa uma conexao (aresta) entre dois nos."""

    id: str
    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None


class WorkflowPayload(BaseModel):
    """Payload completo do React Flow: nos + arestas."""

    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]


# --- Respostas de Execucao ---

class ExecutionResponse(BaseModel):
    """Resposta imediata ao submeter um workflow para execucao."""

    execution_id: UUID
    status: str


class NodeExecutionResponse(BaseModel):
    """Resultado de execucao de um no individual."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    execution_id: UUID
    node_id: str
    node_type: str
    label: str | None = None
    status: str
    duration_ms: int = 0
    row_count_in: int | None = None
    row_count_out: int | None = None
    output_summary: dict[str, Any] | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ExecutionStatusResponse(BaseModel):
    """Status detalhado de uma execucao de workflow."""

    model_config = ConfigDict(from_attributes=True)

    execution_id: UUID
    status: str
    triggered_by: str = "manual"
    result: dict[str, Any] | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ExecutionDetailResponse(BaseModel):
    """Status da execucao + historico de cada no."""

    model_config = ConfigDict(from_attributes=True)

    execution_id: UUID
    status: str
    triggered_by: str = "manual"
    result: dict[str, Any] | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    nodes: list[NodeExecutionResponse] = []


class ExecutionSummaryResponse(BaseModel):
    """Linha enxuta usada nas listagens da aba Executions."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_id: UUID
    status: str
    triggered_by: str
    duration_ms: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    node_count: int = 0
    error_message: str | None = None


class ExecutionListResponse(BaseModel):
    """Resposta paginada de execucoes de um workflow."""

    items: list[ExecutionSummaryResponse]
    total: int
    page: int
    size: int


# --- Schemas de CRUD de Workflow ---

class WorkflowCreate(BaseModel):
    """Payload para criacao de um workflow ou template."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    project_id: UUID | None = None
    workspace_id: UUID | None = None
    is_template: bool = False
    definition: dict[str, Any] = Field(default_factory=dict)


class WorkflowUpdate(BaseModel):
    """Payload para atualizacao parcial de um workflow."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    definition: dict[str, Any] | None = None
    is_template: bool | None = None
    is_published: bool | None = None
    status: str | None = Field(
        default=None,
        description="Status do workflow: 'draft' ou 'published'.",
    )


class WorkflowResponse(BaseModel):
    """Representacao completa de um workflow retornado pela API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None = None
    project_id: UUID | None = None
    workspace_id: UUID | None = None
    is_template: bool
    is_published: bool
    status: str = "draft"
    definition: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class WorkflowCloneRequest(BaseModel):
    """Payload para clonar um template em um projeto destino."""

    target_project_id: UUID
    connection_mapping: dict[str, UUID] = Field(
        default_factory=dict,
        description="Mapeamento de connection_id originais para novos: {'uuid_velho': 'uuid_novo'}",
    )


# --- Schemas de suporte para o no Webhook (UI) ---

class WebhookUrlsResponse(BaseModel):
    """URLs de test e producao resolvidas para o no webhook do workflow."""

    node_id: str | None
    http_method: str
    path: str
    test_url: str
    production_url: str
    production_ready: bool


class WebhookCaptureResponse(BaseModel):
    """Payload capturado pela URL de teste do webhook (listen inbox)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    method: str
    headers: dict[str, str]
    query_params: dict[str, Any]
    body: Any | None = None
    captured_at: datetime
