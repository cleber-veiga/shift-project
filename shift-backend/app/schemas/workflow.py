"""
Schemas Pydantic para workflows do React Flow.
Usa discriminated unions para validar configuracoes por tipo de no.
"""

import re
from datetime import datetime
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Tipo de referencia que aceita UUID real OU template {{vars.NOME}}
# ---------------------------------------------------------------------------

_VARS_TEMPLATE_RE = re.compile(r"^\{\{\s*vars\.[A-Za-z_][A-Za-z0-9_]*\s*\}\}$")


def _coerce_connection_ref(v: Any) -> Any:
    """Normaliza connection_id: converte string UUID -> UUID; valida templates."""
    if isinstance(v, UUID):
        return v
    if isinstance(v, str):
        try:
            return UUID(v)
        except ValueError:
            if _VARS_TEMPLATE_RE.match(v):
                return v
            raise ValueError(
                f"connection_id deve ser um UUID valido ou '{{{{vars.NOME}}}}', recebido: '{v}'"
            )
    raise ValueError(f"connection_id: tipo invalido {type(v).__name__!r}")


ConnectionRef = Annotated[Union[UUID, str], BeforeValidator(_coerce_connection_ref)]
"""UUID de conector ou template {{vars.NOME}} resolvido em tempo de execucao."""


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


# --- Retry policy (Fase 5a) ---


class RetryPolicyConfig(BaseModel):
    """Declara como um no deve ser reexecutado apos falhar.

    ``retry_on`` filtra por substring na mensagem do erro — vazio = retry
    em qualquer ``NodeProcessingError``. ``backoff_strategy='exponential'``
    multiplica ``backoff_seconds`` por 2**(tentativa-1) entre attempts.
    """

    max_attempts: int = Field(default=1, ge=1, le=10)
    backoff_strategy: Literal["none", "fixed", "exponential"] = "none"
    backoff_seconds: float = Field(default=1.0, ge=0.1, le=300.0)
    retry_on: list[str] = Field(default_factory=list)


class _RetryableNodeConfig(BaseModel):
    """Mixin base para configs de nos que suportam retry_policy.

    Nos de trigger NAO herdam desse mixin — disparadores nao devem ser
    reexecutados pelo runtime.
    """

    retry_policy: RetryPolicyConfig | None = None


# --- Configuracoes de Transformacao em DuckDB ---

class MapperFieldConfig(BaseModel):
    """Mapeia um campo de origem para um destino, com transformacao opcional."""

    model_config = ConfigDict(extra="allow")

    source: str | None = None
    target: str
    expression: str | None = None  # expressao SQL computada (ex: UPPER("col"))
    type: str | None = None        # tipo de saida para TRY_CAST (string, integer, ...)


class MapperNodeConfig(_RetryableNodeConfig):
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


class FilterNodeConfig(_RetryableNodeConfig):
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


class AggregatorNodeConfig(_RetryableNodeConfig):
    """Configuracao do no de agregacao."""

    type: Literal["aggregator"]
    group_by: list[str] = Field(default_factory=list)
    aggregations: list[AggregationItemConfig]
    output_field: str = "data"


class MathExpressionConfig(BaseModel):
    """Cria ou atualiza coluna com base em uma expressao matematica."""

    target_column: str
    expression: str


class MathNodeConfig(_RetryableNodeConfig):
    """Configuracao do no matematico."""

    type: Literal["math"]
    expressions: list[MathExpressionConfig]
    output_field: str = "data"


class CodeNodeConfig(_RetryableNodeConfig):
    """Configuracao do no de codigo customizado."""

    type: Literal["code"]
    code: str
    result_variable: str = "result"
    output_field: str = "data"


# --- Configuracoes por Tipo de No ---

class ExtractNodeConfig(_RetryableNodeConfig):
    """Configuracao do no legado de extracao SQL."""

    type: Literal["extractNode"]
    connection_id: ConnectionRef = Field(..., description="ID do conector cadastrado na plataforma")
    query: str | None = None
    table_name: str | None = None
    chunk_size: int = 1000
    max_rows: int | None = None
    output_field: str = "data"


