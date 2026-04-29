# Prompt — Fix do delay ao Executar e do preview de nó vazio

Use este arquivo como instrução completa para um agente de IA. Auto-contido.

---

## Contexto

Após Fases 1-5 + 9 estarem implementadas, dois problemas foram identificados em
uso real:

1. **Delay grande ao clicar em "Executar"** no editor de workflow.
2. **404 "Nenhuma tabela encontrada no resultado do nó"** ao tentar ver preview
   de output de um nó SQL Database, mesmo quando a execução completou ok.

Ambos têm causas claras, identificadas por análise de código. Sua tarefa é
implementar os fixes na ordem indicada e adicionar testes.

### Estado atual do projeto (leia antes de começar)

- Backend: FastAPI + asyncio + APScheduler in-process. **NÃO usa Prefect**
  (foi removido). DuckDB-first como contrato de dados intermediários.
- Frontend: Next.js 16 + React 19 + shadcn/ui.
- Plano geral: `docs/flowfile-implementation-plan.md`.
- Revisões anteriores: `docs/review-fixes-fases-1-5.md`.

### Princípios não-negociáveis

1. Não introduza Prefect, Celery, Polars como engine.
2. DuckDB-first.
3. Pydantic v2.
4. Manter os 235+ testes existentes passando após suas mudanças.
5. Cada bug corrigido tem teste novo que falha SEM o fix e passa COM o fix.
6. Comente o "porquê", não o "como".

---

## Problema #1 — Delay ao clicar em "Executar"

### Sintoma
Ao clicar "Executar" no editor, o spinner aparece imediatamente mas o painel
fica vazio por centenas de ms a alguns segundos antes do primeiro evento SSE
chegar. Sensação de "travado".

### Causa
Em `shift-frontend/components/workflow/workflow-editor.tsx` (handler de
execução, busque pela função que chama `testWorkflowStream`):

```ts
setIsExecuting(true)              // spinner liga aqui

try {
  await updateWorkflow(workflowId, {   // ← HTTP PUT bloqueante
    name,
    description: description || null,
    tags,
    definition: buildDefinition(),     // serializa nodes/edges
  })
} catch (...) { ... }

await testWorkflowStream(...)     // só agora abre o SSE
```

O save acontece SEMPRE antes da execução, mesmo quando o workflow não foi
modificado. O comentário no código diz "Save first so the backend sees the
latest definition" — intencional, mas a UX não comunica e paga o custo todas
as vezes.

### Fix #1A — Skip save quando não há mudanças

**Arquivo:** `shift-frontend/components/workflow/workflow-editor.tsx`

**O projeto já tem flag de dirty.** Procure pelo state `dirty`/`setDirty`
(toggled quando o usuário modifica nodes/edges/configs). Use:

```ts
async function handleExecute() {
  setIsExecuting(true)
  try {
    if (dirty) {
      // mostrar estado "Salvando…" (Fix 1B abaixo)
      await updateWorkflow(workflowId, {...})
      setDirty(false)
    }
    await testWorkflowStream(...)
  } finally {
    // ...
  }
}
```

Quando `dirty=false`, o save inteiro é pulado. Clique consecutivo no
"Executar" só paga save uma vez (na primeira mudança).

### Fix #1B — Mostrar "Salvando…" durante o save

**Arquivo:** `shift-frontend/components/workflow/execution-panel.tsx`
e/ou `workflow-editor.tsx`

Antes do primeiro evento SSE, o painel fica vazio. Adicione um estado
intermediário visível:

1. Adicionar prop `phase` ao `ExecutionPanel`:
   ```ts
   type ExecutionPhase = 'saving' | 'connecting' | 'streaming' | 'idle'
   ```

2. No editor:
   ```ts
   setPhase('saving')
   if (dirty) {
     await updateWorkflow(...)
     setDirty(false)
   }
   setPhase('connecting')
   await testWorkflowStream(...)  // primeiro evento muda para 'streaming'
   ```

