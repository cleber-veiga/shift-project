# Prompt — Fase 9: Code Export (workflow → SQL/Python/YAML)

Use este arquivo como instrução completa para um agente de IA. Auto-contido —
ele não precisa de contexto adicional além dos arquivos do repo.

---

## Estado atual do projeto (após Fases 1-5)

Antes de começar, leia para se orientar:

- `docs/flowfile-implementation-plan.md` — plano geral; sua tarefa é **só a Fase 9**.
- `docs/review-fixes-fases-1-5.md` — correções aplicadas. Use como referência das
  convenções atuais.
- `shift-backend/app/orchestration/flows/node_profile.py` — **NODE_EXECUTION_PROFILE**:
  classifica cada `node_type` por `shape` (narrow/wide/io/output/control). Você vai
  usar isso para decidir o que é exportável.
- `shift-backend/app/orchestration/flows/parameter_resolver.py` — como `${var}` é
  resolvido em runtime.
- `shift-backend/app/services/workflow/semantic_hash.py` — fingerprint de configs.
- `shift-backend/app/services/workflow/schema_inference/__init__.py` — schema preview.
- `shift-backend/app/services/workflow/nodes/{filter,mapper,join,lookup,aggregator,deduplication,sort,sample,record_id,union,pivot,unpivot,text_to_rows}_node.py`
  — implementações de referência. **TODOS são DuckDB-first**.
- `shift-backend/app/orchestration/flows/dynamic_runner.py` — topological sort
  já existe; reuse `_topological_sort_levels` e `_build_graph`.

## Princípios não-negociáveis

1. **Shift NÃO usa Prefect.** Não invoque, não importe, não documente como se usasse.
2. **DuckDB-first.** Export gera SQL DuckDB ou Python que usa `duckdb` direto. Não
   gere Polars como engine de execução do export.
3. **Pydantic v2, Next.js 16, React 19, shadcn/ui.**
4. **Todos os ~245 testes existentes continuam passando** após suas mudanças.
5. **Cada artefato novo tem teste novo** — incluindo snapshot de output.
6. **Comente o "porquê", não o "como".** Sem docstrings elogiosas.
7. **NÃO copie literalmente** o `code_generator/code_generator.py` do Flowfile —
   ele gera Polars. Use só como referência **estrutural** (dispatch por node_type,
   topological order, lista de unsupported, separação de exporters).

## Visão geral da Fase 9

Workflow → exportador → 3 formatos:

1. **SQL** standalone (DuckDB CLI/script — para auditoria e debug local).
2. **Python** standalone (script com `duckdb` + opcional `dlt` para output).
3. **YAML** save format (versionável em git, round-trip import/export).

E endpoints + UI no editor com botão "Export".

---

## Parte 1 — SQL Exporter

### Arquivos novos

- `shift-backend/app/services/workflow/exporters/__init__.py` (módulo)
- `shift-backend/app/services/workflow/exporters/sql_exporter.py`
- `shift-backend/tests/test_sql_exporter.py`
- `shift-backend/tests/snapshots/sql_exporter/` (snapshots como `.sql` files)

### Comportamento

```python
class SQLExporter:
    """Converte WorkflowDefinition em script SQL DuckDB standalone."""

    def export(self, workflow_definition: dict) -> str:
        # 1. _topological_sort_levels (reuse de dynamic_runner)
        # 2. Para cada nó na ordem topológica:
        #    - dispatch handler _handle_{node_type}(node, upstream_refs)
        #    - se não tem handler → adicionar a unsupported_nodes
        # 3. Se unsupported_nodes não-vazio → raise UnsupportedNodeError
        # 4. Concatenar:
        #    - cabeçalho com metadata (workflow_id, exported_at, shift_version)
        #    - declaração de variáveis (${var} → comentário "-- TODO: set X")
        #    - cada bloco SQL com comentário identificando node_id e label
        #    - SELECT final do(s) nó(s) sem outgoing edges (output)
```