class SqlDatabaseNodeConfig(_RetryableNodeConfig):
    """Configuracao explicita para extracao SQL com streaming.

    ``partition_on`` + ``partition_num`` habilitam leitura paralela em
    ranges disjuntos de uma coluna numerica ou temporal — exigido para
    tabelas Oracle/Postgres com 10M+ linhas. A coluna deve ser NOT NULL.
    """

    type: Literal["sql_database"]
    connection_id: ConnectionRef = Field(..., description="ID do conector cadastrado na plataforma")
    query: str | None = None
    table_name: str | None = None
    chunk_size: int = Field(
        default=50_000,
        ge=1,
        le=1_000_000,
        description="Linhas por fetchmany — controla o RAM por chunk.",
    )
    max_rows: int | None = None
    output_field: str = "data"
    partition_on: str | None = Field(
        default=None,
        description=(
            "Coluna NOT NULL (numerica ou temporal) para particionamento "
            "em ranges. Quando informado junto com ``partition_num > 1``, "
            "abre N cursores paralelos. Sem isso, leitura single-connection."
        ),
    )
    partition_num: int = Field(
        default=1,
        ge=1,
        le=64,
        description=(
            "Numero de particoes/conexoes paralelas. Capado em pool_size + "
            "max_overflow do engine (ver engine_cache)."
        ),
    )
    streaming: bool = Field(
        default=True,
        description=(
            "Quando True, usa cursor server-side (stream_results=True) e "
            "fetchmany. Desabilite apenas para drivers nao-streamaveis."
        ),
    )


class HttpRequestNodeConfig(_RetryableNodeConfig):
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


class TransformNodeConfig(_RetryableNodeConfig):
    """Configuracao do no legado de transformacao de dados."""

    type: Literal["transformNode"]
    operations: list[TransformOperation]


class LoadNodeConfig(_RetryableNodeConfig):
    """Configuracao do no de carga de dados."""

    type: Literal["loadNode"]
    connection_id: ConnectionRef = Field(..., description="ID do conector de destino")
    target_table: str
    write_disposition: Literal["append", "replace", "merge"] = "append"


class AINodeConfig(_RetryableNodeConfig):
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
    connection_id: ConnectionRef = Field(..., description="ID do conector a ser monitorado")
    query: str


class TriggerNodeConfig(BaseModel):
    """Configuracao do no de trigger legado."""

    type: Literal["triggerNode"]
    trigger_type: Literal["schedule", "cron", "webhook", "manual", "polling"]
    cron_expression: str | None = None


# ---------------------------------------------------------------------------
# Configuracoes dos novos nos de entrada alternativos
# ---------------------------------------------------------------------------

class CsvInputNodeConfig(_RetryableNodeConfig):
    """Configuracao do no de leitura de arquivo CSV local ou remoto."""

    type: Literal["csv_input"]
    url: str = Field(..., description="Caminho local ou URL HTTP/S3 do arquivo CSV")
    delimiter: str = Field(default=",", min_length=1, max_length=1)
    has_header: bool = True
    encoding: str = "utf-8"
    null_padding: bool = True
    output_field: str = "data"


class ExcelInputNodeConfig(_RetryableNodeConfig):
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


class ApiInputNodeConfig(_RetryableNodeConfig):
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


class InlineDataNodeConfig(_RetryableNodeConfig):
    """Configuracao do no de dados estaticos embutidos no workflow."""

    type: Literal["inline_data"]
    data: list[dict[str, Any]] | dict[str, Any] | str = Field(
        ...,
        description="Lista de dicts, dict unico, ou string JSON valida",
    )
    output_field: str = "data"


# ---------------------------------------------------------------------------
# Configuracoes de no composto personalizavel (custom composite node)
# ---------------------------------------------------------------------------
#
# Um no personalizado encapsula escrita transacional em multiplas tabelas
# relacionadas (ex: NOTA + NOTAITEM + NOTAICMS). O processador e unico
# (``composite_insert``), parametrizado pelo blueprint carregado do
# ``node.data``.
#
# Cardinalidade suportada no Phase 1: ``one`` (1 linha upstream -> 1 linha
# em cada tabela alvo, com FKs propagadas via RETURNING). ``many`` (1 header
# + N itens) fica para Phase 2.

class CompositeFkMapItem(BaseModel):
    """Liga uma coluna do filho ao valor RETURNING de um alias pai."""

    child_column: str = Field(..., description="Coluna FK na tabela filha")
    parent_returning: str = Field(
        ..., description="Nome da coluna RETURNING capturada no pai"
    )


