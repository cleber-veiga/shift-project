"""
Registro de processadores de nos do workflow.

Cada processador herda de BaseNodeProcessor e se registra via
@register_processor("tipo"). O registro e usado pelo motor do workflow
para despachar a logica correta por tipo de no.
"""

from abc import ABC, abstractmethod
import re
from typing import Any


_PROCESSOR_REGISTRY: dict[str, type["BaseNodeProcessor"]] = {}
_TEMPLATE_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}|\{([^{}]+?)\}")


def register_processor(node_type: str):
    """Decorator que registra um processador de no pelo seu tipo."""

    def decorator(cls: type["BaseNodeProcessor"]) -> type["BaseNodeProcessor"]:
        _PROCESSOR_REGISTRY[node_type] = cls
        return cls

    return decorator


def has_processor(node_type: str) -> bool:
    """Indica se existe processador registrado para o tipo informado."""
    return node_type in _PROCESSOR_REGISTRY


def get_processor(node_type: str) -> "BaseNodeProcessor":
    """Retorna uma instancia do processador para o tipo de no informado."""
    cls = _PROCESSOR_REGISTRY.get(node_type)
    if cls is None:
        raise ValueError(
            f"Processador nao encontrado para o tipo '{node_type}'. "
            f"Tipos registrados: {list(_PROCESSOR_REGISTRY.keys())}"
        )
    return cls()


class BaseNodeProcessor(ABC):
    """
    Classe base abstrata para processadores de nos.

    Todo processador implementa `process`, que recebe o ID do no,
    sua configuracao e o contexto da execucao do workflow.
    """

    @abstractmethod
    def process(
        self,
        node_id: str,
        config: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Processa o no e retorna os dados de saida."""
        ...

    def resolve_template(self, value: str, context: dict[str, Any]) -> Any:
        """
        Resolve placeholders simples em strings usando o contexto do workflow.

        Exemplos suportados:
            "{input_data.id}"
            "{{ upstream_results.no_1.output.token }}"
        """
        matches = list(_TEMPLATE_PATTERN.finditer(value))
        if not matches:
            return value

        if len(matches) == 1 and matches[0].span() == (0, len(value)):
            path = matches[0].group(1) or matches[0].group(2) or ""
            return self._resolve_path(path.strip(), context)

        def replacer(match: re.Match[str]) -> str:
            path = (match.group(1) or match.group(2) or "").strip()
            resolved = self._resolve_path(path, context)
            if resolved is None:
                return ""
            return str(resolved)

        return _TEMPLATE_PATTERN.sub(replacer, value)

    def resolve_data(self, data: Any, context: dict[str, Any]) -> Any:
        """Resolve templates de forma recursiva em dicts, listas e strings."""
        if isinstance(data, str):
            return self.resolve_template(data, context)
        if isinstance(data, list):
            return [self.resolve_data(item, context) for item in data]
        if isinstance(data, dict):
            return {
                str(key): self.resolve_data(value, context)
                for key, value in data.items()
            }
        return data

    def _resolve_path(self, path: str, context: dict[str, Any]) -> Any:
        """Resolve um caminho com notacao de pontos dentro do contexto."""
        current: Any = context
        if not path:
            return None

        for raw_part in path.split("."):
            part = raw_part.strip()
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                index = int(part)
                if 0 <= index < len(current):
                    current = current[index]
                else:
                    return None
            else:
                current = getattr(current, part, None)

            if current is None:
                return None

        return current


from app.services.workflow.nodes.manual_trigger import ManualTriggerProcessor  # noqa: E402, F401
from app.services.workflow.nodes.webhook_trigger import WebhookTriggerProcessor  # noqa: E402, F401
from app.services.workflow.nodes.cron_trigger import CronTriggerProcessor  # noqa: E402, F401
from app.services.workflow.nodes.polling_trigger import PollingTriggerProcessor  # noqa: E402, F401
from app.services.workflow.nodes.sql_database import SqlDatabaseProcessor  # noqa: E402, F401
from app.services.workflow.nodes.http_request import HttpRequestProcessor  # noqa: E402, F401
from app.services.workflow.nodes.mapper_node import MapperNodeProcessor  # noqa: E402, F401
from app.services.workflow.nodes.filter_node import FilterNodeProcessor  # noqa: E402, F401
from app.services.workflow.nodes.aggregator_node import AggregatorNodeProcessor  # noqa: E402, F401
from app.services.workflow.nodes.math_node import MathNodeProcessor  # noqa: E402, F401
from app.services.workflow.nodes.load_node import LoadNodeProcessor  # noqa: E402, F401
from app.services.workflow.nodes.code_node import CodeNodeProcessor  # noqa: E402, F401
from app.services.workflow.nodes.condition_node import IfElseNodeProcessor, SwitchNodeProcessor  # noqa: E402, F401
from app.services.workflow.nodes.join_node import JoinNodeProcessor  # noqa: E402, F401
from app.services.workflow.nodes.deduplication_node import DeduplicationNodeProcessor  # noqa: E402, F401
from app.services.workflow.nodes.assert_node import AssertNodeProcessor  # noqa: E402, F401
from app.services.workflow.nodes.lookup_node import LookupNodeProcessor  # noqa: E402, F401
from app.services.workflow.nodes.notification_node import NotificationNodeProcessor  # noqa: E402, F401
from app.services.workflow.nodes.csv_input_node import CsvInputNodeProcessor  # noqa: E402, F401
from app.services.workflow.nodes.excel_input_node import ExcelInputNodeProcessor  # noqa: E402, F401
from app.services.workflow.nodes.api_input_node import ApiInputNodeProcessor  # noqa: E402, F401
from app.services.workflow.nodes.inline_data_node import InlineDataNodeProcessor  # noqa: E402, F401