### Cobertura V1 (handlers a implementar)

Use **NODE_EXECUTION_PROFILE** como filtro: nós com `shape="control"` são
sempre não-exportáveis em V1. Nós com `shape="output"` exportam como
`CREATE TABLE final` ou comentário `-- output to <destination>`.

**Implementar handlers para:**

- `sql_database` → `WITH {node_id} AS (<query>)` ou variável `:connection_uri`
  no header com comentário "-- Run with: duckdb -cmd ..."
- `filter` → `WHERE` aplicado sobre upstream
- `mapper` → `SELECT` com aliases declarados em `mappings`
- `join` → `INNER/LEFT JOIN ON` conforme `conditions`
- `lookup` → `LEFT JOIN` com SELECT específico das colunas mapeadas
- `aggregator` → `GROUP BY` + funções
- `deduplication` → `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)` + filter
- `sort` → `ORDER BY` (atenção a `nulls_position`)
- `sample` → `LIMIT` (first_n) ou `USING SAMPLE reservoir(N ROWS) REPEATABLE(seed)` (random)
- `record_id` → `ROW_NUMBER() OVER (...)` + offset
- `union` → `UNION ALL BY NAME` ou `UNION ALL`
- `pivot` → `SUM(CASE WHEN ... END)` por valor único pré-descoberto (ler `max_pivot_values`)
- `unpivot` → `UNPIVOT (val FOR var IN (col1, col2))` nativo
- `text_to_rows` → `UNNEST(string_split(col, delim))`
- `loadNode` → comentário `-- TODO: write to <connection>` (sem gerar dlt SQL — só warning)

**NÃO suportar em V1** (adicionar a `unsupported_nodes` com motivo claro):
- `code` (Python arbitrário não vira SQL)
- `http_request`, `webhook`, `polling` (side effect externo)
- `notification`, `dead_letter` (side effect)
- `bulk_insert`, `composite_insert`, `truncate_table` (side effect; só comentário no SQL)
- `if_node`, `switch_node`, `loop`, `sub_workflow` (controle de fluxo)
- `assert` (controle)
- Qualquer node_type com `NODE_EXECUTION_PROFILE[t]["shape"] == "control"` ou
  qualquer node_type ausente em NODE_EXECUTION_PROFILE.

### Tratamento de `${var}`

**Não pré-resolver.** Mantenha placeholders e adicione no header:

```sql
-- Workflow: order_enrichment
-- Exported at: 2026-04-29T...
-- TODO: provide values for the following variables:
--   ${API_URL}        (used in nodes: extract_orders)
--   ${CUTOFF_DATE}    (used in nodes: filter_recent)

-- Node: extract_orders (sql_database)
WITH extract_orders AS (
  SELECT * FROM orders WHERE created_at > '${CUTOFF_DATE}'
),
...
```

### Tratamento de `connection_id`

Resolva o `connection_id` pelo `connection_service` (síncrono se possível) e
gere placeholder no header:

```sql
-- TODO: configure connections
ATTACH 'postgres://USER:PASS@host/db' AS conn_<connection_id_short>;
```

### Erro estruturado para nós não suportados

```python
class UnsupportedNodeError(Exception):
    def __init__(self, unsupported: list[dict]):
        self.unsupported = unsupported  # [{node_id, node_type, reason}, ...]
        super().__init__(
            f"Cannot export workflow: {len(unsupported)} unsupported nodes."
        )
```

API converte para HTTP 422 com body estruturado (ver Parte 4).

### Testes

- Snapshot tests: workflows fixture em `tests/fixtures/workflows/` →
  rodar export → comparar com `tests/snapshots/sql_exporter/<fixture>.sql`.
- Pelo menos 5 fixtures cobrindo:
  - Pipeline linear simples (sql_database → filter → load)
  - Join com lookup
  - Aggregator com group by
  - Pivot + unpivot encadeados
  - Workflow com nó não suportado (deve falhar com lista correta)
