# Exportação e importação de workflows

A partir da Fase 9, todo workflow do Shift pode ser exportado em três
formatos standalone — útil para auditoria, debug local e versionamento em
git — e importado de volta a partir de YAML.

## Formatos suportados

| Formato | Extensão | Quando usar                                              |
|---------|----------|----------------------------------------------------------|
| SQL     | `.sql`   | Auditar a lógica do fluxo direto no DuckDB CLI.          |
| Python  | `.py`    | Reproduzir o fluxo num ambiente fora do Shift.           |
| YAML    | `.yaml`  | Versionar em git e re-importar em outro workspace.       |

> Os formatos **SQL** e **Python** são *somente leitura* — não há `import`
> equivalente. Para round-trip, use **YAML**.

## Como exportar pelo editor

1. No canto superior direito do editor de workflows, clique no menu
   **⋯ (mais ações)**.
2. Escolha um dos quatro formatos:
   - `Exportar JSON (canvas)` — formato legado, restaura o canvas.
   - `Exportar SQL (DuckDB)` — script `.sql` standalone.
   - `Exportar Python` — script `.py` que usa `duckdb` direto.
   - `Exportar YAML` — formato versionável.
3. O download começa imediatamente. O nome do arquivo segue o slug do
   workflow (ex.: `order-enrichment.sql`).

Se o workflow contiver nós sem suporte na V1 (`code`, `http_request`,
`if_node`, etc.), o backend devolve **HTTP 422** e o editor mostra um
modal listando cada `node_id` com a razão. Clicar em um item seleciona o
nó correspondente no canvas.

## Variáveis e conexões

Ambos os exportadores **não pré-resolvem** `{{vars.X}}`. As variáveis
viram placeholders shell-style (`${X}`) declarados no cabeçalho:

```sql
-- Variables — replace ${PLACEHOLDER} before running:
--   ${CUTOFF_DATE}   used in: extract_orders
```

Conexões (`connection_id`) também são deixadas como TODO — substitua o
ATTACH no header pelo seu URL real:

```sql
-- Suggested ATTACH (replace credentials & TYPE):
--   ATTACH 'postgres://USER:PASS@HOST:PORT/DB' AS conn_<id> (TYPE POSTGRES, READ_ONLY);
```

Para o exportador Python, a substituição é via `os.environ`:

```python
CUTOFF_DATE = os.environ['CUTOFF_DATE']
CONN_11111111_URL = os.environ.get('CONN_11111111_URL', 'postgresql://USER:PASS@HOST:PORT/DB')
```

## Cobertura V1

Esses 16 tipos de nó são exportáveis para SQL e Python:

- **Entradas:** `sql_database`, `inline_data`
- **Narrow:** `filter`, `mapper`, `record_id`, `sample`, `sort`
- **Wide:** `join`, `lookup`, `aggregator`, `deduplication`, `union`,
  `pivot`, `unpivot`, `text_to_rows`
- **Saída:** `loadNode` (gerado como comentário `-- TODO: write to ...`)

Tipos **não suportados** em V1 (devolvem HTTP 422):

- Código arbitrário: `code`
- I/O externa: `http_request`, `webhook`, `polling`, `csv_input`,
  `excel_input`, `api_input`, `extractNode`, `sql_script`
- Efeitos colaterais: `bulk_insert`, `composite_insert`,
  `truncate_table`, `notification`, `dead_letter`
- Controle de fluxo: `if_node`, `switch_node`, `loop`, `assert`,
  `call_workflow`, `manual`, `cron`
- Aritmética legada: `math`, `transformNode`

## Rodando o SQL exportado

O cabeçalho documenta a invocação. Após substituir variáveis e o
`ATTACH`:

```bash
duckdb < order_enrichment.sql
```

Cada nó vira uma `TEMPORARY TABLE`; o `SELECT *` final imprime o
resultado do(s) terminal(is) — o nó upstream do `loadNode`, se existir.

## Rodando o Python exportado

```bash
pip install duckdb sqlalchemy
export CUTOFF_DATE=2026-01-01
export CONN_11111111_URL='postgresql://user:pass@host/db'
python order_enrichment.py
```

O script:
1. Conecta ao DuckDB em memória.
2. Faz `ATTACH` de cada conexão configurada por `os.environ`.
3. Cria uma `TEMPORARY TABLE` por nó na ordem topológica.
4. Imprime o(s) DataFrame(s) terminal(is) via `pandas`.

## Importando YAML

```text
POST /api/v1/workflows/import?workspace_id=<uuid>
Content-Type: multipart/form-data
file: <arquivo.yaml>
```

O backend valida o `shift_version` (rejeita major incompatível), extrai
`nodes`/`edges`/`variables` e cria um workflow draft no workspace
informado. O `workflow_id` original do YAML é descartado (sempre se
gera um UUID novo).

Pelo editor, use **⋯ → Importar YAML**. Após sucesso, o navegador é
redirecionado para o novo fluxo.

## Estrutura do YAML

```yaml
shift_version: '1.0'
workflow_id: 11111111-2222-3333-4444-555555555555
workflow_name: order_enrichment
exported_at: 2026-04-29T12:00:00+00:00
settings:
  variables:
    - name: CUTOFF_DATE
      type: string
      required: true
  schedule: null
  meta: null
nodes:
  - id: extract_orders
    type: sql_database
    position: { x: 0, y: 100 }
    inputs: []
    outputs: [filter_recent]
    config:
      type: sql_database
      connection_id: 11111111-2222-3333-4444-555555555555
      query: "SELECT * FROM orders WHERE created_at > '{{vars.CUTOFF_DATE}}'"
edges:
  - id: e1
    source: extract_orders
    target: filter_recent
    sourceHandle: null
    targetHandle: input
```

> Os campos `inputs` e `outputs` em cada nó são derivados das `edges`
> apenas para legibilidade — o parser ignora esses campos ao reconstruir
> o workflow (única fonte de verdade são as `edges`).

## Comportamento de erro (HTTP 422)

```json
{
  "detail": {
    "error": "Cannot export workflow: 2 unsupported nodes.",
    "unsupported": [
      {
        "node_id": "ai_extractor",
        "node_type": "code",
        "reason": "transformacao 'code' nao suportada em V1"
      },
      {
        "node_id": "branch_1",
        "node_type": "if_node",
        "reason": "controle de fluxo nao e exportavel em V1"
      }
    ]
  }
}
```

## Limitações conhecidas

- O exportador SQL **não** descobre os valores únicos da coluna pivot
  em build-time — o script gerado usa `PIVOT ... ON <col> USING SUM(...)`
  do DuckDB, que descobre os valores em runtime. Os nomes das colunas
  resultantes seguem o padrão `<valor>_<agg>`.
- O `unpivot` exportado **exige** `value_columns` explícito; `by_type`
  (descoberta por tipo) não é suportada porque depende do schema em
  runtime.
- Workflows com ciclos não são exportáveis — o exportador faz
  ordenação topológica e levanta erro se houver ciclo.
