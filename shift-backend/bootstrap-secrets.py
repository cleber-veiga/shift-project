#!/usr/bin/env python3
"""
Bootstrap de segredos da plataforma Shift.

Gera SECRET_KEY (JWT) e ENCRYPTION_KEY (Fernet) na primeira execucao e
persiste em /shift-secrets/secrets.env. Idempotente: se o arquivo ja
existe, nao faz nada.

Roda no entrypoint do shift-backend antes do uvicorn. O Pydantic Settings
le esse arquivo como uma das fontes de env_file (ver app/core/config.py).

Por que aqui e nao no compose:
  - Funciona igual em Linux, WSL2 e Docker Desktop (Windows/macOS).
  - Reusa o Python ja presente na imagem do backend (sem service init
    extra, sem dependencia de bash/openssl no host).
  - Volume nomeado `shift_secrets` persiste entre `docker compose down`
    e `up` (so e destruido com `down -v` explicito).

ATENCAO: apagar /shift-secrets/secrets.env e regerar a ENCRYPTION_KEY
INVALIDA todas as credenciais criptografadas no banco (tabela connections,
etc). Tratar com cuidado.
"""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path


SECRETS_DIR = Path(os.environ.get("SHIFT_SECRETS_DIR", "/shift-secrets"))
SECRETS_FILE = SECRETS_DIR / "secrets.env"


def main() -> int:
    try:
        SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(
            f"[bootstrap-secrets] WARN: nao consegui criar {SECRETS_DIR}: {e}. "
            "Pulando geracao — config.py cai no fallback de env vars.",
            file=sys.stderr,
        )
        return 0

    if SECRETS_FILE.exists():
        print(f"[bootstrap-secrets] {SECRETS_FILE} ja existe — pulando geracao.")
        return 0

    try:
        from cryptography.fernet import Fernet
    except ImportError:
        print(
            "[bootstrap-secrets] WARN: cryptography nao instalado. "
            "Pulando geracao — config.py cai no fallback de env vars.",
            file=sys.stderr,
        )
        return 0

    secret_key = secrets.token_urlsafe(64)
    encryption_key = Fernet.generate_key().decode()

    content = (
        "# Gerado automaticamente pelo bootstrap-secrets.py na primeira\n"
        "# subida do stack. NAO edite manualmente.\n"
        "#\n"
        "# Apagar este arquivo regera as chaves — isso INVALIDA todos os\n"
        "# dados criptografados no banco (credenciais de connections, etc).\n"
        f"SECRET_KEY={secret_key}\n"
        f"ENCRYPTION_KEY={encryption_key}\n"
    )
    SECRETS_FILE.write_text(content, encoding="utf-8")
    try:
        SECRETS_FILE.chmod(0o600)
    except OSError:
        pass

    print(f"[bootstrap-secrets] segredos gerados em {SECRETS_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
