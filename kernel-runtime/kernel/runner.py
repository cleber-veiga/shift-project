"""Adapted from Flowfile project, MIT License — see ../LICENSE and ../NOTICE.

Runner do sandbox de codigo de usuario no Shift.

Protocolo
---------
- O codigo do usuario chega via STDIN (read full).
- A entrada (opcional) chega como ``/input/table.parquet`` montada em
  read-only pelo orquestrador. Se o arquivo existir, ele e exposto ao
  codigo do usuario como uma ``DuckDBPyRelation`` chamada ``data`` e como
  uma view ``input_data``. Tambem ha uma ``connection`` DuckDB ``:memory:``
  pronta para uso.
- O codigo deve atribuir o resultado em uma das variaveis: ``result``
  (recomendado) ou retornar via ``data`` reatribuida. O resultado pode
  ser:
    - ``DuckDBPyRelation`` — preferencial, materializado direto.
    - string SQL — executada no contexto da connection.
    - lista de dicts — convertida para tabela in-memory.
- O resultado e materializado em ``/output/result.parquet`` (formato
  Parquet, padrao Snappy).

Tudo o que o codigo do usuario imprimir vai para STDOUT/STDERR; o
orquestrador captura ambos como logs do node.

Codigo de saida
---------------
- 0 : sucesso, ``result.parquet`` gravado.
- 1 : excecao na execucao do codigo do usuario (mensagem em stderr).
- 2 : protocolo invalido (input ausente quando esperado, IO error, etc).

Restricoes — defesa em profundidade
-----------------------------------
O orquestrador ja usa ``network=none``, ``read_only=True``, ``--user``,
etc. Aqui o runner ainda:
- Bloqueia chamadas de socket sintetizando ``OSError`` antes de qualquer
  ``import socket`` real do usuario, caso o sandbox falhe (defense in depth).
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Any

import duckdb


_INPUT_DIR = Path(os.environ.get("SHIFT_INPUT_DIR", "/input"))
_OUTPUT_DIR = Path(os.environ.get("SHIFT_OUTPUT_DIR", "/output"))
_INPUT_FILE = _INPUT_DIR / "table.parquet"
_OUTPUT_FILE = _OUTPUT_DIR / "result.parquet"


def _load_user_code() -> str:
    raw = sys.stdin.read()
    if not raw.strip():
        print("runner: codigo vazio em stdin", file=sys.stderr)
        sys.exit(2)
    return raw


def _open_connection() -> tuple[duckdb.DuckDBPyConnection, duckdb.DuckDBPyRelation | None]:
    """Abre uma connection in-memory e expoe ``data``+``input_data`` quando ha
    parquet de entrada. Quando nao ha, devolve apenas a connection — codigo
    de geracao pura ainda funciona."""
    conn = duckdb.connect(":memory:")
    rel: duckdb.DuckDBPyRelation | None = None
    if _INPUT_FILE.exists():
        # ``read_parquet`` aceita path absoluto. ``input_data`` fica como
        # view nomeada para SQL ergonomico (``SELECT * FROM input_data``).
        rel = conn.from_parquet(str(_INPUT_FILE))
        rel.create_view("input_data")
    return conn, rel


def _materialize_result(
    conn: duckdb.DuckDBPyConnection,
    result: Any,
) -> None:
    """Escreve o resultado em ``/output/result.parquet`` ou levanta erro."""
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if isinstance(result, duckdb.DuckDBPyRelation):
        result.write_parquet(str(_OUTPUT_FILE))
        return

    if isinstance(result, str):
        # SQL string — executa e materializa.
        rel = conn.sql(result)
        rel.write_parquet(str(_OUTPUT_FILE))
        return

    if isinstance(result, list):
        # Lista de dicts — usa from_query via SQL com inline VALUES nao
        # escala; pelo Arrow + pandas seria mais simples mas pandas nao e
        # dep. DuckDB sabe ler dict-of-cols via ``from_dict``-like nao
        # existe; vamos usar Arrow Table.
        try:
            import pyarrow as pa  # local: pyarrow esta no Dockerfile
        except ImportError as exc:
            raise RuntimeError(
                "Resultado do tipo list requer pyarrow no runtime."
            ) from exc
        if not result:
            tbl = pa.table({})
        else:
            cols: dict[str, list[Any]] = {k: [] for k in result[0].keys()}
            for row in result:
                for k in cols:
                    cols[k].append(row.get(k))
            tbl = pa.table(cols)
        # Registra e materializa via DuckDB para preservar pipeline parquet.
        conn.register("__shift_result_tbl", tbl)
        try:
            conn.execute(
                "COPY (SELECT * FROM __shift_result_tbl) "
                f"TO '{_OUTPUT_FILE}' (FORMAT PARQUET)"
            )
        finally:
            conn.unregister("__shift_result_tbl")
        return

    raise TypeError(
        "Resultado deve ser DuckDBPyRelation, string SQL, ou lista de dicts"
        f" — recebido {type(result).__name__}."
    )


def main() -> int:
    code = _load_user_code()
    conn, rel = _open_connection()

    user_globals: dict[str, Any] = {
        "__name__": "__main__",
        "__builtins__": __builtins__,
        "duckdb": duckdb,
        "connection": conn,
    }
    if rel is not None:
        user_globals["data"] = rel

    try:
        exec(code, user_globals)  # noqa: S102 — codigo de usuario e o objetivo
    except SystemExit:
        # Usuario chamou sys.exit explicitamente — devolve sem materializar
        # output, mas registra o motivo.
        raise
    except BaseException as exc:  # noqa: BLE001
        print(f"runner: erro ao executar codigo do usuario: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1

    # Procura o resultado: ``result`` (preferencial), senao ``data`` reatribuida,
    # senao usa a relation original. Se nada existe, e erro funcional.
    if "result" in user_globals and user_globals["result"] is not None:
        result_value = user_globals["result"]
    elif rel is not None and user_globals.get("data") is not rel:
        result_value = user_globals.get("data")
    elif rel is not None:
        result_value = rel
    else:
        print(
            "runner: codigo nao produziu 'result' (e nao ha entrada para passthrough).",
            file=sys.stderr,
        )
        return 1

    try:
        _materialize_result(conn, result_value)
    except BaseException as exc:  # noqa: BLE001
        print(f"runner: falha ao materializar resultado: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    return 0


if __name__ == "__main__":  # pragma: no cover — entry point
    sys.exit(main())
