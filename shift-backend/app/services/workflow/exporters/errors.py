"""Excecoes dos exportadores de workflow."""

from __future__ import annotations

from typing import Any


class UnsupportedNodeError(Exception):
    """Erro estruturado para nos cuja exportacao nao e suportada na V1.

    Carrega ``unsupported`` como lista de dicts ``{node_id, node_type, reason}``
    para que a camada de API converta em HTTP 422 com corpo navegavel pelo
    frontend.
    """

    def __init__(self, unsupported: list[dict[str, Any]]) -> None:
        self.unsupported: list[dict[str, Any]] = list(unsupported)
        super().__init__(
            f"Cannot export workflow: {len(unsupported)} unsupported nodes."
        )
