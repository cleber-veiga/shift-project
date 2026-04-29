# Prompt — Correções da revisão das Fases 1-5

Use este arquivo como instrução completa para um agente de IA fazer as correções. É auto-contido — o agente não precisa de contexto extra além dos arquivos do repo.

---

## Contexto

Foi feita uma revisão das implementações das Fases 1-5 do plano em
[`docs/flowfile-implementation-plan.md`](flowfile-implementation-plan.md). A revisão
encontrou 3 problemas críticos, 3 gaps em relação aos prompts originais, e 9
problemas menores de estilo/cleanup. Sua tarefa é corrigir tudo, na ordem indicada,
sem regredir nada que já funciona.

**216 testes passam hoje** (151 das fases 4-5 + 65 dos nós novos). Após suas
correções, todos devem continuar passando, e os novos testes que você adicionar
também.

## Princípios não-negociáveis (revise antes de qualquer mudança)

1. **Shift NÃO usa Prefect.** Foi removido na migration
   `2026_04_16_b8c9d0e1f2a3_drop_prefect_flow_run_id.py`. Orquestração roda em
   `shift-backend/app/orchestration/flows/dynamic_runner.py` (asyncio puro) +
   APScheduler in-process. Não introduza Prefect, Celery ou outro orquestrador externo.
2. **DuckDB-first como contrato de dados intermediários.** Não trocar para Polars.
   Quando precisar materializar, use `DuckDbReference`.
3. **Single-process, multi-replica.** Não introduza estado em memória que quebre
   a premissa de múltiplas réplicas coordenando via Postgres.
4. **Migrations Alembic com upgrade + downgrade simétricos.**
5. **Frontend Next.js 16 + React 19 + shadcn/ui.** Zustand já é dependência do projeto.
6. **Não escreva docstrings/comentários elogiosos.** Comente o "porquê", não o "como".

## Ordem de execução obrigatória

Você DEVE seguir esta ordem para evitar conflito:

1. Primeiro o **Bloco A** (segurança e bugs críticos) — bloqueador.
2. Depois o **Bloco B** (gaps em relação aos prompts originais).
3. Por último o **Bloco C** (cleanup) — só se sobrar tempo/contexto.

Cada bloco abaixo tem instruções, arquivos afetados, e critério de aceite verificável.

---

# Bloco A — Crítico (bloquear merge sem isto)

## A1. Autorização nos endpoints de execução

**Arquivos:** `shift-backend/app/api/v1/executions.py`

**Problema:** Os endpoints `GET /executions/{execution_id}/nodes/{node_id}/preview`
(linha 56) e `GET /executions/{execution_id}/plan` (linha 138) usam apenas
`Depends(get_current_user)` para autenticação. Qualquer usuário autenticado pode
ler resultado/plano de qualquer execução se souber o ID. Compare com
`shift-backend/app/api/v1/workflows.py:822` que usa
`require_permission("workspace", "CONSULTANT")`.

**Correção:**
1. Buscar o `WorkflowExecution` pelo `execution_id` antes de servir os dados.
2. A partir do `workflow_id` da execução, derivar `workspace_id`.
3. Validar acesso do `current_user` ao workspace via mecanismo já existente
   em `require_permission` ou `permission_service`. Procure padrões em
   `shift-backend/app/api/v1/workflows.py` para o padrão correto neste projeto.
4. Aplicar a ambos os endpoints (`/preview` e `/plan`).
5. Retornar `403` (não `404`) quando o usuário existe mas não tem acesso ao
   workspace, para distinguir de "não existe".

**Critério de aceite:**
- Teste `test_executions_api.py` com 2 cenários:
  - `test_preview_forbidden_for_other_workspace`: usuário do workspace A tentando
    ler execução do workspace B → 403.
  - `test_plan_forbidden_for_other_workspace`: idem para `/plan`.
- Os endpoints continuam funcionando para o owner (200).

## A2. `input_fingerprints=[]` invalida o semantic hash

