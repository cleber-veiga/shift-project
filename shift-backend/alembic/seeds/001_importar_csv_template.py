"""
Seed: Template "Importar CSV para tabela"

Cria um template de workflow publicado no workspace que demonstra o uso de
variaveis (file_upload, connection, string) em vez de connection_id fixo.

Uso:
    python -m alembic.seeds.001_importar_csv_template --workspace-id <UUID>

Ou via Python:
    from alembic.seeds.001_importar_csv_template import seed
    await seed(db, workspace_id="<UUID>")
"""

import argparse
import asyncio
import uuid

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.workflow import Workflow


TEMPLATE_DEFINITION: dict = {
    "variables": [
        {
            "name": "arquivo_csv",
            "type": "file_upload",
            "required": True,
            "description": "Arquivo CSV a ser importado",
            "accepted_extensions": [".csv"],
            "ui_group": "Dados de entrada",
            "ui_order": 1,
        },
        {
            "name": "conexao_destino",
            "type": "connection",
            "required": True,
            "description": "Conexao com o banco de dados destino",
            "ui_group": "Destino",
            "ui_order": 2,
        },
        {
            "name": "tabela_destino",
            "type": "string",
            "required": True,
            "description": "Nome da tabela destino (ex: schema.tabela)",
            "ui_group": "Destino",
            "ui_order": 3,
        },
    ],
    "nodes": [
        {
            "id": "csv_leitura",
            "type": "csv_input",
            "label": "Leitura CSV",
            "config": {
                "url": "{{vars.arquivo_csv}}",
                "delimiter": ",",
                "has_header": True,
            },
        },
        {
            "id": "bulk_insert",
            "type": "bulk_insert",
            "label": "Inserir na tabela",
            "config": {
                "connection_id": "{{vars.conexao_destino}}",
                "table_name": "{{vars.tabela_destino}}",
                "if_exists": "append",
            },
        },
    ],
    "edges": [
        {"source": "csv_leitura", "target": "bulk_insert"},
    ],
    "meta": {
        "description": "Template padrao para importacao de CSV via variaveis — sem connection_id fixo.",
    },
}


async def seed(db, workspace_id: str) -> Workflow:
    """Insere o template se ainda nao existir para o workspace."""
    ws_uuid = uuid.UUID(workspace_id)

    existing = await db.execute(
        select(Workflow)
        .where(Workflow.workspace_id == ws_uuid)
        .where(Workflow.name == "Importar CSV para tabela")
        .where(Workflow.is_template.is_(True))
    )
    if existing.scalar_one_or_none() is not None:
        print(f"Template ja existe no workspace {workspace_id} — ignorando.")
        return existing.scalar_one_or_none()

    template = Workflow(
        name="Importar CSV para tabela",
        description="Importa um arquivo CSV para uma tabela via variaveis de conexao.",
        workspace_id=ws_uuid,
        project_id=None,
        is_template=True,
        is_published=True,
        definition=TEMPLATE_DEFINITION,
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)
    print(f"Template criado: {template.id}")
    return template


async def _main(workspace_id: str) -> None:
    async with AsyncSessionLocal() as db:
        async with db.begin():
            await seed(db, workspace_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed template 'Importar CSV para tabela'")
    parser.add_argument("--workspace-id", required=True, help="UUID do workspace destino")
    args = parser.parse_args()
    asyncio.run(_main(args.workspace_id))
