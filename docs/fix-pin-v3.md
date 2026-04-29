# Prompt — Pin v3: materializar linhas para persistência real

Use este arquivo como instrução completa para um agente de IA. Auto-contido.

---

## Contexto

A funcionalidade "Fixar" (pin) permite ao usuário **congelar** o output de um
nó para que ele não seja re-executado. Útil para trabalhar com dados
intermediários sem precisar bater no banco toda vez. É equivalente ao "Pin"
do n8n.

### O que existe hoje

**Pin v1 (pré-Fase 1):** guardava `output` inline em `node.data.pinnedOutput`.
Funcionava porque a SSE carregava `output` completo. Workflows antigos
salvos podem ter pin v1.

**Pin v2 (fix recente):** guarda `{__pinned_v: 2, output, output_reference,
row_count, execution_id}` em `node.data.pinnedOutput`. Restaura o estado para
a UI a partir do `execution_id` chamando `GET /executions/{id}/nodes/{node_id}/preview`.

### Problema com v2

O preview funciona enquanto o **arquivo DuckDB em
`/tmp/shift/executions/{execution_id}/{node_id}.duckdb` existir**. Mas:

- Reinício do backend → `/tmp` é limpo em muitos sistemas → pin some.
- Limpeza periódica do `/tmp` (cron systemd-tmpfiles, restart de container).
- Fechar editor e voltar dias depois → execução antiga foi GC'd.
- Export YAML do workflow para outro ambiente → pin não viaja junto, só a
  referência (que não existe no destino).