- Atualizar snapshots com `pytest --snapshot-update` ou similar (use `syrupy`
  se já está no projeto; senão, comparação string direta).

---

## Parte 2 — Python Exporter

### Arquivos novos

- `shift-backend/app/services/workflow/exporters/python_exporter.py`
- `shift-backend/tests/test_python_exporter.py`
- `shift-backend/tests/snapshots/python_exporter/`

### Comportamento

Mesmo padrão do SQLExporter, mas gera script Python standalone:

```python
"""
Workflow: order_enrichment
Exported from Shift at: 2026-04-29T...

Run:
    pip install duckdb sqlalchemy
    export API_URL=...
    export CUTOFF_DATE=...
    python order_enrichment.py
"""
import os
import duckdb
from sqlalchemy import create_engine

# ── Variables ──
API_URL = os.environ["API_URL"]
CUTOFF_DATE = os.environ["CUTOFF_DATE"]

# ── Connections ──
# TODO: replace with real connection strings
CONN_ORDERS = "postgresql://user:pass@host/db"

def main():
    con = duckdb.connect(":memory:")

    # ── Node: extract_orders (sql_database) ──
    engine = create_engine(CONN_ORDERS)
    df = pd.read_sql(f"SELECT * FROM orders WHERE created_at > '{CUTOFF_DATE}'", engine)
    con.register("extract_orders", df)

    # ── Node: filter_recent (filter) ──
    con.execute("CREATE TABLE filter_recent AS SELECT * FROM extract_orders WHERE ...")

    # ... etc

    # Output
    result = con.execute("SELECT * FROM final_node").fetchdf()
    print(result)

if __name__ == "__main__":
    main()
```

Use **mesma cobertura V1** do SQLExporter. Nós não suportados → mesma
`UnsupportedNodeError`.

### Imports condicionais

Apenas importe o que o workflow específico usa. Se não há `sql_database`,
não importe `sqlalchemy`. Construa lista de imports incrementalmente
durante o dispatch.

### Testes

Snapshot tests + smoke test que roda `python <script>` em subprocess
e verifica exit code 0 (use `tmp_path` e mocks de connection se preciso).

---

## Parte 3 — YAML Serializer

### Arquivos novos

- `shift-backend/app/services/workflow/serializers/yaml_serializer.py`
- `shift-backend/tests/test_yaml_serializer.py`

### Format

```yaml
shift_version: "1.0"
workflow_id: "<uuid>"
workflow_name: "order_enrichment"
exported_at: "2026-04-29T12:00:00Z"
settings:
  variables:
    - name: API_URL
      type: string
      required: true
    - name: CUTOFF_DATE
      type: string
      default: "2025-01-01"
  schedule: null
nodes:
  - id: "extract_orders"
    type: "sql_database"
    position: { x: 0, y: 100 }
    inputs: []
    outputs: ["filter_recent"]
    config:
      connection_id: "<uuid>"
      query: "SELECT * FROM orders WHERE created_at > '${CUTOFF_DATE}'"
  - id: "filter_recent"
    type: "filter"
    position: { x: 200, y: 100 }
    inputs: ["extract_orders"]
    outputs: ["enrich_customer"]
    config:
      condition: "amount > 100"
edges:
  - source: "extract_orders"
    target: "filter_recent"
    sourceHandle: "success"
    targetHandle: "input"
```

### Funções

```python
def to_yaml(workflow_definition: dict) -> str: ...
def from_yaml(yaml_str: str) -> dict: ...
```

Use `yaml.safe_dump` com `sort_keys=False`, `default_flow_style=False`,
`allow_unicode=True`. Use `yaml.safe_load` para parse.

### Round-trip preservation

`from_yaml(to_yaml(d))` deve retornar `d` (deep equality), inclusive campos
de extensão (`pinnedOutput`, `enabled`, etc). Use snapshot tests.