**Arquivo:** `shift-backend/app/orchestration/flows/dynamic_runner.py:1315-1319`

**Problema atual:**

```python
_sem_hash = compute_semantic_hash(
    config=node_data,
    input_fingerprints=[],   # ← sempre vazio
    node_type=_resolver_type,
)
```

O `compute_semantic_hash` (em `shift-backend/app/services/workflow/semantic_hash.py`)
foi projetado para que dois nós com mesma config mas inputs diferentes produzam
hashes diferentes. Hoje todos os nós com mesma config têm o mesmo hash
independente do upstream. Para Fase 5 isso é só observabilidade quebrada, mas
quando a Fase 6+ usar para skip por cache, vai virar bug grave de cache
poisoning. Corrigir agora.

**Correção:**
1. Manter um dict `_node_semantic_hashes: dict[str, str] = {}` no escopo do
   `run_workflow` (próximo a `results: dict[...]` na linha ~1107). Cada vez que
   um nó for resolvido com sucesso, armazene seu `_sem_hash` ali.
2. Antes de calcular `_sem_hash` para o nó atual, colete os hashes dos upstreams
   olhando em `reverse_adj[node_id]` (já existe no escopo). Para cada
   `predecessor_id`, pegue `_node_semantic_hashes.get(predecessor_id)` (pode ser
   `None` se predecessor não foi processado — pular ou usar string vazia
   determinística).
3. Ordene os fingerprints (a função já ordena via `sorted(input_fingerprints)`,
   mas garanta que a coleta não tem ambiguidade) e passe na chamada:

```python
_input_fps = sorted(
    _node_semantic_hashes.get(pred_id, "")
    for pred_id in reverse_adj.get(node_id, set())
)
_sem_hash = compute_semantic_hash(
    config=node_data,
    input_fingerprints=_input_fps,
    node_type=_resolver_type,
)
_node_semantic_hashes[node_id] = _sem_hash
```

**Critério de aceite:**
- Teste novo em `tests/test_semantic_hash_propagation.py`:
  - Workflow A→B→C onde A e A' têm configs diferentes mas B e C iguais. Hash
    de C em workflow A deve ser **diferente** de hash de C em workflow A'.
  - Workflow A→B→C com 100 execuções idênticas. Hash de C deve ser idêntico
    em todas.
- Rodar `pytest tests/test_semantic_hash.py tests/test_semantic_hash_propagation.py`
  e mostrar passando.

## A3. `_param_restorations` capturado mas nunca aplicado

**Arquivo:** `shift-backend/app/orchestration/flows/dynamic_runner.py:1033-1051`

**Problema:** `apply_parameters` retorna lista de mutações que devem ser revertidas,
mas o código nunca chama `restore_parameters(_param_restorations)`. O
`resolved_payload` é mutado in-place permanentemente. Hoje não causa bug visível
porque o payload é construído a cada `run_workflow`, mas é bug latente: loops
inline, sub-workflows, ou qualquer reuso futuro do payload veriam valores já
resolvidos.

**Correção:**
1. Importar `restore_parameters` no topo (não dentro do try, mover o import).
2. Envolver o `with bind_context(...)` que executa o workflow em try/finally e
   chamar `restore_parameters(_param_restorations)` no finally.

```python
try:
    with bind_context(...), start_execution_span(...):
        # ... existing code ...
        return result
finally:
    if _param_restorations:
        from app.orchestration.flows.parameter_resolver import restore_parameters
        restore_parameters(_param_restorations)
```

**Critério de aceite:**
- Teste novo em `tests/test_parameter_resolver.py`:
  - `test_restore_after_run_keeps_payload_pristine`: monte um `resolved_payload`
    com `${API_URL}` em config, rode `run_workflow` (mockando processors),
    verifique que após retorno o `resolved_payload` ainda contém `${API_URL}`
    literal, não o valor resolvido.

---