Resultado: pin v2 **dá ilusão de persistência** mas quebra silenciosamente.
Não atende o caso de uso real ("fixar para trabalhar com os dados nos
próximos dias / commitar o workflow no git com pin").

### Goal — Pin v3

Materializar as **linhas reais** dentro do `pinnedOutput`, com limite de
tamanho. Pin v3 sobrevive a:

- Reinício do backend.
- Limpeza de `/tmp`.
- Export/import YAML do workflow.
- Compartilhamento do workflow com outro dev.

Equivalente real ao Pin do n8n.

### Princípios não-negociáveis

1. **Shift NÃO usa Prefect.** Não introduzir.
2. **DuckDB-first.** Materialização lê de `DuckdbReference`, não de Polars.
3. **Pydantic v2, Next.js 16, React 19, shadcn/ui.**
4. **Backward compat com pin v1 e v2.** Workflows existentes não podem
   regredir. Reidratação suporta os 3 formatos.
5. **Cada fix tem teste novo** que falha SEM o fix e passa COM.
6. Comente o **porquê**, não o como. Nada de docstrings elogiosas.

### Estado atual relevante (leia antes)

- `shift-frontend/components/workflow/node-config-modal.tsx` — botão "Fixar",
  handler `onPin`, checagem `canPin`.
- `shift-frontend/components/workflow/workflow-editor.tsx` — helper
  `pinnedOutputToState(pinned)` que reidrata pin para `nodeExecStates`.
- `shift-backend/app/api/v1/executions.py` — endpoint `/preview` que já lê
  DuckDB. **Vai ser irmão do novo `/materialize-pin`.**
- `shift-backend/app/orchestration/flows/dynamic_runner.py` — lógica de
  `pinnedOutput` que faz passthrough quando o nó tem pin (busque por
  `pinnedOutput`). **Vai precisar ler `rows` do v3.**
- `shift-backend/app/services/workflow/serializers/yaml_serializer.py` —
  to_yaml/from_yaml. Pin v3 cabe automaticamente em `node.data` mas vamos
  validar round-trip.

---

## Parte 1 — Backend: endpoint `/materialize-pin`

### Arquivo: `shift-backend/app/api/v1/executions.py`

Adicionar novo endpoint, irmão do `/preview`:

```python
@router.post("/executions/{execution_id}/nodes/{node_id}/materialize-pin")
async def materialize_pin(
    execution_id: str,
    node_id: str,
    max_rows: int = Query(default=5000, ge=1, le=10000),
    _=Depends(require_permission("workspace", "CONSULTANT")),
) -> dict[str, Any]:
    """Lê o DuckDB do nó executado e materializa N linhas para serem
    embutidas em node.data.pinnedOutput.

    Diferente de /preview (que paginação on-demand), aqui é one-shot:
    o frontend chama uma vez quando o usuário clica em "Fixar" e guarda
    o resultado dentro do pinnedOutput JSON.

    Retorno:
        {
          "rows": [{...}, ...],
          "columns": ["a", "b"],
          "row_count": int,    # = len(rows), pode ser < total_rows
          "total_rows": int,   # total no DuckDB
          "truncated": bool,   # row_count < total_rows
          "schema_fingerprint": str,
          "size_bytes": int,   # JSON.dumps(rows) approx
        }
    """
```

Detalhes da implementação:

1. **Reuso máximo do `/preview`**: a lógica de localizar o DuckDB
   (`_SHIFT_EXECUTIONS_DIR / execution_id / sanitize_name(node_id).duckdb`),
   path traversal protection, query em `information_schema.tables` (pós fix
   #2 do `fix-executar-preview.md`), filtro de `_dlt_*`, escolha da última
   tabela user — **TUDO igual**. Extraia para função privada compartilhada
   `_open_node_duckdb(execution_id, node_id) -> (con, table_ref)` que ambos
   endpoints usam.

2. **Materialização**:
   ```python
   total = int(con.execute(f"SELECT COUNT(*) FROM {table_ref}").fetchone()[0])
   result = con.execute(f"SELECT * FROM {table_ref} LIMIT {max_rows}")
   raw_rows = result.fetchall()
   columns = [desc[0] for desc in result.description or []]
   rows = [
       {col: _serialize(val) for col, val in zip(columns, row)}
       for row in raw_rows
   ]
   ```

3. **schema_fingerprint**: reusar `fingerprint_schema()` de
   `shift-backend/app/services/workflow/semantic_hash.py` se importável; ou
   sha256 das `(name, type)` pares ordenados, primeiros 16 chars.

4. **size_bytes**: `len(json.dumps(rows, default=str).encode("utf-8"))`.
   Permite o frontend decidir antes de salvar se vale a pena (5 MB hard
   limit no frontend).

5. **Erro 404**: mesma mensagem do `/preview` — banco não existe ou nó não
   rodou ainda.

6. **Logs estruturados**: `logger.info("pin.materialized", execution_id=...,
   node_id=..., rows=N, total=M, truncated=bool, size_bytes=...)`.

### Refator do `/preview` para reuso

Extraia a função compartilhada:

```python
def _open_node_duckdb_table(
    execution_id: str, node_id: str
) -> tuple[duckdb.DuckDBPyConnection, str, tuple[str, str]]:
    """Abre o DuckDB do nó e retorna (con, table_ref_quoted, (schema, table)).

    Levanta HTTPException 404/400 quando aplicável. Caller é responsável
    por fechar a conexão.
    """
    ...
```

E aplique tanto em `/preview` quanto em `/materialize-pin`. **Não duplique**
a lógica de path traversal e de descoberta de tabela.

### Testes do endpoint

Arquivo: `shift-backend/tests/test_executions_api_pin.py`

Cenários:

1. `test_materialize_pin_happy_path`:
   - DuckDB temp com `CREATE TABLE main.t AS SELECT 1 AS a, 'x' AS b
     UNION ALL SELECT 2, 'y'`
   - POST `/materialize-pin?max_rows=10`
   - Espera 200, `rows == [{a:1,b:"x"}, {a:2,b:"y"}]`, `total_rows == 2`,
     `truncated == False`, `size_bytes > 0`.

2. `test_materialize_pin_truncates_when_exceeds_max`:
   - DuckDB com 100 linhas
   - POST `?max_rows=10`
   - Espera `row_count == 10`, `total_rows == 100`, `truncated == True`.

3. `test_materialize_pin_works_with_shift_extract_schema`:
   - Tabela em `shift_extract.orders` (caso real do bug do dlt)
   - Espera 200, dados corretos.

4. `test_materialize_pin_filters_dlt_internal_tables`:
   - DuckDB com `_dlt_loads`, `_dlt_pipeline_state`, e `shift_extract.orders`
   - Espera dados de `orders`, não dos `_dlt_*`.

5. `test_materialize_pin_404_when_node_not_run`:
   - DuckDB inexistente
   - Espera 404 com mensagem clara.

6. `test_materialize_pin_max_rows_clamped_to_10000`:
   - POST `?max_rows=99999`
   - Espera 422 (validação Pydantic do Query).

7. `test_materialize_pin_requires_permission`:
   - Usuário sem permissão → 403.

8. `test_materialize_pin_path_traversal_blocked`:
   - `node_id = "../../etc/passwd"` → 400.

---

## Parte 2 — Frontend: handler `onPin` v3

### Arquivo: `shift-frontend/components/workflow/node-config-modal.tsx`

Atualize `onPin` para implementar a lógica:

```ts
async function onPin() {
  if (is_pinned) {
    // unpin (remover pinnedOutput do node.data) — comportamento atual
    return existingOnUnpin()
  }

  const exec = currentOutput
  if (!exec) {
    toast.error("Sem output para fixar", "Execute o nó antes de fixar.")
    return
  }

  let rows: unknown[] | null = null
  let totalRows: number | null = null
  let truncated = false
  let sizeBytes = 0
  let columns: string[] = []

  // 1. Output inline (inline_data, code_node simples) — pin direto, sem fetch
  if (exec.output && Array.isArray(exec.output.rows)) {
    rows = exec.output.rows as unknown[]
    columns = (exec.output.columns as string[] | undefined) ?? []
    totalRows = rows.length
  }
  // 2. Output via DuckDB reference — chamar materialize-pin
  else if (exec.output_reference && exec.execution_id) {
    try {
      const result = await materializePinFromBackend({
        executionId: exec.execution_id,
        nodeId: node.id,
        maxRows: 5000,
      })
      rows = result.rows
      columns = result.columns
      totalRows = result.total_rows
      truncated = result.truncated
      sizeBytes = result.size_bytes
    } catch (err) {
      toast.error("Não foi possível fixar", err.message ?? "Erro ao buscar dados")
      return
    }
  }
  else {
    toast.error("Sem dados para fixar", "Output do nó não pode ser fixado.")
    return
  }

  // 3. Validar tamanho — workflow JSON não pode passar de ~5MB
  if (sizeBytes > 5 * 1024 * 1024) {
    const ok = confirm(
      `Pin grande: ${(sizeBytes / 1024 / 1024).toFixed(1)} MB. ` +
      `Pode tornar o save lento. Continuar?`
    )
    if (!ok) return
  }

  // 4. Salvar pin v3 em node.data.pinnedOutput
  const pinV3 = {
    __pinned_v: 3,
    rows,
    columns,
    row_count: rows?.length ?? 0,
    total_rows: totalRows,
    truncated,
    schema_fingerprint: ...,  // do response
    pinned_at: new Date().toISOString(),
  }
  onUpdateNodeData({ ...node.data, pinnedOutput: pinV3 })
  toast.success(
    truncated
      ? `Fixado: ${rows.length} de ${totalRows} linhas`
      : `Fixado: ${rows.length} linhas`,
    "Re-execute e re-fixe para atualizar."
  )
}
```

### Adicionar função em `shift-frontend/lib/auth.ts`

```ts
export type MaterializedPin = {
  rows: Array<Record<string, unknown>>
  columns: string[]
  row_count: number
  total_rows: number
  truncated: boolean
  schema_fingerprint: string
  size_bytes: number
}

export async function materializePinFromBackend(params: {
  executionId: string
  nodeId: string
  maxRows?: number
}): Promise<MaterializedPin> {
  const url = `${getApiBaseUrl()}/executions/${params.executionId}` +
              `/nodes/${encodeURIComponent(params.nodeId)}` +
              `/materialize-pin?max_rows=${params.maxRows ?? 5000}`
  const res = await fetch(url, {
    method: "POST",
    credentials: "include",
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `Falha ao materializar pin (${res.status})`)
  }
  return res.json()
}
```

### canPin

Continue aceitando `output OR output_reference` (já está no fix v2). Sem
mudança aqui.

---

## Parte 3 — Frontend: helper `pinnedOutputToState` v3

### Arquivo: `shift-frontend/components/workflow/workflow-editor.tsx`

Atualize o helper para suportar 3 versões:

```ts
function pinnedOutputToState(pinned: unknown): NodeExecState | null {
  if (!pinned || typeof pinned !== "object") return null
  const p = pinned as Record<string, unknown>

  // v3 — rows materializadas (atual)
  if (p.__pinned_v === 3 && Array.isArray(p.rows)) {
    return {
      status: "success",
      output: { rows: p.rows, columns: p.columns ?? [] },
      output_reference: null,
      row_count: typeof p.total_rows === "number" ? p.total_rows : (p.rows.length as number),
      execution_id: undefined,  // pin v3 não depende mais
      is_pinned: true,
      pin_truncated: p.truncated === true,
      pin_total_rows: typeof p.total_rows === "number" ? p.total_rows : null,
    }
  }

  // v2 — referência DuckDB com execution_id
  if (p.__pinned_v === 2) {
    return {
      status: "success",
      output: (p.output as Record<string, unknown> | undefined) ?? undefined,
      output_reference: (p.output_reference as ExecRef | null) ?? null,
      row_count: typeof p.row_count === "number" ? p.row_count : null,
      execution_id: typeof p.execution_id === "string" ? p.execution_id : undefined,
      is_pinned: true,
    }
  }

  // v1 (legado) — pinned é o próprio output dict
  return {
    status: "success",
    output: p as Record<string, unknown>,
    output_reference: null,
    row_count: null,
    is_pinned: true,
  }
}
```

### Adicionar campos ao tipo `NodeExecState`

Em `shift-frontend/lib/workflow/execution-context.ts` (ou onde o tipo vive):

```ts
export type NodeExecState = {
  // ... campos existentes
  pin_truncated?: boolean
  pin_total_rows?: number | null
}
```

---

## Parte 4 — UX: banner de truncamento

### Arquivo: `shift-frontend/components/workflow/node-config-modal.tsx`

Quando o nó está pinned e `pin_truncated === true`, mostre banner âmbar
no header da seção OUTPUT:

```tsx
{nodeExec?.is_pinned && nodeExec.pin_truncated && (
  <Alert variant="default" className="border-amber-500/40 bg-amber-50 dark:bg-amber-950/20">
    <AlertTriangle className="size-4 text-amber-600" />
    <AlertTitle className="text-xs">Pin parcial</AlertTitle>
    <AlertDescription className="text-xs">
      Mostrando {nodeExec.row_count} de {nodeExec.pin_total_rows} linhas.
      Re-execute o nó e re-fixe para atualizar com os dados completos.
    </AlertDescription>
  </Alert>
)}
```

E quando pinned (qualquer versão), o banner âmbar atual "Dados fixados — nó
não será re-executado" continua visível (já existe). Adicionar botão
"Atualizar pin" que executa o nó e re-pina automaticamente:

```tsx
<Button
  variant="ghost"
  size="sm"
  onClick={onRefreshPin}
  disabled={isRefreshing}
>
  <RefreshCw className="size-3 mr-1" />
  Atualizar pin
</Button>
```

`onRefreshPin`: dispara unpin + execução do nó isolado + repin. Versão
mínima: só dispara unpin e mostra toast "Re-execute o workflow para
atualizar". Versão completa: faz tudo automático. **Implemente a versão
mínima.** Versão completa fica para depois.

---

## Parte 5 — Runner: respeitar pin v3

### Arquivo: `shift-backend/app/orchestration/flows/dynamic_runner.py`

Procure onde o runner trata `pinnedOutput` (busque por `pinnedOutput` ou
`pinned`). A lógica atual:

```python
pinned = node_data.get("pinnedOutput")
if pinned and isinstance(pinned, dict):
    # passthrough: usa pinned como output do nó
    results[node_id] = pinned
    # emit node_complete com is_pinned=True
```

Atualize para extrair o output real conforme a versão:

```python
def _extract_pinned_output(pinned: dict) -> dict | None:
    """Retorna o dict de output do nó dado um pinnedOutput (v1/v2/v3)."""
    if not isinstance(pinned, dict):
        return None
    version = pinned.get("__pinned_v")

    if version == 3:
        # v3: rows materializadas — reconstrói output dict
        rows = pinned.get("rows")
        if not isinstance(rows, list):
            return None
        return {
            "rows": rows,
            "columns": pinned.get("columns") or [],
            "row_count": pinned.get("total_rows") or len(rows),
        }

    if version == 2:
        # v2: usa o output inline se disponível, senão a referência
        if isinstance(pinned.get("output"), dict):
            return pinned["output"]
        if pinned.get("output_reference"):
            return {"output_reference": pinned["output_reference"]}
        return None

    # v1 (legado): pinned é o próprio output
    if "rows" in pinned or "data" in pinned or "output_reference" in pinned:
        return pinned

    return None
```

Use `_extract_pinned_output(pinned)` em vez de `pinned` direto na lógica
de passthrough. Garante que downstream recebe um dict de output coerente,
independente da versão.

### Teste do runner

Arquivo: `shift-backend/tests/test_dynamic_runner.py` (já existe).

Adicionar caso:

```python
def test_pinned_v3_passthrough_emits_rows():
    """Pin v3 com rows materializadas vira output do nó sem re-executar."""
    pinned_v3 = {
        "__pinned_v": 3,
        "rows": [{"a": 1}, {"a": 2}],
        "columns": ["a"],
        "row_count": 2,
        "total_rows": 2,
        "truncated": False,
    }
    payload = {
        "nodes": [{"id": "n1", "type": "filter", "data": {"pinnedOutput": pinned_v3}}],
        "edges": [],
    }
    collected = []
    async def sink(event): collected.append(event)
    asyncio.run(run_workflow(workflow_payload=payload, ..., event_sink=sink))
    complete = next(e for e in collected if e["type"] == "node_complete")
    assert complete["is_pinned"] is True
    # row_count chega via slim payload (não output completo)
    assert complete["row_count"] == 2
```

E também atualizar o teste **`test_pinned_output_emits_node_complete_with_is_pinned`**
que está quebrado hoje (achado na revisão pós-Fase 9): a asserção
`complete["output"] == pinned` deve virar
`complete["row_count"] == ...` ou similar, conforme o slim payload.

---

## Parte 6 — Round-trip YAML (Fase 9)

### Validação

Pin v3 está em `node.data.pinnedOutput`. O `yaml_serializer.to_yaml`
serializa `node.data` como `config:` — então pin viaja no export.

Adicione teste em
`shift-backend/tests/test_workflow_yaml_serializer.py`:

```python
def test_yaml_round_trip_preserves_pin_v3():
    workflow = {
        "nodes": [{
            "id": "n1",
            "type": "filter",
            "position": {"x": 0, "y": 0},
            "data": {
                "condition": "amount > 0",
                "pinnedOutput": {
                    "__pinned_v": 3,
                    "rows": [{"id": 1, "name": "Ana"}, {"id": 2, "name": "Bob"}],
                    "columns": ["id", "name"],
                    "row_count": 2,
                    "total_rows": 2,
                    "truncated": False,
                    "pinned_at": "2026-04-29T12:00:00Z",
                },
            },
        }],
        "edges": [],
    }
    yaml_str = to_yaml(workflow)
    assert "__pinned_v" in yaml_str
    parsed = from_yaml(yaml_str)["definition"]
    assert parsed["nodes"][0]["data"]["pinnedOutput"] == workflow["nodes"][0]["data"]["pinnedOutput"]
```

---

## Critério de aceite

- [ ] Endpoint `POST /executions/{id}/nodes/{nid}/materialize-pin` funciona,
  com 8 testes cobrindo happy path, truncamento, schema não-main, filtro
  `_dlt_*`, 404, validação de max_rows, autorização, path traversal.
- [ ] Função `materializePinFromBackend` no `auth.ts`.
- [ ] `onPin` no modal busca rows reais via endpoint quando há reference,
  pina inline quando há `output` inline. Confirma com usuário se > 5 MB.
- [ ] `pinnedOutputToState` reidrata v1/v2/v3 corretamente.
- [ ] Banner âmbar "Pin parcial" aparece quando `pin_truncated === true`.
- [ ] Botão "Atualizar pin" (versão mínima: só unpin + toast).
- [ ] Runner usa `_extract_pinned_output` e respeita pin v3.
- [ ] Teste do runner para pin v3 passthrough.
- [ ] Teste do `test_pinned_output_emits_node_complete_with_is_pinned`
  atualizado para slim payload.
- [ ] Round-trip YAML preserva pin v3.
- [ ] `pytest tests/` continua passando (mesmo número de passing que antes
  + os testes novos).
- [ ] `npm run build` no shift-frontend/ compila.
- [ ] Teste manual:
  - SQL: Etrade → execute → fixar → reiniciar backend → reabrir editor →
    pin ainda mostra os mesmos dados (sobreviveu).
  - Workflow com pin → export YAML → import em workflow vazio → pin viaja junto.

## Não-objetivos

- **Não** materializar para nós inline (`inline_data`, `code` simples) que
  já têm `output.rows` na própria SSE — pin direto, sem chamar endpoint.
- **Não** implementar "Atualizar pin" automático com re-execução do nó
  isolado. Versão mínima (toast pedindo re-execute) é suficiente nesta
  rodada.
- **Não** mudar o limite de 10000 rows hard limit do backend. Se usuário
  precisar de mais, é problema de produto.
- **Não** introduzir Zustand para essa mudança — useState + helpers é
  suficiente.
- **Não** mexer em workflow_test_service.py além do necessário.

## Estimativa

- Backend (endpoint + refator + tests): 2-3h
- Frontend (handler v3 + helper + UX): 2-3h
- Runner (extract helper + tests): 1h
- YAML round-trip test: 30min
- Verificação manual: 30min
- **Total: ~6-8h**

Sonnet 4.6 high-effort dá conta sozinho. Bem-bounded. Sem concorrência.

## Referências

- `docs/fix-executar-preview.md` — contém o fix do `information_schema` que
  vai ser reutilizado em `_open_node_duckdb_table`.
- `docs/flowfile-implementation-plan.md` — princípios gerais.
- `docs/review-fixes-fases-1-5.md` — histórico do slim payload (que originou
  a regressão do pin).
