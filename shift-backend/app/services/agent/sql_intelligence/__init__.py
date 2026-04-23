"""SQL Intelligence — analise estatica de SQL para o Platform Agent.

Exporta as funcoes publicas do modulo parser.
"""

from app.services.agent.sql_intelligence.parser import (
    BindParam,
    TableRef,
    analyze_sql_script,
    classify_destructiveness,
    extract_binds,
    extract_tables,
    split_statements,
)

__all__ = [
    "BindParam",
    "TableRef",
    "analyze_sql_script",
    "classify_destructiveness",
    "extract_binds",
    "extract_tables",
    "split_statements",
]
