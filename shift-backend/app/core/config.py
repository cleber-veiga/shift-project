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

    # --- Upload de arquivos para variaveis de workflow ---
    # Diretorio local onde os arquivos uploadados sao armazenados.
    # Em producao substitua por um bucket S3/MinIO.
    WORKFLOW_UPLOAD_DIR: str = "workflow_uploads"

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
