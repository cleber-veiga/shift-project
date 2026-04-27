"""
Helpers compartilhados pelos nos de entrada de arquivo (csv_input,
excel_input). Concentra logica que se repetiria nos dois nos:

- ``resolve_upload_url``: traduz ``shift-upload://<id>`` (ou UUID puro,
  legado) para path absoluto local via ``workflow_file_upload_service``,
  com ``touch()`` pra proteger contra cleanup mid-execution.

- ``validate_against_input_model``: compara colunas reais do arquivo
  com schema do ``InputModel`` vinculado. Em CSV usa sheet 0 (sempre
  unica). Em Excel, recebe ``sheet_name`` e tenta casar com a sheet
  homonima no modelo; se nao casar, valida contra a primeira sheet do
  modelo (fallback) emitindo log info.

Regras de validacao (v1):
    - Coluna ``required: true`` ausente -> NodeProcessingError
    - Coluna opcional ausente -> OK
    - Coluna extra no arquivo -> log info, nao bloqueia
    - Tipo divergente -> NAO valido em v1
    - Comparacao de nomes case-insensitive
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.services.workflow.nodes.exceptions import NodeProcessingError
from app.services.workflow_file_upload_service import workflow_file_upload_service

logger = get_logger(__name__)

# Scheme interno: arquivo uploadado via /workflows/{id}/uploads
_UPLOAD_SCHEME = "shift-upload://"

# UUID v4 (case-insensitive). Fallback pra quando variavel file_upload
# tem apenas o file_id sem o scheme (legado de execute-workflow-dialog
# que salvava setValue(name, file_id) sem prefixo).
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def resolve_upload_url(node_id: str, raw_url: str, context: dict[str, Any]) -> str:
    """Resolve referencia a upload de workflow para path absoluto local.

    Aceita:
        - ``shift-upload://<file_id>`` (formato canonico)
        - ``<file_id>`` UUID puro (legado de variaveis file_upload)
        - Qualquer outra coisa (http://, s3://, /path) passa direto
    """
    candidate = raw_url.strip()

    file_id: str | None = None
    if candidate.startswith(_UPLOAD_SCHEME):
        file_id = candidate[len(_UPLOAD_SCHEME):].strip()
    elif _UUID_RE.match(candidate):
        file_id = candidate

    if file_id is None:
        return raw_url

    workflow_id = context.get("workflow_id")
    if not workflow_id:
        raise NodeProcessingError(
            f"No '{node_id}': referencia a upload exige workflow_id no contexto."
        )

    workflow_id_str = str(workflow_id)
    resolved = workflow_file_upload_service.resolve_url(workflow_id_str, file_id)
    if resolved is None:
        raise NodeProcessingError(
            f"No '{node_id}': arquivo '{file_id}' nao encontrado ou foi removido. "
            f"Re-faca o upload pela UI."
        )
    workflow_file_upload_service.touch(workflow_id_str, file_id)
    return resolved


def validate_against_input_model(
    node_id: str,
    input_model_id: str,
    actual_columns: list[str],
    sheet_name: str | None = None,
) -> None:
    """Valida colunas do arquivo contra schema do InputModel vinculado.

    Args:
        node_id: id do no, usado em mensagens de erro.
        input_model_id: UUID do InputModel.
        actual_columns: lista de colunas presentes no arquivo (na ordem).
        sheet_name: nome da sheet em uso (Excel). None = sheet[0].

    Selecao de sheet do modelo:
        - sheet_name=None -> sheets[0]
        - sheet_name informado e existe no modelo -> sheet homonima
        - sheet_name informado mas nao existe -> sheets[0] + log info

    Levanta ``NodeProcessingError`` listando colunas obrigatorias
    ausentes e o que veio no arquivo. Modelo deletado: log warning,
    nao falha (caller pode remover o vinculo na UI).
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.db.session import sync_session_factory  # noqa: PLC0415
    from app.models.input_model import InputModel  # noqa: PLC0415

    try:
        model_uuid = UUID(input_model_id)
    except (TypeError, ValueError):
        raise NodeProcessingError(
            f"No '{node_id}': input_model_id '{input_model_id}' nao e um "
            f"UUID valido."
        )

    with sync_session_factory() as session:
        model = session.execute(
            select(InputModel).where(InputModel.id == model_uuid)
        ).scalar_one_or_none()

    if model is None:
        logger.warning(
            "input_model.missing",
            node_id=node_id,
            input_model_id=input_model_id,
        )
        return

    schema_def = model.schema_def or {}
    sheets = schema_def.get("sheets") or []
    if not sheets:
        logger.warning(
            "input_model.empty_schema",
            node_id=node_id,
            input_model_id=input_model_id,
        )
        return

    # Seleciona a sheet do MODELO a usar
    selected_sheet = None
    if sheet_name:
        selected_sheet = next(
            (s for s in sheets if str(s.get("name", "")).lower() == str(sheet_name).lower()),
            None,
        )
        if selected_sheet is None:
            logger.info(
                "input_model.sheet_fallback",
                node_id=node_id,
                input_model_id=input_model_id,
                requested_sheet=sheet_name,
                model_sheets=[s.get("name") for s in sheets],
            )
    if selected_sheet is None:
        selected_sheet = sheets[0]

    expected_columns = selected_sheet.get("columns") or []

    actual_set = {c.lower() for c in actual_columns}
    required_names = [
        c["name"]
        for c in expected_columns
        if c.get("required") and c.get("name")
    ]
    missing_required = [
        name for name in required_names if name.lower() not in actual_set
    ]

    if missing_required:
        sheet_label = (
            f" (sheet '{selected_sheet.get('name')}')"
            if sheet_name or len(sheets) > 1
            else ""
        )
        raise NodeProcessingError(
            f"No '{node_id}': arquivo nao corresponde ao modelo "
            f"'{model.name}'{sheet_label}. "
            f"Colunas obrigatorias ausentes: {', '.join(missing_required)}. "
            f"Presentes no arquivo: {', '.join(actual_columns)}. "
            f"Sugestao: ajuste o cabecalho do arquivo ou edite o modelo."
        )

    expected_set = {
        c.get("name", "").lower() for c in expected_columns if c.get("name")
    }
    extras = [c for c in actual_columns if c.lower() not in expected_set]
    if extras:
        logger.info(
            "input_model.extra_columns",
            node_id=node_id,
            input_model_id=input_model_id,
            extra_columns=extras,
        )