class CompositeTableStep(BaseModel):
    """Uma tabela dentro do blueprint, executada na ordem declarada."""

    alias: str = Field(..., description="Identificador logico (ex: 'nota', 'item')")
    table: str = Field(..., description="Nome da tabela no banco destino")
    role: Literal["header", "child"] = "header"
    parent_alias: str | None = Field(
        default=None,
        description="Alias do pai quando role='child'. Deve aparecer antes no array.",
    )
    fk_map: list[CompositeFkMapItem] = Field(
        default_factory=list,
        description="Mapeamento de colunas FK -> valores RETURNING do pai",
    )
    cardinality: Literal["one"] = Field(
        default="one",
        description="Phase 1 so suporta 'one' (1 linha filha por pai).",
    )
    columns: list[str] = Field(
        ..., description="Colunas da tabela alvo expostas no field_mapping"
    )
    returning: list[str] = Field(
        default_factory=list,
        description="Colunas capturadas do INSERT para uso por filhos (PK, etc.)",
    )
    conflict_mode: Literal["insert", "upsert", "insert_or_ignore"] = Field(
        default="insert",
        description=(
            "Estrategia de conflito: 'insert' (padrao, falha em duplicata), "
            "'upsert' (atualiza em conflito) ou 'insert_or_ignore' (silencia)."
        ),
    )
    conflict_keys: list[str] = Field(
        default_factory=list,
        description=(
            "Colunas que formam o indice unico usado por ON CONFLICT/MERGE. "
            "Obrigatorio quando conflict_mode != 'insert'."
        ),
    )
    update_columns: list[str] | None = Field(
        default=None,
        description=(
            "Colunas atualizadas em UPDATE (modo 'upsert'). None = atualiza "
            "todas as columns excluindo conflict_keys. Ignorado em modos "
            "diferentes de 'upsert'."
        ),
    )

    @model_validator(mode="after")
    def _validate_conflict(self) -> "CompositeTableStep":
        if self.conflict_mode != "insert" and not self.conflict_keys:
            raise ValueError(
                f"alias='{self.alias}' conflict_mode='{self.conflict_mode}' "
                "exige conflict_keys nao-vazio."
            )
        allowed_keys = set(self.columns) | {fk.child_column for fk in self.fk_map}
        for key in self.conflict_keys:
            if key not in allowed_keys:
                raise ValueError(
                    f"alias='{self.alias}' conflict_keys contem '{key}' "
                    "que nao esta em columns nem em fk_map.child_column."
                )
        if self.update_columns is not None:
            for col in self.update_columns:
                if col not in self.columns:
                    raise ValueError(
                        f"alias='{self.alias}' update_columns contem '{col}' "
                        "que nao esta em columns."
                    )
        return self


class CompositeBlueprint(BaseModel):
    """Contrato estruturado da composicao (N tabelas em cascata)."""

    tables: list[CompositeTableStep] = Field(
        ..., min_length=1, description="Tabelas na ordem de insercao"
    )


class SqlScriptOutputColumn(BaseModel):
    """Coluna declarada no output_schema do no sql_script."""

    name: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)


class SqlScriptNodeConfig(_RetryableNodeConfig):
    """Configuracao do no de execucao de SQL arbitrario."""

    type: Literal["sql_script"]
    connection_id: ConnectionRef = Field(..., description="ID do conector SQL alvo")
    script: str = Field(..., min_length=1)
    parameters: dict[str, str] = Field(default_factory=dict)
    mode: Literal["query", "execute", "execute_many"] = "query"
    output_schema: list[SqlScriptOutputColumn] = Field(default_factory=list)
    output_field: str = "sql_result"
    timeout_seconds: int = Field(default=60, ge=1, le=600)


class CompositeInsertNodeConfig(_RetryableNodeConfig):
    """Configuracao do no de insercao composta (multi-tabela, transacional)."""

    type: Literal["composite_insert"]
    connection_id: ConnectionRef = Field(..., description="ID do conector SQL de destino")
    definition_id: UUID | None = Field(
        default=None,
        description="Referencia a CustomNodeDefinition de origem (auditoria)",
    )
    definition_version: int | None = Field(
        default=None, description="Versao do blueprint snapshot no momento do save"
    )
    blueprint: CompositeBlueprint = Field(
        ..., description="Snapshot do blueprint — fonte de verdade em tempo de execucao"
    )
    field_mapping: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Mapa 'alias.coluna' -> 'coluna_upstream'. Ex: "
            "{'nota.numero': 'NUMERO_NOTA', 'item.produto': 'PRODUTO'}."
        ),
    )
    batch_size: int = Field(default=100, ge=1)
    output_field: str = "composite_result"


