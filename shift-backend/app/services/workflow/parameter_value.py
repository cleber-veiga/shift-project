"""
Tipo compartilhado ParameterValue e resolutor para nós de workflow.

Espelha o tipo TypeScript em shift-frontend/lib/workflow/parameter-value.ts.
Não altera nenhum nó existente — este módulo é a fundação que nós futuros
importarão ao migrar da lógica ad-hoc atual.
"""

from __future__ import annotations

import re
import uuid as _uuid_module
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter, model_validator

# ---------------------------------------------------------------------------
# Tipos
# ---------------------------------------------------------------------------

TransformKind = Literal[
    "upper", "lower", "trim", "digits_only",
    "remove_specials", "replace", "truncate", "remove_chars",
]


class TransformEntry(BaseModel):
    kind: TransformKind
    args: dict[str, str | int] | None = None


class FixedValue(BaseModel):
    mode: Literal["fixed"] = "fixed"
    value: str


class DynamicValue(BaseModel):
    mode: Literal["dynamic"] = "dynamic"
    template: str
    transforms: list[TransformEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_template_not_empty(self) -> "DynamicValue":
        if not self.template.strip():
            raise ValueError(
                "dynamic ParameterValue: template não pode ser vazio"
            )
        return self


ParameterValue = FixedValue | DynamicValue

# Adapter para parsing de JSON/dict arbitrário com discriminador "mode".
_ADAPTER: TypeAdapter[ParameterValue] = TypeAdapter(
    Annotated[Union[FixedValue, DynamicValue], Field(discriminator="mode")]
)


def parse_parameter_value(raw: dict[str, Any]) -> ParameterValue:
    """Converte um dict (e.g. vindo de JSON) para ParameterValue validado."""
    return _ADAPTER.validate_python(raw)


# ---------------------------------------------------------------------------
# Contexto de resolução
# ---------------------------------------------------------------------------

class ResolutionContext:
    """
    Dados disponíveis durante a resolução de um ParameterValue.

    Atributos:
        input_data:       campos do input direto do nó { campo: valor }
        upstream_results: resultados indexados por node_id { node_id: { campo: valor } }
        vars:             variáveis globais do workflow { nome: valor }
        all_results:      todos os resultados executados até agora (não apenas os pais
                          diretos). Usado como fallback quando um token referencia um
                          ancestral não-direto — por exemplo, um ``workflow_input``
                          cujo resultado foi ocultado por um ``sync``/``Aguardar Todos``
                          intermediário.
    """

    def __init__(
        self,
        input_data: dict[str, Any] | None = None,
        upstream_results: dict[str, dict[str, Any]] | None = None,
        vars: dict[str, Any] | None = None,
        all_results: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.input_data: dict[str, Any] = input_data or {}
        self.upstream_results: dict[str, dict[str, Any]] = upstream_results or {}
        self.vars: dict[str, Any] = vars or {}
        self.all_results: dict[str, dict[str, Any]] = all_results or {}


# ---------------------------------------------------------------------------
# Resolução de template
# ---------------------------------------------------------------------------

# Captura {{TOKEN}} e $builtin
_TOKEN_RE = re.compile(r"\{\{([^}]+)\}\}|\$([a-zA-Z_]+)")


def _resolve_builtin(name: str) -> str:
    if name == "now":
        return datetime.now(tz=timezone.utc).isoformat()
    if name == "uuid":
        return str(_uuid_module.uuid4())
    raise ValueError(f"Função builtin desconhecida: ${name}")


def _resolve_token(token: str, ctx: ResolutionContext) -> Any:
    """Resolve um token {{TOKEN}} (sem as chaves) para seu valor no contexto.

    Suporta caminhos multi-segmento em upstream_results:
        {{node_X.CAMPO}}       → ctx.upstream_results["node_X"]["CAMPO"]
        {{node_X.data.CAMPO}}  → ctx.upstream_results["node_X"]["data"]["CAMPO"]
    """
    token = token.strip()

    if token.startswith("vars."):
        var_name = token[5:]
        if var_name not in ctx.vars:
            raise KeyError(
                f"Variável '{{{{vars.{var_name}}}}}' não encontrada no contexto"
            )
        return ctx.vars[var_name]

    if "." in token:
        parts = token.split(".")
        node_id = parts[0]
        if node_id in ctx.upstream_results:
            current: Any = ctx.upstream_results[node_id]
        elif node_id in ctx.all_results:
            # Ancestral não-direto: o runner expõe o histórico completo em
            # ``all_results``. Fallback necessário para grafos com nós de
            # convergência (sync) que isolam o downstream dos pais originais.
            current = ctx.all_results[node_id]
        else:
            raise KeyError(
                f"Nó '{node_id}' não encontrado em upstream_results"
            )
        for part in parts[1:]:
            if not isinstance(current, dict) or part not in current:
                raise KeyError(
                    f"Campo '{part}' não encontrado no caminho '{token}'"
                )
            current = current[part]
        return current

    if token not in ctx.input_data:
        raise KeyError(
            f"Campo '{{{{{token}}}}}' não encontrado em input_data"
        )
    return ctx.input_data[token]


def _apply_transforms(value: Any, transforms: list[TransformEntry]) -> Any:
    """Aplica cada transform em ordem; converte para str quando necessário."""
    result: Any = value
    for t in transforms:
        s = str(result)
        if t.kind == "upper":
            result = s.upper()
        elif t.kind == "lower":
            result = s.lower()
        elif t.kind == "trim":
            result = s.strip()
        elif t.kind == "digits_only":
            result = re.sub(r"\D", "", s)
        elif t.kind == "remove_specials":
            result = re.sub(r"[^a-zA-Z0-9\s]", "", s)
        elif t.kind == "replace":
            args = t.args or {}
            old = str(args.get("old", ""))
            new = str(args.get("new", ""))
            result = s.replace(old, new)
        elif t.kind == "truncate":
            args = t.args or {}
            max_len = int(args.get("length", 0))
            result = s[:max_len]
        elif t.kind == "remove_chars":
            args = t.args or {}
            chars = str(args.get("chars", ""))
            if chars:
                # Escape metacharacters special inside a regex character class: \ ] ^ -
                char_class = re.sub(r'([-\]\\^])', r'\\\1', chars)
                result = re.sub(f'[{char_class}]', '', s)
    return result


# ---------------------------------------------------------------------------
# Pre-compiled template (hot-loop optimisation)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CompiledTemplate:
    """DynamicValue pre-tokenizado para execução eficiente por linha.

    Compilar uma vez fora do loop e executar N vezes dentro elimina o custo
    de Pydantic + re.finditer por linha × por parâmetro.
    """
    tokens: list[tuple[str, str]]   # ("text"|"field"|"builtin", valor)
    transforms: list[TransformEntry]


def compile_parameter(pv: ParameterValue) -> "CompiledTemplate | str":
    """Pre-compila um ParameterValue.

    - FixedValue  → string pura (sem dataclass — máximo de cheapness)
    - DynamicValue → CompiledTemplate com tokens e transforms prontos
    """
    if isinstance(pv, FixedValue):
        return pv.value
    template = pv.template
    tokens: list[tuple[str, str]] = []
    last = 0
    for m in _TOKEN_RE.finditer(template):
        if m.start() > last:
            tokens.append(("text", template[last : m.start()]))
        if m.group(2):
            tokens.append(("builtin", m.group(2)))
        else:
            tokens.append(("field", m.group(1).strip()))
        last = m.end()
    if last < len(template):
        tokens.append(("text", template[last:]))
    return CompiledTemplate(tokens=tokens, transforms=list(pv.transforms))


def execute_compiled(compiled: "CompiledTemplate | str", ctx: ResolutionContext) -> Any:
    """Executa um resultado de compile_parameter num contexto de resolução.

    Permite compilar uma vez fora do loop e chamar N vezes (uma por linha).
    """
    if isinstance(compiled, str):
        return compiled
    tokens = compiled.tokens
    if not tokens:
        return _apply_transforms("", compiled.transforms)
    if len(tokens) == 1:
        kind, value = tokens[0]
        if kind == "text":
            return _apply_transforms(value, compiled.transforms)
        if kind == "field":
            return _apply_transforms(_resolve_token(value, ctx), compiled.transforms)
        return _apply_transforms(_resolve_builtin(value), compiled.transforms)
    parts: list[str] = []
    for kind, value in tokens:
        if kind == "text":
            parts.append(value)
        elif kind == "field":
            resolved = _resolve_token(value, ctx)
            parts.append("" if resolved is None else str(resolved))
        else:
            parts.append(str(_resolve_builtin(value)))
    return _apply_transforms("".join(parts), compiled.transforms)


# ---------------------------------------------------------------------------
# Migração de formato legado (sql_script)
# ---------------------------------------------------------------------------

_LEGACY_UPSTREAM_RE = re.compile(r"^(?:upstream_results|upstream)\.(.+)$")


def migrate_legacy_sql_parameter(raw: "str | dict[str, Any]") -> ParameterValue:
    """Converte um valor legado de parâmetro SQL Script para ParameterValue.

    Formatos suportados:
      "upstream_results.node_X.data.CAMPO" → dynamic  template="{{node_X.data.CAMPO}}"
      "upstream.node_X.CAMPO"              → dynamic  template="{{node_X.CAMPO}}"
      { mode: "fixed"|"dynamic", ... }     → retorna como ParameterValue (já migrado)
      "valor_literal"                      → fixed    value="valor_literal"
      ""                                   → fixed    value=""
    """
    if isinstance(raw, dict) and "mode" in raw:
        return parse_parameter_value(raw)

    if not isinstance(raw, str):
        return FixedValue(value=str(raw) if raw is not None else "")

    path = raw.strip()
    if not path:
        return FixedValue(value="")

    m = _LEGACY_UPSTREAM_RE.match(path)
    if m:
        token = m.group(1)  # e.g. "node_X.data.CAMPO" or "node_X.CAMPO"
        return DynamicValue(template=f"{{{{{token}}}}}")

    return FixedValue(value=path)


# Alias — mesma lógica, nome semântico para o nó Loop.
migrate_legacy_loop_source = migrate_legacy_sql_parameter


def extract_field_reference(left: Any) -> str:
    """Extrai o nome de coluna do lado esquerdo de uma condição (PV ou string).

    Aceita o raw dict vindo do JSON de configuração do nó, antes do parsing.

    - str pura            → retorna diretamente
    - fixed PV  (dict)    → retorna value (nome da coluna)
    - dynamic PV chip único {{X}} → retorna X
    - dynamic PV multi-token/texto livre → retorna o template (fallback)
    - None / outro        → retorna "" (seguro para checagem `if not field`)
    """
    if isinstance(left, str):
        return left
    if isinstance(left, dict):
        mode = left.get("mode")
        if mode == "fixed":
            return str(left.get("value", ""))
        if mode == "dynamic":
            template = str(left.get("template", ""))
            m = re.match(r"^\{\{([^}]+)\}\}$", template.strip())
            if m:
                return m.group(1)
            return template
    return str(left) if left is not None else ""


def resolve_parameter(value: ParameterValue, ctx: ResolutionContext) -> Any:
    """
    Resolve um ParameterValue para seu valor concreto dado o contexto.

    Regras:
    - mode="fixed"  → retorna value.value diretamente
    - mode="dynamic" com token único ocupando o template inteiro
                    → retorna o tipo original (int, bool, etc.)
    - mode="dynamic" com múltiplos tokens ou texto misturado
                    → concatena tudo como string
    - transforms são aplicados ao resultado final (sempre em cima do tipo já
      resolvido; se transform for aplicado, converte para str)

    Para uso em hot loops (ex: bulk_insert), prefira compile_parameter uma
    vez fora do loop e execute_compiled a cada linha.
    """
    return execute_compiled(compile_parameter(value), ctx)
