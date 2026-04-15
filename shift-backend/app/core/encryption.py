"""
Criptografia simetrica para dados sensiveis armazenados no banco de dados.

Usa Fernet (AES-128-CBC + HMAC-SHA256) da biblioteca `cryptography`.
A chave e carregada de settings.ENCRYPTION_KEY, que deve ser uma chave
Fernet valida (32 bytes, URL-safe base64-encoded, 44 caracteres).

Geracao de uma nova chave (uma unica vez, no setup do projeto):

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Armazene o valor gerado na variavel de ambiente ENCRYPTION_KEY.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Retorna a instancia Fernet usando a chave das settings (cache singleton)."""
    from app.core.config import settings

    return Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt(plaintext: str) -> str:
    """Criptografa um texto plano e retorna o token Fernet como string UTF-8."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """
    Descriptografa um token Fernet e retorna o texto plano.

    Raises:
        cryptography.fernet.InvalidToken: se o token for invalido ou a chave incorreta.
    """
    return _get_fernet().decrypt(token.encode()).decode()


class EncryptedString(TypeDecorator):
    """
    Tipo SQLAlchemy que criptografa/descriptografa valores de coluna de forma transparente.

    Uso:
        password: Mapped[str] = mapped_column(EncryptedString(1024), nullable=False)

    O valor e armazenado no banco como token Fernet (string longa).
    Ao ler do banco, e descriptografado automaticamente antes de retornar.
    Ao escrever no banco, e criptografado automaticamente antes de persistir.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        """Chamado ao gravar no banco: criptografa o valor."""
        if value is None:
            return None
        return encrypt(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:
        """Chamado ao ler do banco: descriptografa o valor."""
        if value is None:
            return None
        try:
            return decrypt(value)
        except (InvalidToken, Exception):
            # Valor corrompido ou chave trocada — retorna None para nao quebrar a API.
            return None
