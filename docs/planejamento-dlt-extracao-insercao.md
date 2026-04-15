# Planejamento: Padronização com dlt para Extração e Inserção

> **Escopo**: Usar dlt como engine padrão para **leitura de dados (extração)** e **escrita de dados (inserção/carga)** em todo o Shift.
>
> **Fora de escopo**: Transformações (mapper, filter, aggregator, etc.) continuam in-memory com Python/DuckDB.

---

## 1. Estado Atual

### 1.1 O que já temos

| Componente | Usa dlt? | Onde |
|---|---|---|
| Extração SQL (produção) | ✅ Sim | `data_pipelines/sql_extractor.py` — `@dlt.resource` + streaming SQLAlchemy → DuckDB temp |
| Carga/Load (produção) | ⚠️ Parcial | `data_pipelines/migrator.py` — dlt para Postgres/MySQL/MSSQL; fallback SQLAlchemy para Oracle/Firebird |
| Extração SQL (teste inline) | ❌ Não | `workflow_test_service.py` → `_exec_sql_database()` usa SQLAlchemy puro |
| Bulk Insert (teste inline) | ❌ Não | `workflow_test_service.py` → `_exec_bulk_insert()` usa SQLAlchemy puro |
| Load Node (teste inline) | ❌ Não | `workflow_test_service.py` → `_exec_load_node()` usa SQLAlchemy puro |
| Truncate Table (teste inline) | ❌ Não | `workflow_test_service.py` → `_exec_truncate_table()` usa SQLAlchemy puro |

### 1.2 Dependência

```toml
# pyproject.toml — já instalado
dlt[postgres]>=1.4,<2.0
```

### 1.3 Bancos suportados

| Banco | Driver SQLAlchemy | dlt destination | Status dlt |
|---|---|---|---|
| PostgreSQL | `postgresql+psycopg2` | `dlt.destinations.postgres` | ✅ Funciona |
| MySQL | `mysql+pymysql` | `dlt.destinations.mysql` | ✅ Funciona |
| SQL Server | `mssql+pyodbc` | `dlt.destinations.mssql` | ✅ Funciona |
| Oracle | `oracle+oracledb` | `dlt.destinations.sqlalchemy` | ⚠️ Bug ORA-00932 com CLOB em `_dlt_pipeline_state` |
| Firebird | `firebird+firebird` | — | ❌ Sem suporte nativo no dlt |

### 1.4 Bug conhecido: Oracle + dlt

O dlt cria tabelas de controle internas (`_dlt_pipeline_state`, `_dlt_loads`, etc.) que usam colunas TEXT/CLOB. Oracle rejeita operações de comparação em CLOB, gerando `ORA-00932`. Hoje o workaround é usar SQLAlchemy puro para Oracle e Firebird.

---

## 2. Arquitetura Proposta

### 2.1 Visão geral

```
┌─────────────────────────────────────────────────────────┐
│                    Workflow Engine                       │
│                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────┐  │
│  │  Nó Extração │    │  Nós Transf. │    │ Nó Carga  │  │
│  │  (SQL, CSV,  │───▶│  (mapper,    │───▶│ (load,    │  │
│  │   API, etc.) │    │   filter...) │    │  bulk ins) │  │
│  └──────┬───────┘    └──────────────┘    └─────┬─────┘  │
│         │                                      │        │
│         ▼                                      ▼        │
│  ┌──────────────┐                      ┌──────────────┐ │
│  │ dlt Extract  │                      │  dlt Load    │ │
│  │   Service    │                      │   Service    │ │
│  └──────┬───────┘                      └──────┬───────┘ │
│         │                                      │        │
│         ▼                                      ▼        │
│  ┌──────────────┐                      ┌──────────────┐ │
│  │  DuckDB temp │  ← staging area →   │  Banco dest. │ │
│  │  (rows[])    │                      │  (Oracle,    │ │
│  │              │                      │   Postgres…) │ │
│  └──────────────┘                      └──────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Princípios

1. **Um serviço de extração, um de carga** — toda leitura e escrita passa por esses dois módulos
2. **Modo produção e teste usam o mesmo código** — eliminar duplicação entre `workflow_test_service.py` e `data_pipelines/`
3. **Oracle/Firebird: fallback inteligente** — dlt quando possível, SQLAlchemy quando necessário, decisão automática
4. **Type casting centralizado** — introspecção da tabela destino antes da escrita, conversão automática de tipos
5. **DuckDB como staging universal** — extração sempre materializa em DuckDB; carga sempre lê de DuckDB ou rows[]

---

## 3. Tarefas de Implementação

### Fase 1 — Serviço unificado de Extração

**Objetivo**: Um módulo `extraction_service.py` que serve tanto o modo teste quanto produção.

#### Tarefa 1.1: Criar `app/services/extraction_service.py`

```python
# Assinatura proposta
class ExtractionService:
    async def extract_sql(
        self,
        connection_id: str,
        query: str,
        *,
        max_rows: int = 200,          # limite para modo teste
        chunk_size: int = 1000,
        conn_map: dict[str, Connection] | None = None,
    ) -> ExtractionResult:
        """
        Extrai dados SQL usando dlt resource com streaming.
        Retorna ExtractionResult com rows[], columns[], row_count.

        Para modo teste: retorna rows[] em memória (limitado a max_rows).
        Para modo produção: materializa em DuckDB temp e retorna referência.
        """

    async def extract_csv(self, url: str, **opts) -> ExtractionResult: ...
    async def extract_api(self, url: str, **opts) -> ExtractionResult: ...
    async def extract_excel(self, url: str, **opts) -> ExtractionResult: ...