3. No painel, render condicional no header (perto do "Executando…"):
   - `phase === 'saving'`: ícone + texto "Salvando workflow…"
   - `phase === 'connecting'`: ícone + texto "Iniciando execução…"
   - `phase === 'streaming'`: comportamento atual ("Executando…" + nó atual)

4. Use `MorphLoader` que já é o spinner padrão do projeto.

### Critério de aceite #1

- Workflow salvo (não-dirty) → clique em "Executar" abre SSE em < 100ms.
- Workflow modificado → clique em "Executar" mostra "Salvando workflow…"
  durante o save, depois "Iniciando execução…", depois eventos normais.
- Teste manual: editar config de um nó, clicar Executar duas vezes seguidas
  (sem editar entre as duas) → segunda execução abre SSE imediato.

---

## Problema #2 — "Nenhuma tabela encontrada no resultado do nó"

### Sintoma
Workflow com `sql_database` (sem `partition_on`) executa com sucesso, status
`completed`, dados extraídos (visível no log do backend), mas ao clicar no nó
para ver preview, frontend mostra erro 404 "Nenhuma tabela encontrada no
resultado do nó".

### Causa raiz
Em `shift-backend/app/services/extraction_service.py:112-179`, o caminho
**legacy** (sem partição) usa `dlt` com `dataset_name="shift_extract"`. No
DuckDB, `dataset_name` do dlt vira **schema** — então a tabela é criada
como `shift_extract.<tabela>`, não em `main`.

O endpoint preview em `shift-backend/app/api/v1/executions.py:95` faz:

```python
tables = con.execute("SHOW TABLES").fetchall()  # só lista schema main
if not tables:
    raise HTTPException(404, "Nenhuma tabela encontrada no resultado do nó.")
table_name = tables[-1][0]
table_ref = quote_identifier(table_name)
```

`SHOW TABLES` no DuckDB lista apenas o schema **corrente** (`main`). Como os
dados estão em `shift_extract`, o resultado é zero tabelas → 404.

O caminho **particionado** (`extraction_service.py:181+`) usa `JsonlStreamer`
e materializa em `main` (`dataset_name=""`), por isso esse caminho não
quebra. A divergência é só no legacy.

### Fix #2A — Preview lê `information_schema.tables`

**Arquivo:** `shift-backend/app/api/v1/executions.py`

Substitua o bloco que usa `SHOW TABLES`:

```python
try:
    con = duckdb.connect(str(db_path))
    try:
        tables_res = con.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'system')
              AND table_type = 'BASE TABLE'
            ORDER BY
              CASE table_schema WHEN 'main' THEN 0 ELSE 1 END,
              table_name
            """
        ).fetchall()
        if not tables_res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Nenhuma tabela encontrada no resultado do nó.",
            )

        # Heurística: prefere a última tabela criada. Quando o nó usa dlt,
        # ele cria múltiplas tabelas internas (_dlt_loads, _dlt_pipeline_state,
        # etc); filtramos as que começam com '_dlt_' para pegar a real.
        user_tables = [
            (s, t) for s, t in tables_res
            if not t.startswith("_dlt_")
        ]
        if not user_tables:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Nenhuma tabela encontrada no resultado do nó.",
            )

        table_schema, table_name_str = user_tables[-1]
        table_ref = f"{quote_identifier(table_schema)}.{quote_identifier(table_name_str)}"

        total_row = con.execute(
            f"SELECT COUNT(*) FROM {table_ref}"
        ).fetchone()
        total = int(total_row[0]) if total_row else 0

        result = con.execute(
            f"SELECT * FROM {table_ref} LIMIT {limit} OFFSET {offset}"
        )
        raw_rows = result.fetchall()
        columns = [desc[0] for desc in result.description or []]
    finally:
        con.close()
```

**Notas importantes:**

- Filtra `_dlt_*` (o dlt cria tabelas internas como `_dlt_loads`,
  `_dlt_pipeline_state`, `_dlt_version`). Sem o filtro o preview pode mostrar
  uma dessas e confundir.
- Ordena `main` primeiro (legado): se mesmo nó tiver tabelas em `main` E
  `shift_extract`, prefere `main`.