class TruncateTableNodeConfig(_RetryableNodeConfig):
    """Configuracao do no de truncate/delete em tabela de destino SQL."""

    type: Literal["truncate_table"]
    connection_id: ConnectionRef = Field(..., description="ID do conector SQL alvo")
    target_table: str = Field(..., min_length=1)
    mode: Literal["truncate", "delete"] = "truncate"
    where_clause: str | None = None
    output_field: str = "data"


class BulkInsertNodeConfig(_RetryableNodeConfig):
    """Configuracao do no de bulk insert com mapeamento de colunas."""

    type: Literal["bulk_insert"]
    connection_id: ConnectionRef = Field(..., description="ID do conector SQL de destino")
    target_table: str = Field(..., min_length=1)
    column_mapping: list[dict[str, str]] = Field(default_factory=list)
    unique_columns: list[str] = Field(default_factory=list)
    batch_size: int = Field(default=1000, ge=1)
    output_field: str = "load_result"


class DeadLetterNodeConfig(_RetryableNodeConfig):
    """Configuracao do no terminal que persiste payloads em dead-letter."""

    type: Literal["dead_letter"]
    output_field: str = "dead_letter_result"


# ---------------------------------------------------------------------------
# Sub-workflows (Fase 3)
# ---------------------------------------------------------------------------
#
# Um workflow publicado (``WorkflowVersion``) pode declarar ``io_schema`` com
# listas de ``WorkflowParam``. Um no ``call_workflow`` em outro workflow
# invoca a versao publicada, mapeando campos do contexto para os inputs e
# publicando os outputs num campo do contexto downstream.

_WORKFLOW_PARAM_TYPES = (
    "string", "integer", "number", "boolean", "object", "array", "table_reference",
    "connection", "file_upload", "secret",
)


class WorkflowParam(BaseModel):
    """Declaracao de um parametro no io_schema ou nas variaveis globais de um workflow."""

    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    type: Literal[
        "string", "integer", "number", "boolean", "object", "array", "table_reference",
        "connection", "file_upload", "secret",
    ]
    required: bool = True
    default: Any | None = None
    description: str | None = Field(default=None, max_length=500)
    # Campos exclusivos de variaveis globais (ignorados em io_schema de sub-workflows)
    connection_type: Literal["postgres", "mysql", "sqlserver", "oracle", "mongodb"] | None = None
    accepted_extensions: list[str] | None = None
    ui_group: str | None = None
    ui_order: int = 0

    @model_validator(mode="after")
    def _validate_type_specific_fields(self) -> "WorkflowParam":
        if self.type != "connection" and self.connection_type is not None:
            raise ValueError("connection_type so e permitido quando type='connection'.")
        if self.type != "file_upload" and self.accepted_extensions is not None:
            raise ValueError("accepted_extensions so e permitido quando type='file_upload'.")
        return self


class WorkflowVariablesSchema(BaseModel):
    """Lista de variaveis globais declaradas pelo criador do workflow."""

    variables: list[WorkflowParam] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_unique_names(self) -> "WorkflowVariablesSchema":
        seen: set[str] = set()
        for p in self.variables:
            if p.name in seen:
                raise ValueError(f"variavel '{p.name}' duplicada nas variaveis do workflow.")
            seen.add(p.name)
        return self


class WorkflowIOSchema(BaseModel):
    """Contrato de inputs/outputs de um workflow publicado."""

    inputs: list[WorkflowParam] = Field(default_factory=list)
    outputs: list[WorkflowParam] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_unique_names(self) -> "WorkflowIOSchema":
        seen_in: set[str] = set()
        for p in self.inputs:
            if p.name in seen_in:
                raise ValueError(f"input '{p.name}' duplicado no io_schema.")
            seen_in.add(p.name)
        seen_out: set[str] = set()
        for p in self.outputs:
            if p.name in seen_out:
                raise ValueError(f"output '{p.name}' duplicado no io_schema.")
            seen_out.add(p.name)
        return self