# Bloco B — Gaps em relação aos prompts originais

## B1. Schema inference para `sql_database`

**Arquivo:** `shift-backend/app/services/workflow/schema_inference/__init__.py`

**Problema:** Hoje retorna `None` para `sql_database` (linha 252). O prompt original
da Fase 5 pedia explicitamente:

> sql_database: executar EXPLAIN ou SELECT ... LIMIT 0 contra a connection.
> Cache schema por (connection_id + query_hash).

Isso impacta o nó mais usado em workflows ETL — sem schema preview, frontend não
mostra colunas downstream sem ter rodado o workflow uma vez.

**Correção:**
1. Adicionar handler `_sql_database_schema(config, input_schemas)` que:
   - Lê `connection_id` do config.
   - Resolve a connection via `connection_service` (use o serviço já existente
     em `shift-backend/app/services/connection_service.py`; pode precisar tornar
     a função síncrona ou criar uma versão sync).
   - Abre conexão via SQLAlchemy/driver apropriado.
   - Executa a query envolvida em `SELECT * FROM ({query}) AS __schema_probe LIMIT 0`.
   - Lê `cursor.description` para extrair nome e tipo de cada coluna.
   - Mapeia tipos do driver para SQL types via `_TYPE_MAP` ampliado se necessário.
   - Retorna `list[FieldDescriptor]`.
2. Adicionar cache LRU module-level: `dict[(connection_id, sha256(query)), list[FieldDescriptor]]`.
   Limite de 256 entradas. Use `functools.lru_cache` com chave composta ou um
   pequeno cache manual com OrderedDict.
3. Capturar QUALQUER exceção (connection error, timeout, query inválida) e
   retornar `None` — schema inference NUNCA derruba fluxo.
4. Registrar o handler em `_HANDLERS`.

**Importante:** schema_inference deve ser síncrono (é chamado de dentro de BFS
síncrono no `_propagate_schema` em `workflows.py`). Se o `connection_service` é
async, crie um wrapper que use `asyncio.run` cuidadosamente OU torne o lookup
de connection síncrono (preferível — adicione método `get_sync` no
`connection_service`).

**Critério de aceite:**
- Teste em `tests/test_schema_inference.py`:
  - Mock de connection retornando cursor com `description=[("id","INTEGER",...),
    ("name","VARCHAR",...)]`. Verificar que `predict_output_schema("sql_database",
    {"connection_id": ..., "query": "SELECT id, name FROM t"}, {})` retorna
    os 2 FieldDescriptors esperados.
  - Cache hit: 2ª chamada com mesma query NÃO chama o cursor novamente.
  - Connection error: retorna None, não levanta exceção.

## B2. Reducer incremental no frontend (sem reconstruir a cada render)

**Arquivo:** `shift-frontend/components/workflow/execution-panel.tsx:87`

**Problema:**

```tsx
export function ExecutionPanel({ events, ... }) {
  const { nodes: nodeStates } = buildNodeStates(events)  // ← O(N) a cada render
```

A cada render, percorre todo array de events. Para workflow com 50 nós + loop de
10 iterações = 500+ eventos, é 500 iterações por render.

**Correção (escolha UMA das duas):**

**Opção A (mínima — recomendada para fix rápido):**
Envolver em `useMemo`:

```tsx
const { nodes: nodeStates } = useMemo(
  () => buildNodeStates(events),
  [events]
)
```

Como `events` é provavelmente reconstruído como novo array a cada novo evento
(via `setEvents([...prev, e])`), o useMemo só re-executa quando há novo evento,
não em todo render por outras causas (resize, hover, etc).

**Opção B (correta arquiteturalmente — preferida se houver tempo):**
Migrar para Zustand store seguindo o que o prompt original pedia:
1. Criar `shift-frontend/components/workflow/execution-store.ts` usando
   `create` do `zustand` (já é dep — verifique `package.json`).