```

**Detalhes**:
- Reutiliza pattern do `sql_extractor.py` (streaming + `@dlt.resource`)
- Para Firebird: mantém driver dedicado (`firebird_client.py`), mas wrappa resultado como `@dlt.resource`
- Normalização de driver async → sync já existe em `sql_extractor.py`, reutilizar
- `ExtractionResult` é um dataclass com `rows`, `columns`, `row_count`, e opcionalmente `duckdb_path`

#### Tarefa 1.2: Migrar `workflow_test_service._exec_sql_database()` para usar `ExtractionService`

- Substituir o bloco SQLAlchemy puro por chamada ao `extraction_service.extract_sql()`
- Manter a interface de retorno `{"row_count": N, "columns": [...], "rows": [...]}`
- Remover funções auxiliares `_exec_sa()` e `_exec_firebird()` após migração

#### Tarefa 1.3: Migrar nó de produção `workflow/nodes/sql_database.py`

- Substituir chamada direta a `extract_sql_to_duckdb()` por `extraction_service.extract_sql(mode="production")`
- Manter compatibilidade com `duckdb_storage.py` para staging

**Estimativa**: Média complexidade. Base já existe em `sql_extractor.py`.

---

### Fase 2 — Serviço unificado de Carga

**Objetivo**: Um módulo `load_service.py` que serve bulk_insert, load_node e truncate_table.

#### Tarefa 2.1: Criar `app/services/load_service.py`

```python
class LoadService:
    async def insert(
        self,
        connection_id: str,
        target_table: str,
        rows: list[dict],
        *,
        column_mapping: list[dict] | None = None,
        write_disposition: str = "append",  # append | replace | merge
        merge_key: list[str] | None = None,
        batch_size: int = 1000,
        conn_map: dict[str, Connection] | None = None,
    ) -> LoadResult:
        """
        Insere dados na tabela destino.

        Fluxo:
        1. Resolve connection_id → connection_string
        2. Introspecção da tabela destino (tipos das colunas)
        3. Aplica column_mapping (se fornecido)
        4. Cast de tipos (string→number, string→date, etc.)
        5. Escolhe estratégia:
           - dlt pipeline (Postgres, MySQL, MSSQL)
           - SQLAlchemy direto (Oracle, Firebird)
        6. Insere em batches com tracking de progresso
        7. Retorna LoadResult com rows_written, erros, warnings
        """

    async def truncate(
        self,
        connection_id: str,
        target_table: str,
        *,
        mode: str = "truncate",      # truncate | delete
        where_clause: str | None = None,
        conn_map: dict[str, Connection] | None = None,
    ) -> TruncateResult: ...
```

#### Tarefa 2.2: Implementar escolha automática dlt vs SQLAlchemy

```python
def _choose_loader(connection_string: str) -> Literal["dlt", "sqlalchemy"]:
    """
    Oracle e Firebird → sqlalchemy (bug ORA-00932)
    Tudo mais → dlt
    """
    cs = connection_string.lower()
    if cs.startswith(("oracle", "firebird")):
        return "sqlalchemy"
    return "dlt"
