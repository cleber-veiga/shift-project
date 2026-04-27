"""
Configuracoes centrais da aplicacao Shift.
Carrega variaveis de ambiente via Pydantic BaseSettings.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuracoes carregadas de variaveis de ambiente ou arquivo .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Banco de Dados da Plataforma (asyncpg) ---
    DATABASE_URL: str = "postgresql+asyncpg://shift:shift@localhost:5432/shift"

    # --- Logging ---
    # LOG_FORMAT: "console" (dev, colorido) ou "json" (producao, machine-readable).
    # LOG_LEVEL:  DEBUG | INFO | WARNING | ERROR | CRITICAL.
    LOG_FORMAT: str = "console"
    LOG_LEVEL: str = "INFO"

    # --- Seguranca / JWT ---
    SECRET_KEY: str = "CHANGE-ME-IN-PRODUCTION"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- Criptografia de Credenciais ---
    # Chave Fernet (32 bytes, base64-url encoded, 44 chars).
    # Gere com: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ENCRYPTION_KEY: str = "CHANGE-ME-GENERATE-A-REAL-FERNET-KEY-32B="

    # --- dlt ---
    DLT_DEFAULT_DESTINATION: str = "postgres"

    # --- Google OAuth2 ---
    # Client ID gerado no Google Cloud Console (OAuth 2.0 → Web application).
    # Deve ser o mesmo CLIENT_ID configurado no botão do Google no frontend.
    GOOGLE_CLIENT_ID: str = ""

    # --- Convites / Email ---
    EMAIL_BACKEND: str = "console"  # "console" (dev) ou "resend" (prod)
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "noreply@shift.app"
    FRONTEND_BASE_URL: str = "http://localhost:3000"
    INVITATION_EXPIRE_DAYS: int = 7

    # --- Checkpoints de execucao ---
    # Diretorio persistente onde arquivos DuckDB de nos com checkpoint_enabled
    # sao copiados para sobreviver a limpeza de /tmp.
    # ATENCAO: o default e relativo ao CWD do processo (``./shift_data/checkpoints``).
    # Em producao DEVE apontar para um volume persistente externo (ex:
    # ``/var/lib/shift/checkpoints`` ou um volume montado em container).
    # NUNCA use ``/tmp/...`` em producao: reboots, politica de tmpfiles e
    # limite de disco do tmpfs podem destruir checkpoints.
    SHIFT_CHECKPOINT_DIR: str = "shift_data/checkpoints"
    # Tempo de expiracao de checkpoints em dias (0 = nao expira).
    SHIFT_CHECKPOINT_EXPIRE_DAYS: int = 7

    # --- Limites de execucao ---
    # Timeout global por execucao em segundos (0 = sem limite).
    WORKFLOW_DEFAULT_MAX_EXECUTION_TIME_SECONDS: int = 3600
    # Maximo de linhas extraidas por no (sql_database, csv_input, excel_input, api_input).
    EXTRACT_DEFAULT_MAX_ROWS: int = 10_000_000
    # Limite injetado em nos de extracao quando ``run_mode=preview`` — permite
    # ao consultor validar o pipeline sem mover o volume todo.
    WORKFLOW_PREVIEW_MAX_ROWS: int = 100
    # Monitor de RAM: cancela a execucao mais antiga ao ultrapassar este limite (MB).
    SHIFT_MAX_EXECUTION_MEMORY_MB: int = 4096
    # Monitor de disco: bloqueia novas execucoes quando /tmp/shift superar este limite (GB).
    SHIFT_MAX_DISK_GB: int = 20

    # --- Rate limiting de execucoes (Sprint 4.2) ---
    # Limites por usuario autenticado (decoded do JWT, sem DB lookup).
    RATE_LIMIT_EXECUTE_USER_MINUTE: int = 30
    RATE_LIMIT_EXECUTE_USER_HOUR: int = 500
    # Limites por projeto (workflow_id -> project_id resolvido em cache em memoria).
    RATE_LIMIT_EXECUTE_PROJECT_MINUTE: int = 100
    RATE_LIMIT_EXECUTE_PROJECT_HOUR: int = 2000

    # --- Sandbox de codigo de usuario (Prompt 2.1) ---
    # Quando True, ``code`` / ``python_code`` nodes executam dentro de um
    # container Docker isolado (kernel-runtime). Quando False, mantem o
    # caminho legacy in-process com builtins restritos — APENAS para
    # ambientes de desenvolvimento single-tenant.
    SANDBOX_ENABLED: bool = False
    # Imagem do container — construida a partir de ``kernel-runtime/Dockerfile``.
    # Em CI/prod, fixar uma tag imutavel (ex: shift-kernel-runtime:2026.04.25).
    SANDBOX_IMAGE: str = "shift-kernel-runtime:latest"
    # Defaults aplicados quando o node nao especifica override. Workspace
    # admins podem subir ate o cap absoluto definido em
    # ``docker_sandbox.ABSOLUTE_CAPS``.
    SANDBOX_DEFAULT_CPU_QUOTA: float = 1.0
    SANDBOX_DEFAULT_MEM_LIMIT_MB: int = 512
    SANDBOX_DEFAULT_TIMEOUT_S: int = 60
    SANDBOX_DEFAULT_TMPFS_MB: int = 128
    SANDBOX_DEFAULT_PIDS_LIMIT: int = 128
    # Pool de containers warm (Prompt 2.2). Quando True, o backend mantem
    # SANDBOX_POOL_TARGET_IDLE containers ja-iniciados e bloqueados em
    # ``sys.stdin.read()`` para que ``acquire`` devolva quase instantaneamente
    # (skip do create+start+import duckdb).
    SANDBOX_POOL_ENABLED: bool = True
    SANDBOX_POOL_TARGET_IDLE: int = 2
    SANDBOX_POOL_MAX_SIZE: int = 8
    SANDBOX_POOL_HEALTHCHECK_INTERVAL_S: float = 30.0

    # --- Streaming entre nodes (Prompt 1.2) ---
    # Numero maximo de chunks em RAM por queue de streaming. Acima disso, e
    # com STREAMING_SPILL_WHEN_EXCEEDED=True, chunks excedentes vao para
    # disco em STREAMING_SPILL_DIR.
    STREAMING_MAX_IN_MEMORY_CHUNKS: int = 4
    # Liga/desliga o spillover. Quando False, o producer bloqueia ao atingir
    # STREAMING_MAX_IN_MEMORY_CHUNKS — backpressure puro, RAM constante.
    STREAMING_SPILL_WHEN_EXCEEDED: bool = True
    # Diretorio onde chunks excedentes sao serializados (pickle por padrao).
    # Em producao deve apontar para tmpfs/local — nao precisa sobreviver a
    # restart porque o cleanup roda no fim de cada execucao. Default vazio
    # delega para ``default_spill_dir()`` (<tempdir>/shift/spill).
    STREAMING_SPILL_DIR: str = ""
    # Acima desse numero de chunks spilados em uma execucao, emitimos WARN
    # com execution_id — sinal de pipeline maldimensionado.
    STREAMING_SPILL_WARN_THRESHOLD: int = 50

    # --- Cache de extracoes (Sprint 4.4) ---
    # Diretorio persistente para DuckDB de entradas em cache.
    # ATENCAO: nao use /tmp — deve sobreviver a restarts.
    SHIFT_EXTRACT_CACHE_DIR: str = "shift_data/extract_cache"
    # TTL padrao em segundos para entradas de cache quando nao configurado no no.
    SHIFT_EXTRACT_CACHE_DEFAULT_TTL_SECONDS: int = 300

    # --- Webhooks ---
    # URL publica do backend usada para montar as URLs de webhook exibidas
    # na UI. Em desenvolvimento, usa-se tipicamente http://localhost:8000.
    # Em producao, apontar para o dominio publico (atras do proxy/tunel).
    EXTERNAL_BASE_URL: str | None = None

    # --- Upload de arquivos para nos e variaveis de workflow ---
    # Diretorio local onde os arquivos uploadados sao armazenados.
    # Em producao substitua por um bucket S3/MinIO — todo o consumo
    # passa por workflow_file_upload_service.resolve_url(), entao
    # trocar storage e cirurgico (so muda o service).
    WORKFLOW_UPLOAD_DIR: str = "workflow_uploads"
    # Tamanho maximo aceito por arquivo individual (MB).
    WORKFLOW_UPLOAD_MAX_FILE_MB: int = 500
    # Quota agregada por projeto (MB). Calculada somando ``size_bytes``
    # de todos os uploads dos workflows do mesmo project_id. Excedeu,
    # POST /uploads retorna 429.
    WORKFLOW_UPLOAD_QUOTA_PER_PROJECT_MB: int = 5120
    # Time-to-live de uploads (dias). Cleanup job remove arquivos com
    # last_accessed_at < now - TTL_DAYS. Cada execucao que usa o arquivo
    # faz ``touch()`` antes da leitura — protege arquivo em uso.
    WORKFLOW_UPLOAD_TTL_DAYS: int = 30
    # Hora UTC em que o cleanup job roda (0-23). Default 03h pra fugir
    # de pico de execucoes em horario comercial.
    WORKFLOW_UPLOAD_CLEANUP_HOUR_UTC: int = 3

    # --- AI / LLM (SQL Assistant) ---
    # Identificador LiteLLM do modelo. Prefixo define o provider:
    #   anthropic/claude-sonnet-4-20250514, gpt-4o, gemini/gemini-2.0-flash, ollama/llama3.2
    LLM_MODEL: str = "anthropic/claude-sonnet-4-20250514"
    # Chave de API do provider ativo (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.)
    LLM_API_KEY: str = ""
    # URL base opcional — apenas para Ollama ou endpoints customizados
    LLM_BASE_URL: str | None = None

    # --- Modo "raciocinio profundo" (ativado por toggle no chat) ---
    # Modelo com capacidade de reasoning (OpenAI o-series, Anthropic extended thinking, etc.).
    # Vazio = modo nao disponivel no UI.
    # Exemplos: openai/o4-mini, openai/o3-mini, anthropic/claude-opus-4-5
    LLM_REASONING_MODEL: str = ""
    # Nivel de esforco: "low" | "medium" | "high" (convertido por LiteLLM).
    LLM_REASONING_EFFORT: str = "medium"
    # Limite maior de tokens para respostas com reasoning (tokens internos + output).
    LLM_REASONING_MAX_TOKENS: int = 8192

    # --- Platform Agent (LangGraph) ---
    # Liga/desliga globalmente o agente de plataforma. Quando False,
    # endpoints /agent retornam 404 e UI oculta o painel.
    AGENT_ENABLED: bool = False

    # Modelo LLM usado pelo Platform Agent (pode ser diferente do SQL assistant).
    AGENT_LLM_MODEL: str = "anthropic/claude-sonnet-4-20250514"

    # Timeout maximo em segundos para uma thread aguardando aprovacao humana
    # antes de ser marcada como expirada.
    AGENT_APPROVAL_TIMEOUT_SECONDS: int = 3600  # 1 hora

    # Overrides de budget por workspace. JSON mapeando workspace_id (UUID str)
    # -> dict parcial com campos de AgentBudget (messages_per_hour, etc.).
    # Exemplo: {"11111111-...": {"messages_per_hour": 120}}
    AGENT_BUDGET_OVERRIDES_JSON: str = ""

    # Intervalo do job de expiracao de aprovacoes pendentes (minutos).
    AGENT_EXPIRATION_JOB_INTERVAL_MINUTES: int = 5

    # --- Observabilidade: LangSmith ---
    # Quando LANGSMITH_TRACING=true, o backend:
    #   1) propaga LANGSMITH_* para os.environ, o que ativa o tracer nativo
    #      do LangGraph (astream_events, node spans, state diffs);
    #   2) registra "langsmith" como success/failure_callback do LiteLLM,
    #      o que envia cada chamada ao LLM (prompt, resposta, latencia,
    #      tokens) para o mesmo projeto como um span independente.
    # Gere a API key em https://smith.langchain.com → Settings → API Keys.
    LANGSMITH_TRACING: bool = False
    LANGSMITH_API_KEY: str = ""
    LANGSMITH_PROJECT: str = "shift-platform-agent"
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"

    @property
    def DATABASE_URL_SYNC(self) -> str:
        """URL sincrona (psycopg2) para uso com Alembic."""
        return self.DATABASE_URL.replace("+asyncpg", "+psycopg2")


# Singleton utilizado em toda a aplicacao
settings = Settings()