class WorkflowInputNodeConfig(_RetryableNodeConfig):
    """No marcador: expoe ``input_data`` como ponto de entrada de um sub-workflow.

    Nao recebe upstream. Durante a execucao, lê ``context['input_data']``
    e publica no ``output_field`` para uso por nos a jusante.
    """

    type: Literal["workflow_input"]
    output_field: str = "data"


class WorkflowOutputNodeConfig(_RetryableNodeConfig):
    """No marcador: captura valores para o pacote de saida do sub-workflow.

    Os campos em ``mapping`` sao avaliados sobre o contexto (igual aos
    templates de outros nos). O resultado e mergeado em
    ``context['workflow_output']`` — o call_workflow pai consome isso e
    valida contra o ``output_schema`` da versao.
    """

    type: Literal["workflow_output"]
    mapping: dict[str, str] = Field(
        default_factory=dict,
        description="Mapa nome_output -> path/template do contexto.",
    )


class LoopNodeConfig(_RetryableNodeConfig):
    """Itera sobre linhas de um dataset upstream invocando um sub-workflow.

    O sub-workflow (Fase 3) e invocado uma vez por item. ``source_field``
    e um dotted path do contexto que resolve para uma DuckDbReference
    ou para uma lista inline. ``item_param_name`` e o input obrigatorio
    que recebe o item atual; ``index_param_name`` e opcional e recebe
    o indice (0-based) da iteracao.
    """

    type: Literal["loop"]
    source_field: str = Field(..., min_length=1, description="Dotted path no contexto do loop.")
    workflow_id: UUID = Field(..., description="Workflow a invocar por item.")
    workflow_version: int | Literal["latest"] = "latest"
    item_param_name: str = Field(..., min_length=1, max_length=100)
    index_param_name: str | None = Field(default=None, max_length=100)
    extra_inputs: dict[str, str] = Field(default_factory=dict)
    mode: Literal["sequential", "parallel"] = "sequential"
    max_parallelism: int = Field(default=4, ge=1, le=32)
    on_item_error: Literal["fail_fast", "continue", "collect"] = "fail_fast"
    max_iterations: int = Field(default=10_000, ge=1, le=1_000_000)
    output_field: str = "loop_result"


class CallWorkflowNodeConfig(_RetryableNodeConfig):
    """Invoca uma versao publicada de outro workflow como sub-rotina."""

    type: Literal["call_workflow"]
    workflow_id: UUID = Field(..., description="ID do workflow a invocar.")
    version: int | Literal["latest"] = Field(
        default="latest",
        description="Numero da WorkflowVersion publicada ou 'latest'.",
    )
    input_mapping: dict[str, str] = Field(
        default_factory=dict,
        description="Mapa input_name -> path/template no contexto do pai.",
    )
    output_field: str = Field(
        default="workflow_result",
        description="Campo publicado no contexto com os outputs do sub.",
    )
    timeout_seconds: int = Field(default=300, ge=1, le=3600)


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
        SqlScriptNodeConfig,
        CompositeInsertNodeConfig,
        TruncateTableNodeConfig,
        BulkInsertNodeConfig,
        DeadLetterNodeConfig,
        WorkflowInputNodeConfig,
        WorkflowOutputNodeConfig,
        CallWorkflowNodeConfig,
        LoopNodeConfig,
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


# --- Payload de Execucao ---

class ExecuteWorkflowRequest(BaseModel):
    """Payload para submeter um workflow para execucao via POST /execute."""

    variable_values: dict[str, Any] = Field(default_factory=dict)
    retry_from_execution_id: UUID | None = Field(
        default=None,
        description=(
            "ID de uma execucao anterior falhada. Quando informado, o runner carrega "
            "checkpoints dessa execucao e pula nos ja concluidos com sucesso."
        ),
    )
    run_mode: Literal["full", "preview", "validate"] = Field(
        default="full",
        description=(
            "Modo de execucao. 'full' = execucao completa (padrao); "
            "'preview' = aplica LIMIT 100 em nos de extracao para dry-run rapido; "
            "'validate' = apenas testa conexoes e valida variaveis, sem mover dados."
        ),
    )


class ValidateConnectionResult(BaseModel):
    """Resultado da validacao de uma conexao durante run_mode=validate."""

    connection_id: UUID
    name: str
    ok: bool
    error: str | None = None