### Testes

- Round-trip fuzzing: 20 fixtures de workflows variados.
- Versionamento: detectar `shift_version` ausente ou diferente; warning
  (não erro) quando minor diff, erro quando major.
- Validação de schema obrigatório: `shift_version`, `nodes`, `edges`.

---

## Parte 4 — Endpoints API

### Arquivos modificados

- `shift-backend/app/api/v1/workflows.py` — adicionar endpoints.
- `shift-backend/tests/test_workflow_export_api.py` (novo).

### Endpoint export

```python
@router.post("/{workflow_id}/export")
async def export_workflow(
    workflow_id: UUID,
    format: Literal["sql", "python", "yaml"] = Query(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> Response:
    """Exporta workflow para formato standalone.

    Retorna 422 com lista estruturada se houver nós não suportados.
    """
    ...
    # Headers:
    # Content-Type: text/plain (sql), text/x-python (python), text/yaml (yaml)
    # Content-Disposition: attachment; filename="<workflow_name>.<ext>"
```

Body de erro 422:

```json
{
  "error": "Cannot export workflow: 3 unsupported nodes.",
  "unsupported": [
    {"node_id": "ai_1", "node_type": "code", "reason": "arbitrary Python script"},
    {"node_id": "http_3", "node_type": "http_request", "reason": "external side effect"},
    {"node_id": "if_1", "node_type": "if_node", "reason": "control flow not supported in V1"}
  ]
}
```

### Endpoint import (YAML only por enquanto)

```python
@router.post("/import")
async def import_workflow(
    file: UploadFile = File(...),
    workspace_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> dict:
    """Cria novo workflow draft a partir de YAML."""
    # Valida content-type / extensão.
    # Parse YAML.
    # Validar shift_version compatível.
    # Criar Workflow row com definition do YAML.
    # Retornar { workflow_id, name, status: "draft" }.
```

### Testes

- Export 200: cada formato retorna content-type correto e body não-vazio.
- Export 422: workflow com nó não suportado retorna body estruturado.
- Import 200: YAML válido cria workflow.
- Import 400: YAML malformado, version incompatível, schema ausente.
- Auth: usuário sem permissão retorna 403.

---

## Parte 5 — Frontend

### Arquivos modificados

- `shift-frontend/components/workflow/workflow-editor.tsx` — botão "Export".
- `shift-frontend/components/workflow/export-menu.tsx` (novo) — DropdownMenu shadcn/ui.
- `shift-frontend/components/workflow/import-modal.tsx` (novo).
- `shift-frontend/lib/auth.ts` — funções de fetch.

### Botão Export

DropdownMenu com 3 opções (SQL, Python, YAML). Cada opção:

```ts
async function downloadExport(workflowId: string, format: 'sql' | 'python' | 'yaml') {
  const res = await fetch(`/api/v1/workflows/${workflowId}/export?format=${format}`, {
    method: 'POST',
    credentials: 'include',
  })
  if (res.status === 422) {
    const body = await res.json()
    showToast(`Não foi possível exportar: ${body.unsupported.length} nós não suportados`)
    showUnsupportedDialog(body.unsupported)
    return
  }
  if (!res.ok) {
    showToast('Erro ao exportar')
    return
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = res.headers.get('Content-Disposition')?.match(/filename="(.+)"/)?.[1] || 'export'
  a.click()
  URL.revokeObjectURL(url)
}
```

### Modal de unsupported

Quando 422, mostrar lista com `node_id`, `node_type` e `reason`. Permitir
clicar em cada item para focar o nó no canvas (use `setNodes` + viewport
move se já tem mecanismo).

### Modal Import

Input de arquivo `.yaml`, parse client-side opcional para preview, POST
para `/api/v1/workflows/import`. Após sucesso, redirect para
`/projeto/.../workflows/{novo_id}`.

### Não esquecer

- Atualizar `shift-frontend/components/workflow/workflow-toolbar.tsx` se o
  botão entrar lá.