```

#### Tarefa 2.3: Implementar introspecção + type casting centralizado

Já temos `_cast_for_db()` no `workflow_test_service.py`. Mover para o `load_service.py` como lógica central:

```python
def _introspect_and_cast(
    engine: sa.Engine,
    target_table: str,
    rows: list[dict],
    column_mapping: list[dict] | None,
) -> list[dict]:
    """
    1. inspector.get_columns() → mapa coluna→tipo
    2. Aplica column_mapping (renomeia source→target)
    3. Itera cada valor e converte:
       - String numérica → float/int (para NUMBER, DECIMAL, etc.)
       - String data → datetime (para DATE, TIMESTAMP, etc.)
       - Número → str (para VARCHAR, CHAR, etc.)
       - String vazia → None (para campos numéricos/data)
    4. Retorna rows convertidos
    """
```

#### Tarefa 2.4: Implementar diagnóstico detalhado de erros

```python
def _insert_with_diagnostics(
    engine: sa.Engine,
    insert_sql: sa.TextClause,
    rows: list[dict],
    batch_size: int,
) -> InsertDiagnostics:
    """
    - Tenta inserir em batch
    - Se batch falha: tenta linha a linha
    - Identifica: número da linha, coluna problemática, valor, tipo esperado
    - Retorna: rows_written, failed_rows (com detalhes), warnings
    """
```

#### Tarefa 2.5: Migrar `workflow_test_service` para usar `LoadService`

Substituir:
- `_exec_bulk_insert()` → `load_service.insert()`
- `_exec_load_node()` / `_exec_load_sa()` → `load_service.insert()`
- `_exec_truncate_table()` → `load_service.truncate()` + `load_service.insert()`

#### Tarefa 2.6: Migrar nó de produção `workflow/nodes/load_node.py`

- Substituir chamada a `run_migration_pipeline()` por `load_service.insert()`
- Manter suporte a merge/upsert
- Manter streaming de DuckDB → destino

#### Tarefa 2.7: Deprecar `data_pipelines/migrator.py`

- Após migração completa, `migrator.py` pode ser removido
- Toda lógica de load/merge vive em `load_service.py`

**Estimativa**: Alta complexidade. É o coração da mudança.

---

### Fase 3 — Melhorias de Monitoramento

#### Tarefa 3.1: Eventos SSE enriquecidos

Adicionar ao streaming SSE durante a carga:

```python
# Evento de progresso por batch
yield sse({
    "type": "node_progress",
    "node_id": node_id,
    "rows_written": rows_so_far,
    "total_rows": total,
    "batch_number": batch_idx,
    "timestamp": _ts(),
})
```

#### Tarefa 3.2: Output enriquecido nos nós de carga

```python
# Retorno do nó de inserção
{
    "status": "success",
    "rows_written": 200,
    "target_table": "VIASOFTMCP.IMPPESSOA",
    "column_types": {              # tipos detectados via introspecção
        "IDPESS": "NUMBER",
        "NOME": "VARCHAR2",
        "DTCADASTRO": "DATE",
        "RENDA": "NUMBER",
    },
    "cast_summary": {              # quantos valores foram convertidos
        "string_to_number": 600,
        "string_to_date": 400,
        "null_coerced": 15,
    },
    "duration_ms": 1234,
    "batches": 1,
}
```

#### Tarefa 3.3: Log de linhas rejeitadas

```python
# Se uma linha falha, armazenar em campo separado
{
    "rejected_rows": [
        {
            "row_number": 42,
            "error": "ORA-01722: número inválido",
            "column": "RENDA",
            "value": "N/A",
            "expected_type": "NUMBER",
        }
    ]
}
```

---

## 4. Decisões Técnicas

### 4.1 dlt Resource Pattern (Extração)

```python
@dlt.resource(name="source_data", write_disposition="replace")
def _stream_rows(engine, query, chunk_size, max_rows):
    with engine.connect().execution_options(stream_results=True) as conn:
        result = conn.execute(sa.text(query))
        total = 0
        while True:
            chunk = result.mappings().fetchmany(chunk_size)
            if not chunk:
                break
            for row in chunk:
                yield dict(row)
                total += 1
                if max_rows and total >= max_rows:
                    return
```

### 4.2 dlt Pipeline Pattern (Carga)

```python
# Para bancos compatíveis (Postgres, MySQL, MSSQL)
pipeline = dlt.pipeline(
    pipeline_name=f"load_{uuid4().hex[:8]}",
    destination=_resolve_dlt_destination(conn_str),
    dataset_name=schema_name or "public",
)