class ValidateExecutionResponse(BaseModel):
    """Resposta sincrona do endpoint /execute quando run_mode=validate.

    Nao cria WorkflowExecution — apenas reporta o resultado da validacao.
    """

    ok: bool
    connections: list[ValidateConnectionResult] = Field(default_factory=list)
    missing_variables: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# --- Schema de Variaveis (endpoint /variables/schema) ---

class ConnectionOptionResponse(BaseModel):
    """Conector disponivel como opcao para uma variavel do tipo 'connection'."""

    id: UUID
    name: str
    type: str


class InheritedVariable(BaseModel):
    """Variavel herdada de um sub-workflow referenciado por um no call_workflow.

    O frontend usa estas entradas para:
    1) exibir a lista como categoria "read-only" no painel de variaveis,
       transmitindo ao usuario que estes campos sao requeridos pelo sub-fluxo;
    2) incluir no formulario de execucao para capturar valores que serao
       auto-encaminhados pelo backend quando os nomes baterem.
    """

    variable: WorkflowParam
    sub_workflow_id: UUID
    sub_workflow_name: str
    sub_workflow_version: int


class VariablesSchemaResponse(BaseModel):
    """Declaracoes de variaveis + opcoes de conexao por variavel do tipo 'connection'."""

    variables: list[WorkflowParam]
    connection_options: dict[str, list[ConnectionOptionResponse]] = Field(
        default_factory=dict,
        description="Chaves = nomes de variaveis com type='connection'; valores = lista de conectores compativeis.",
    )
    inherited_variables: list[InheritedVariable] = Field(
        default_factory=list,
        description="Variaveis declaradas por sub-workflows referenciados, com metadados da origem.",
    )


# --- Checkpoints ---

class CheckpointSummary(BaseModel):
    """Resumo de um checkpoint de no."""

    node_id: str
    created_at: datetime
    expires_at: datetime
    used_by_execution_id: UUID | None = None


class CheckpointsResponse(BaseModel):
    """Lista de checkpoints disponiveis para retomada de execucao."""

    source_execution_id: UUID
    checkpoints: list[CheckpointSummary]
    resumable: bool = Field(
        description="True quando ha ao menos um checkpoint valido (nao expirado, arquivo DuckDB presente)."
    )


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
    input_data: dict[str, Any] | None = None
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
    template_version: str | None = None


class ExecutionListResponse(BaseModel):
    """Resposta paginada de execucoes de um workflow."""

    items: list[ExecutionSummaryResponse]
    total: int
    page: int
    size: int


class ExecutionDefinitionResponse(BaseModel):
    """Resposta do endpoint GET /executions/{id}/definition (Sprint 4.1).

    Compatibilidade com clientes que ainda consultam o caminho legado.
    Sob o capo le os mesmos campos novos de ExecutionSnapshotResponse.
    """

    execution_id: UUID
    workflow_id: UUID
    snapshot: dict[str, Any] | None
    snapshot_hash: str | None
    current_hash: str | None
    definition_diverged: bool = False


class ExecutionSnapshotResponse(BaseModel):
    """Snapshot imutavel da definicao renderizada usada por uma execucao.

    Garantia: ``snapshot`` jamais contem valores de variaveis ``secret`` em
    texto claro — sao substituidos por ``<REDACTED>`` antes da persistencia.
    """

    execution_id: UUID
    workflow_id: UUID
    template_snapshot: dict[str, Any]
    template_version: str | None
    rendered_at: datetime
    current_template_version: str | None = Field(
        default=None,
        description="SHA-256 atual da definicao do workflow para comparacao.",
    )
    diverged: bool = Field(
        default=False,
        description="True se template_version != current_template_version.",
    )


class ReplayExecutionRequest(BaseModel):
    """Body opcional do POST /executions/{id}/replay.

    ``trigger_type`` permite que o frontend distinga uma replay manual
    (botao "rodar novamente") de uma replay agendada por outro processo
    (sistema de retry, scheduler).
    """

    trigger_type: Literal["manual", "on_demand"] = "on_demand"


class ReplayExecutionResponse(BaseModel):
    """Resposta do endpoint POST /executions/{id}/replay."""

    execution_id: UUID
    original_execution_id: UUID
    status: str
    template_version: str | None