- Tipo `WorkflowExportFormat` em `shift-frontend/lib/workflow/types.ts`.

---

## Critério de aceite (verificável)

- [ ] `pytest shift-backend/tests/` — todos os ~245 + os novos passam.
- [ ] `npm run build` no shift-frontend/ compila.
- [ ] `npm run lint` no shift-frontend/ passa.
- [ ] **Smoke test SQL:** workflow fixture com 8 nós suportados (sql_database,
  filter, mapper, join, aggregator, sort, deduplication, load) →
  `sql_exporter.export(...)` produz string que roda no `duckdb` CLI sem
  erro de sintaxe (testar via `duckdb -c "<output>"` em subprocess; tolerar
  erros de connection mas não de parse).
- [ ] **Smoke test Python:** workflow fixture exporta → `python <script>`
  retorna exit code 0 (com mocks/conn vazia, ok).
- [ ] **Round-trip YAML:** 20 fixtures variadas — `from_yaml(to_yaml(w)) == w`
  (deep equal, ignore campos voláteis como `exported_at`).
- [ ] **422 estruturado:** workflow com `code` ou `http_request` retorna
  422 com lista correta.
- [ ] **Auth:** usuário sem permissão recebe 403.
- [ ] **Cobertura V1 declarada explicitamente** em docstring do módulo
  exporters/__init__.py — lista node_types suportados, com note sobre os
  novos nós da Fase 2-3 (sort, sample, record_id, union, pivot, unpivot,
  text_to_rows) incluídos.
- [ ] Documentação em `docs/users/export-and-import.md` com exemplos dos 3
  formatos e como rodar SQL/Python gerados.

---

## NÃO fazer

- Não copiar Polars do `code_generator/code_generator.py` do Flowfile.
  Use só como referência estrutural (dispatch por type, ordenação, separação).
- Não tentar fazer V2 (cobertura completa). V1 cobre 15 node_types listados;
  resto é UnsupportedNodeError.
- Não pré-resolver `${var}` no export SQL/Python. Mantenha placeholder e
  declare no header.
- Não introduzir novas dependências sem justificar (yaml, syrupy se não
  estiver no projeto, etc).
- Não criar arquivo `events.py` em events.py se não existe — a Fase 1
  resolveu inline em `workflow_test_service.py`. Mantenha consistência.
- Não silenciar testes ao implementar — se algum teste existente falhar
  por causa do seu trabalho, corrija a causa. Não classifique como
  "pré-existente" sem confirmar via `git stash`.
- Não regredir o que já foi feito nas Fases 1-5. Se for tocar
  `dynamic_runner.py` ou `workflow_test_service.py`, justifique no PR.

---

## Estimativa

- Parte 1 (SQL Exporter): 2 dias
- Parte 2 (Python Exporter): 1 dia
- Parte 3 (YAML Serializer): 1 dia
- Parte 4 (Endpoints): 0.5 dia
- Parte 5 (Frontend): 1.5 dias
- Testes + docs: 1 dia
- **Total: 7 dias**

Sonnet 4.6 high-effort dá conta sozinho. Não é uma fase que precisa de Opus
— bem-bounded, mecânica, sem concorrência.

---

## Referências de código

Para inspiração estrutural (NÃO copiar literalmente):

- `D:\Labs\Flowfile\flowfile_core\flowfile_core\flowfile\code_generator\code_generator.py`
  (~2090 linhas, single file). Veja:
  - método `convert()` que faz topological sort + dispatch.
  - função `determine_execution_order()`.
  - lista `unsupported_nodes` acumulada.
  - separação `FlowGraphToPolarsConverter` vs `FlowGraphToFlowFrameConverter` —
    inspira nossa separação `SQLExporter` vs `PythonExporter`.
- `D:\Labs\Flowfile\data\templates\flows\order_enrichment.yaml` — referência
  do format YAML.