@dlt.resource(name=table_name, write_disposition=disposition)
def _data():
    yield from cast_rows

load_info = pipeline.run(_data())
```

### 4.3 SQLAlchemy Pattern (Oracle/Firebird)

```python
# Para Oracle e Firebird (sem dlt)
inspector = sa.inspect(engine)
col_types = {c["name"]: c["type"] for c in inspector.get_columns(table)}
cast_rows = [_cast_row(row, col_types) for row in rows]

with engine.begin() as conn:
    for batch in chunked(cast_rows, batch_size):
        try:
            conn.execute(insert_sql, batch)
        except Exception:
            _insert_row_by_row_with_diagnostics(conn, insert_sql, batch)
```

### 4.4 Quando usar dlt vs SQLAlchemy direto

```
                    ┌─────────────────┐
                    │  É Oracle ou    │
                    │  Firebird?      │
                    └────┬───────┬────┘
                         │       │
                        Sim     Não
                         │       │
                         ▼       ▼
                  ┌──────────┐ ┌──────────┐
                  │SQLAlchemy│ │   dlt     │
                  │  direto  │ │ pipeline  │
                  └──────────┘ └──────────┘
```

> **Nota**: Monitorar releases do dlt. Quando o bug ORA-00932 for corrigido, remover o fallback e usar dlt para todos os bancos.

---

## 5. Estrutura de Arquivos (Após migração)

```
shift-backend/app/
├── services/
│   ├── extraction_service.py    ← NOVO: extração unificada
│   ├── load_service.py          ← NOVO: carga unificada
│   ├── connection_service.py    (sem mudança)
│   ├── workflow_test_service.py (simplificado — delega para extraction/load)
│   └── workflow/
│       └── nodes/
│           ├── sql_database.py  (simplificado — delega para extraction_service)
│           └── load_node.py     (simplificado — delega para load_service)
├── data_pipelines/
│   ├── sql_extractor.py         ← DEPRECAR (absorvido por extraction_service)
│   ├── migrator.py              ← DEPRECAR (absorvido por load_service)
│   └── duckdb_storage.py        (sem mudança — staging continua)
```

---

## 6. Ordem de Execução Sugerida

| Ordem | Tarefa | Impacto | Risco |
|---|---|---|---|
| 1 | **2.3** Introspect + cast centralizado | Alto — resolve ORA-01722 imediatamente | Baixo |
| 2 | **2.1** Criar `load_service.py` | Alto — base para toda carga | Médio |
| 3 | **2.2** Escolha automática dlt vs SA | Médio — estratégia de roteamento | Baixo |
| 4 | **2.5** Migrar test_service para load_service | Alto — elimina duplicação | Médio |
| 5 | **1.1** Criar `extraction_service.py` | Médio — base para toda extração | Baixo |
| 6 | **1.2** Migrar test_service para extraction_service | Médio — elimina duplicação | Baixo |
| 7 | **3.1-3.3** Monitoramento enriquecido | Médio — visibilidade | Baixo |
| 8 | **2.6-2.7** Migrar nós produção + deprecar migrator | Alto — limpeza final | Médio |

---

## 7. Riscos e Mitigações

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Bug dlt com Oracle CLOB (`ORA-00932`) | Confirmado | Fallback SQLAlchemy automático; monitorar changelog do dlt |
| Firebird sem suporte dlt nativo | Confirmado | Sempre usa SQLAlchemy direto; dlt só para staging DuckDB |
| Regressão no modo teste ao migrar | Médio | Manter testes E2E; implementar gradualmente (nó a nó) |
| Performance: introspecção adiciona latência | Baixo | Cache de tipos por tabela durante a execução (1 inspect por tabela) |
| Tipos incompatíveis entre bancos (ex: Firebird→Oracle) | Médio | Cast centralizado com fallback tolerante; log de warnings sem bloquear |

---

## 8. Extras dlt disponíveis

| Recurso dlt | Aplicação no Shift | Prioridade |
|---|---|---|
| **Schema inference** | Detectar tipos automaticamente na extração | Fase 1 |
| **Write dispositions** (append, replace, merge) | Já usado no migrator; padronizar | Fase 2 |
| **State management** | Cargas incrementais (last_value) | Futuro |
| **Retry/backoff** | Resiliência em cargas grandes | Futuro |
| **Normalização** | Flatten de JSON aninhado | Futuro |
| **Destinations cloud** (BigQuery, Snowflake, Redshift) | Expandir destinos suportados | Futuro |