class ExecutionLogEntry(BaseModel):
    """Linha de log estruturado de uma execucao."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    timestamp: datetime
    level: str
    message: str
    node_id: str | None = None
    context: dict[str, Any] | None = None


class ExecutionLogsResponse(BaseModel):
    """Resposta do endpoint GET /executions/{id}/logs."""

    execution_id: UUID
    entries: list[ExecutionLogEntry]
    total: int
    truncated: bool = False


# --- Schemas de CRUD de Workflow ---


def _normalize_tags(value: Any) -> list[str]:
    """Normaliza lista de tags: strip + UPPER + remove vazias + dedup preservando ordem."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("tags deve ser uma lista de strings")
    seen: set[str] = set()
    out: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            raise ValueError("cada tag deve ser string")
        tag = raw.strip().upper()
        if not tag:
            continue
        if len(tag) > 50:
            raise ValueError(f"tag '{tag[:20]}...' excede 50 caracteres")
        if tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


class WorkflowCreate(BaseModel):
    """Payload para criacao de um workflow ou template."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    project_id: UUID | None = None
    workspace_id: UUID | None = None
    is_template: bool = False
    definition: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags", mode="before")
    @classmethod
    def _normalize_tags(cls, v: Any) -> list[str]:
        return _normalize_tags(v)

    @model_validator(mode="after")
    def _validate_definition_variables(self) -> "WorkflowCreate":
        if "variables" in self.definition:
            try:
                WorkflowVariablesSchema(variables=self.definition["variables"])
            except Exception as exc:
                raise ValueError(f"definition.variables invalido: {exc}") from exc
        return self


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
    tags: list[str] | None = None

    @field_validator("tags", mode="before")
    @classmethod
    def _normalize_tags(cls, v: Any) -> list[str] | None:
        if v is None:
            return None
        return _normalize_tags(v)

    @model_validator(mode="after")
    def _validate_definition_variables(self) -> "WorkflowUpdate":
        if self.definition and "variables" in self.definition:
            try:
                WorkflowVariablesSchema(variables=self.definition["variables"])
            except Exception as exc:
                raise ValueError(f"definition.variables invalido: {exc}") from exc
        return self


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
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class WorkflowListResponse(BaseModel):
    """Resposta paginada de workflows."""

    items: list[WorkflowResponse]
    total: int
    page: int
    size: int


class WorkflowVersionCreate(BaseModel):
    """Payload para publicar uma nova versao de um workflow."""

    io_schema: WorkflowIOSchema = Field(default_factory=WorkflowIOSchema)
    definition: dict[str, Any] | None = Field(
        default=None,
        description="Snapshot a publicar; se None, usa a definition atual do workflow.",
    )


class WorkflowVersionResponse(BaseModel):
    """Versao publicada retornada pela API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_id: UUID
    version: int
    input_schema: list[WorkflowParam]
    output_schema: list[WorkflowParam]
    # Variaveis globais declaradas no corpo do sub-workflow. Permite ao caller
    # (no ``call_workflow``) exibir e preencher esses valores. Extraido de
    # ``definition.variables`` pelo endpoint — nao e persistido em coluna
    # dedicada do banco.
    variables: list[WorkflowParam] = Field(default_factory=list)
    published: bool
    created_at: datetime


class CallableWorkflowSummary(BaseModel):
    """Item do catalogo /workflows/callable — workflows com ao menos 1 versao."""

    workflow_id: UUID
    name: str
    description: str | None = None
    latest_version: int
    versions: list[int]


class WorkflowCloneRequest(BaseModel):
    """Payload para clonar um template em um projeto destino.

    Quando o template usa variáveis de conexão (``type="connection"``), o
    consultor preenche os valores concretos no momento da execução via o
    formulário gerado automaticamente.  Nesse caso ``connection_mapping``
    pode ser omitido.

    .. deprecated::
        ``connection_mapping`` é o mecanismo legado de remapeamento de
        ``connection_id`` fixos.  Prefira declarar variáveis de conexão no
        template (``type="connection"``) e deixar ``connection_mapping``
        vazio.  Manter suporte para retrocompatibilidade com templates
        antigos que ainda contêm UUIDs literais nos nós.
    """

    target_project_id: UUID
    connection_mapping: dict[str, UUID] = Field(
        default_factory=dict,
        description=(
            "[DEPRECATED] Mapeamento de connection_id fixos: {'uuid_velho': 'uuid_novo'}. "
            "Prefira variáveis de conexão (type='connection') declaradas no template."
        ),
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
