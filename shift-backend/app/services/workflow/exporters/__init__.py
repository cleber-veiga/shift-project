"""
Exportadores de workflow para formatos standalone (Fase 9).

Cobertura V1 — node_types suportados pelos exportadores SQL/Python:

    Entradas (io)
      - sql_database     : CTE com a query do usuario; ATTACH/connection
                            string e gerada como TODO no header.
      - inline_data      : VALUES (...) literal embutido no script.

    Transformacoes narrow
      - filter           : WHERE
      - mapper           : SELECT com renomeacoes / TRY_CAST
      - record_id        : ROW_NUMBER() OVER (...)
      - sample           : LIMIT, USING SAMPLE reservoir, USING SAMPLE PERCENT
      - sort             : ORDER BY ... NULLS FIRST/LAST [LIMIT N]

    Transformacoes wide
      - join             : INNER/LEFT/RIGHT/FULL OUTER JOIN
      - lookup           : LEFT JOIN com colunas selecionadas
      - aggregator       : GROUP BY + agregacoes (SUM/AVG/COUNT/MAX/MIN)
      - deduplication    : ROW_NUMBER() + filtro
      - union            : UNION ALL [BY NAME]
      - pivot             : SUM/COUNT/AVG/MAX/MIN(CASE WHEN ...) (precisa de
                            ``pivot_values`` pre-descobertos no config — caso
                            contrario, gera comentario informando o limite).
      - unpivot           : UNPIVOT nativo do DuckDB
      - text_to_rows      : UNNEST(string_split(...))

    Saidas (output)
      - loadNode          : comentario ``-- TODO: write to <connection>``;
                            o ultimo SELECT do script materializa os dados
                            que seriam gravados.

Nos da Fase 2-3 — sort, sample, record_id, union, pivot, unpivot e
text_to_rows — estao TODOS na cobertura V1.

Nos NAO suportados em V1:
  - code, http_request, webhook, polling, notification, dead_letter,
    bulk_insert, composite_insert, truncate_table, if_node, switch_node,
    loop, sub_workflow, assert, manual, cron, csv_input, excel_input,
    api_input, extractNode, sql_script, math, transformNode e qualquer
    node_type ausente em ``NODE_EXECUTION_PROFILE`` ou marcado como
    ``shape='control'``.
"""

from app.services.workflow.exporters.errors import UnsupportedNodeError
from app.services.workflow.exporters.python_exporter import PythonExporter
from app.services.workflow.exporters.sql_exporter import SQLExporter

__all__ = ["SQLExporter", "PythonExporter", "UnsupportedNodeError"]
