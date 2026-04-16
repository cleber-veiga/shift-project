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

    # --- Seguranca / JWT ---
    SECRET_KEY: str = "CHANGE-ME-IN-PRODUCTION"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- Criptografia de Credenciais ---
    # Chave Fernet (32 bytes, base64-url encoded, 44 chars).
    # Gere com: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ENCRYPTION_KEY: str = "CHANGE-ME-GENERATE-A-REAL-FERNET-KEY-32B="

    # --- Prefect ---
    PREFECT_FLOW_NAME: str = "dynamic-runner"
    PREFECT_DEPLOYMENT_NAME: str = "dynamic-runner/shift-workflow-runner"
    # Work pool usado pelo worker. Serve de fallback para deployments cron quando o
    # deployment base nao for encontrado ou nao tiver work_pool_name configurado.
    PREFECT_WORK_POOL_NAME: str = ""

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

    # --- AI / LLM (SQL Assistant) ---
    # Identificador LiteLLM do modelo. Prefixo define o provider:
    #   anthropic/claude-sonnet-4-20250514, gpt-4o, gemini/gemini-2.0-flash, ollama/llama3.2
    LLM_MODEL: str = "anthropic/claude-sonnet-4-20250514"
    # Chave de API do provider ativo (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.)
    LLM_API_KEY: str = ""
    # URL base opcional — apenas para Ollama ou endpoints customizados
    LLM_BASE_URL: str | None = None

    @property
    def DATABASE_URL_SYNC(self) -> str:
        """URL sincrona (psycopg2) para uso com Alembic."""
        return self.DATABASE_URL.replace("+asyncpg", "+psycopg2")


# Singleton utilizado em toda a aplicacao
settings = Settings()