- `table_ref` agora é `<schema>.<table>` quoteado — funciona em qualquer schema.

### Fix #2A.1 — Logging quando preview cai em schema não-main

Adicione log para detectar o caso (vai ajudar a decidir se vale fazer 2B
depois):

```python
if table_schema != "main":
    logger.info(
        "preview.non_main_schema",
        execution_id=execution_id,
        node_id=node_id,
        schema=table_schema,
        table=table_name_str,
    )
```

Use `from app.core.logging import get_logger` e instancie no topo do módulo.
Permite saber em produção quantos previews caem nesse caso.

### Critério de aceite #2

Adicione testes em `shift-backend/tests/test_executions_api_preview.py` (criar
o arquivo se não existir):

1. **Tabela em `main` (caso atual feliz)**:
   - Cria DuckDB temporário com `CREATE TABLE main.results AS SELECT 1 AS x`
   - Chama o endpoint
   - Espera 200 com 1 linha

2. **Tabela em schema `shift_extract` (regressão deste bug)**:
   - Cria DuckDB temporário com:
     ```sql
     CREATE SCHEMA shift_extract;
     CREATE TABLE shift_extract.orders AS SELECT 1 AS id;
     ```
   - Chama o endpoint
   - Espera 200 com 1 linha (e NÃO 404 como hoje)

3. **Múltiplas tabelas com tabelas internas dlt**:
   - DuckDB com `_dlt_loads`, `_dlt_version`, e `shift_extract.orders`
   - Chama o endpoint
   - Espera 200 e que retorne dados de `orders`, não de `_dlt_*`

4. **Banco vazio**:
   - DuckDB com nenhuma tabela base
   - Espera 404 com mensagem clara

5. **Banco só com tabelas dlt internas**:
   - DuckDB com apenas `_dlt_loads` e `_dlt_version`
   - Espera 404 (não tem dado de usuário pra preview)

Use o helper de mock de execution já existente nos outros testes
`test_executions_api_*`. Path do banco precisa ficar dentro de
`_SHIFT_EXECUTIONS_DIR / execution_id` (ver `executions.py:71`).

---

## Não-objetivos

- **NÃO** mexa em `extraction_service.py` para padronizar schema entre legacy
  e particionado. É refator maior, fica para depois (fora de escopo).
- **NÃO** elimine o caminho legacy do dlt. Idem.
- **NÃO** mude o comportamento do save em sub-workflows ou execução
  agendada — o fix #1A é só do botão "Executar" no editor.
- **NÃO** introduza Zustand se for primeira mudança no frontend — useState
  + props é suficiente para o estado `phase`.

---

## Checklist final

- [ ] Fix #1A implementado: handleExecute pula `updateWorkflow` quando `!dirty`.
- [ ] Fix #1B implementado: estado `phase` propagado ao painel; estados visuais
  "Salvando…" / "Iniciando execução…" / "Executando…" funcionam.
- [ ] Fix #2A implementado: preview usa `information_schema.tables`, filtra
  `_dlt_*`, prefere `main`.
- [ ] Fix #2A.1 implementado: log estruturado quando schema != main.
- [ ] 5 testes novos em `tests/test_executions_api_preview.py` passando.
- [ ] Suite atual: `pytest tests/test_executions_api_auth.py` continua passando
  (autorização não regrediu).
- [ ] `npm run build` no `shift-frontend/` compila.
- [ ] Teste manual:
  - Editar config, clicar Executar duas vezes — segunda é instantânea.
  - Workflow com sql_database (sem partition_on) → preview do nó retorna dados.

## Referências de código relevantes

- `shift-frontend/components/workflow/workflow-editor.tsx` — handler de Executar
- `shift-frontend/components/workflow/execution-panel.tsx` — render do painel
- `shift-backend/app/api/v1/executions.py:56-135` — endpoint de preview
- `shift-backend/app/services/extraction_service.py:112-179` — caminho legacy
  com dlt+shift_extract (NÃO mexer, mas entender para validar fix)
- `shift-backend/app/data_pipelines/duckdb_storage.py` — `quote_identifier`,
  `sanitize_name`