2. Estrutura:
   ```ts
   type ExecutionStore = {
     order: string[]
     byNodeId: Record<string, NodeState>
     executionId: string | null
     applyEvent: (e: WorkflowTestEvent) => void
     reset: () => void
   }
   ```
3. `applyEvent` faz a transição incremental do estado para um único evento
   (mesmo switch que está em `buildNodeStates`, mas processa só o novo).
4. `ExecutionPanel` lê via `useExecutionStore(s => s.byNodeId)`.
5. Quem chama o panel registra um callback no SSE que faz
   `useExecutionStore.getState().applyEvent(e)`.

**Critério de aceite:**
- Workflow de teste com 50 nós + loop de 10 iterações: react devtools profiler
  mostra `ExecutionPanel` re-renderizando em < 5ms por novo evento (não escala
  com tamanho do histórico).
- Cancelamento e re-execução continuam funcionando.
- Os tipos exportados (`NodeExecState`, `NodeExecStatus`) em
  `shift-frontend/lib/workflow/execution-context.ts` não regridem — outras
  partes do projeto consomem isso.

## B3. Verificação de tamanho de SSE < 2KB

**Arquivo:** novo teste em `shift-backend/tests/test_sse_payload_size.py`

**Problema:** O critério "Tamanho médio de evento SSE < 2 KB" não tem teste
automático. O payload foi reduzido em `_transform_for_sse`, mas não há
verificação.

**Correção:**
1. Criar teste que monta um evento `node_complete` com campos típicos
   (incluindo um nome de label e schema_fingerprint reais).
2. Serializa via `json.dumps(payload)` e mede `len(...)`.
3. Asserta < 2048 bytes para casos padrão.
4. Inclui caso patológico: nó com label de 200 caracteres + node_id UUID +
   stack trace de 1000 chars no error → ainda asserta < 4 KB (limite superior).

**Critério de aceite:** teste passa.

---

# Bloco C — Cleanup (só se houver tempo)

## C1. Duplicação de `StrategyDecision`

`strategy_observer.py` e `strategy_resolver.py` têm dataclasses idênticas com
mesmo nome. Mova para `shift-backend/app/orchestration/flows/strategy_types.py`
e importe de lá nos dois.

## C2. Inconsistência semântica de `data_worker` no SSE

`strategy_resolver.py:102` emite `strategy="data_worker"` mas o runner roda
`local_thread` (fallback até Fase 6). O evento mente sobre o que vai acontecer.

**Correção:** no `build_strategy_sse_event`, emitir tanto `declared_strategy`
quanto `effective_strategy`. O frontend pode mostrar ambos ou priorizar o
effective.

## C3. `_normalize_value` ordena lista de primitivos

`semantic_hash.py:117` ordena `list[str]` em normalização. Para `sort_columns:
list[dict]` está OK (mantém ordem), mas se algum nó futuro tiver `list[str]`
onde a ordem importa, gera bug silencioso.

**Correção:** parâmetro do node_type poderia indicar quais campos são
order-preserving. Por ora, adicione comentário explícito documentando o
comportamento e crie um conjunto `ORDER_PRESERVING_FIELDS = {"sort_columns",
"column_order", "select_columns", ...}` que escapa a ordenação.

## C4. Imports dentro do loop em `dynamic_runner.py`

Linhas 1300-1304: imports de `strategy_resolver` e `semantic_hash` dentro do
for-de-cada-nó. Mover para o topo do arquivo. Mantém o `# noqa: PLC0415` se
houver imports já lá.

## C5. `except Exception` sem `.exception()` no resolver fallback

`dynamic_runner.py:1332` silencia qualquer erro do resolver. Adicionar
`logger.exception("strategy_resolver.failed", node_id=node_id)` para que bugs
sutis no resolver sejam visíveis em produção.

## C6. `ATTACH '{db_path}'` sem escape em `union_node.py:95`

```python
conn.execute(
    f"ATTACH '{db_path}' AS {quote_identifier(alias)} (READ_ONLY)"
)
```

Se `db_path` contém aspa simples, é injection. Em prática controlado pelo Shift
(paths são gerados pelo backend), mas higiênico. Use parametrização do DuckDB
ou escape manual: `db_path.replace("'", "''")`.

## C7. Teste de cobertura de `NODE_EXECUTION_PROFILE`

Adicionar teste em `tests/test_node_profile.py`:

```python
def test_node_profile_covers_all_registered_processors():
    from app.services.workflow.nodes import PROCESSOR_REGISTRY
    from app.orchestration.flows.node_profile import NODE_EXECUTION_PROFILE
    missing = set(PROCESSOR_REGISTRY.keys()) - set(NODE_EXECUTION_PROFILE.keys())
    assert not missing, (
        f"Node types sem entrada em NODE_EXECUTION_PROFILE: {missing}. "
        f"Adicione em shift-backend/app/orchestration/flows/node_profile.py"
    )
```

Pode falhar agora — ajuste o `NODE_EXECUTION_PROFILE` para incluir todos os nós
registrados ou documente exclusões intencionais.

## C8. `output_summary` nos novos nós

Os 7 nós novos (sort, sample, record_id, union, pivot, unpivot, text_to_rows)
não retornam `output_summary` com `row_count_in`, `row_count_out`, `warnings[]`.
Útil para observabilidade.

**Correção mínima:** após o `CREATE OR REPLACE TABLE`, fazer
`SELECT COUNT(*) FROM input` e `SELECT COUNT(*) FROM output`. Adicionar ao
return:

```python
return {
    "node_id": node_id,
    "status": "completed",
    "output_field": output_field,
    output_field: output_reference,
    "output_summary": {
        "row_count_in": row_in,
        "row_count_out": row_out,
        "warnings": [],
    },
}
```

Para `record_id` sem `order_by`, adicione warning correspondente.
Para `sample` random sem seed em workflow publicado, idem.

## C9. NODE_PROFILE local nos nós

O prompt da Fase 2 pedia declaração de `NODE_PROFILE` no início de cada arquivo
de nó. Foi feito tudo central em `node_profile.py` (decisão de design legítima
e provavelmente melhor). Atualize `docs/flowfile-implementation-plan.md` na
Fase 2 (e seguintes) para refletir essa convenção e remover a confusão para
agentes futuros.

---

# Checklist final antes de abrir PR

- [ ] `pytest shift-backend/tests/ -x` passa (todos os ~216 + os novos que você adicionar)
- [ ] `npm run lint` no `shift-frontend/` passa
- [ ] `npm run build` no `shift-frontend/` compila
- [ ] Os 3 itens do Bloco A foram corrigidos (são bloqueadores)
- [ ] Cada bug corrigido tem teste novo que falha SEM o fix e passa COM o fix
- [ ] Não introduziu Prefect, Celery ou Polars como engine
- [ ] Migrations Alembic (se houver) têm upgrade + downgrade simétricos
- [ ] Critérios de aceite de cada item estão verificados
- [ ] PR description lista cada item corrigido + teste correspondente

# O que NÃO fazer

- Não refatorar arquivos não listados aqui.
- Não reformatar/lint massivo (introduz ruído de revisão).
- Não trocar o paradigma do React Context atual por Zustand se escolher a
  Opção A do B2 — só faça a migração para Zustand se for fazer completa.
- Não inventar novos node_types, novos endpoints, ou novas tabelas. Os fixes
  são pontuais.
- Não silenciar exceções para "fazer o teste passar". Se um teste novo falha,
  o bug precisa ser realmente corrigido.

# Referências

- Plano completo: `docs/flowfile-implementation-plan.md`
- Análise comparativa: `benchmarking_flowfile_shift.md`,
  `benchmarking_flowfile_nodes_shift.md`,
  `benchmarking_flowfile_performance_shift.md`
- Mecanismos do Flowfile: `docs/flowfile-mechanisms.md`
