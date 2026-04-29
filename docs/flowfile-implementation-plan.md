# Plano de Ação — Importar Padrões do Flowfile para o Shift

## Sobre este documento

Plano de implementação consolidado a partir de quatro análises prévias:

- [`../benchmarking_flowfile_shift.md`](../benchmarking_flowfile_shift.md) — arquitetura/estratégia
- [`../benchmarking_flowfile_nodes_shift.md`](../benchmarking_flowfile_nodes_shift.md) — catálogo de nós
- [`../benchmarking_flowfile_performance_shift.md`](../benchmarking_flowfile_performance_shift.md) — performance/UX
- [`flowfile-mechanisms.md`](flowfile-mechanisms.md) — código real do Flowfile

Cada fase abaixo tem:
- **Objetivo, pré-requisitos, risco, esforço, valor entregue**
- **Entregáveis concretos** (arquivos a criar/modificar)
- **Critério de aceite** (checklist verificável)
- **Prompt para agente de IA** (auto-contido — copie e cole no Claude Code, Cursor, ou ferramenta similar)

## Princípios de ordenação

A ordem combina três critérios:

1. **Quick wins de UX primeiro** (Fases 1-3) — entregam valor visível ao usuário sem refatoração de runtime, criam momentum.
2. **Foundations observáveis antes de mudar comportamento** (Fase 4) — instrumentação que captura dados reais para validar heurísticas das fases seguintes.
3. **Refatorações de runtime depois das foundations** (Fases 5-7) — strategy resolver, worker, nós pesados.
4. **Governança e conectores por último** (Fases 8-10) — Dataset Registry, code export, conectores cloud.

## Princípios não-negociáveis

Aplicáveis a TODAS as fases. Inclua na sua leitura inicial de qualquer prompt abaixo:

1. **Shift NÃO usa Prefect.** Foi removido na migration `2026_04_16_b8c9d0e1f2a3_drop_prefect_flow_run_id.py`. Orquestração roda em [`shift-backend/app/orchestration/flows/dynamic_runner.py`](../shift-backend/app/orchestration/flows/dynamic_runner.py) (asyncio puro) + APScheduler in-process. Não introduza Prefect, Celery ou outro orquestrador externo.
2. **DuckDB-first como contrato de dados intermediários.** Não trocar para Polars LazyFrame. Quando precisar materializar, use `DuckDbReference`.
3. **Não copiar features sem copiar contrato operacional.** Cada nó novo precisa declarar `NODE_PROFILE` (shape, default_strategy, handles), retornar `output_summary` padrão, e ter testes com dados representativos.
4. **Single-process, multi-replica.** Backend roda single-worker uvicorn. Coordenação multi-replica via `SQLAlchemyJobStore` no Postgres. Não introduza estado em memória que quebre essa premissa.
5. **Migrations com Alembic, sem autogenerate cego.** Sempre revise.
6. **Frontend Next.js 16 + React 19.** Componentes shadcn/ui. Não trocar de framework.
7. **Código deve ser revisado por humano.** O agente entrega PR, não merge direto.

---

## Visão geral das 10 fases

| # | Fase | Pré-req | Risco | Esforço | Valor |
|---|---|---|---|---|---|
| 1 | UX: SSE leve + preview on-demand | — | Baixo | 3-5 dias | Alto |
| 2 | Nós tabulares simples (sort, sample, record_id, union) | — | Baixo | 4-6 dias | Alto |
| 3 | Nós analíticos (pivot, unpivot, text_to_rows) | Fase 2 | Médio | 5-7 dias | Alto |
| 4 | Observability foundations (instrumentação passiva) | — | Baixo | 4-6 dias | Médio (habilita tudo depois) |
| 5 | Strategy resolver ativo + parameter resolver + schema callback | Fase 4 | Médio | 6-9 dias | Alto |
| 6 | Worker subprocess para nós pesados | Fase 5 | Médio-Alto | 8-12 dias | Muito alto |
| 7 | Fuzzy match + cross_join com guardrails | Fase 6 | Médio | 5-7 dias | Alto (diferencial) |
| 8 | Dataset Registry + dataset triggers | Fase 5 | Médio | 8-12 dias | Muito alto |
| 9 | Code export (workflow → SQL/Python) + YAML save format | Fase 4 | Médio | 5-7 dias | Alto (governança) |
| 10 | Conectores cloud storage (S3/GCS) | Fase 5 | Médio | 4-6 dias por conector | Sob demanda |

Total estimado: 50-80 dias de engenharia, distribuíveis em paralelo a partir da Fase 4.

---

## Fase 1 — UX: SSE leve + preview on-demand

**Objetivo:** Reduzir latência percebida no editor e custo de renderização durante execução. Hoje o evento `node_complete` carrega output completo, e o frontend reconstrói estado a partir do array inteiro de eventos. É o pior gargalo de UX descrito em `benchmarking_flowfile_performance_shift.md §4`.

**Pré-requisitos:** nenhum.

**Risco:** Baixo. Não muda runtime, só protocolo SSE e renderização.

**Esforço estimado:** 3-5 dias.

**Valor entregue:** editor mais responsivo em workflows com muitos nós/loops; menos memória no browser; preview pago só quando o usuário pede.

### Entregáveis

- Backend
  - `shift-backend/app/orchestration/events.py` — payload de `node_complete` reduzido a `{node_id, status, row_count, schema_fingerprint, output_reference, duration_ms}`. Sem dados completos.
  - `shift-backend/app/api/v1/executions.py` — novo endpoint `GET /executions/{execution_id}/nodes/{node_id}/preview?limit=100&offset=0` que retorna primeiras N linhas do `DuckDbReference` do nó.
- Frontend
  - `shift-frontend/components/workflow/execution-panel.tsx` — `useMemo(() => buildNodeStates(events), [events])` para evitar rebuild em renders disparados por hover/resize.
  - Buscar preview via fetch on-demand quando o usuário seleciona um nó.

### Decisão sobre estado incremental — Zustand vs useMemo

**Escolha:** `useMemo` em vez de Zustand store.

**Por quê:**
- `zustand` não está em `shift-frontend/package.json` — adicionar dependência apenas para esse caso de uso quebra a regra de "não introduzir libs sem necessidade".
- `useMemo` resolve o problema prático: a função `buildNodeStates` é O(N) sobre o histórico de eventos, mas `useMemo([events])` só re-executa quando o array de events muda. Como o caller faz `setEvents([...prev, e])` a cada SSE, a memoização vale por evento, não por render.
- Migrar para Zustand exigiria reescrever (a) o ponto de consumo SSE, (b) o `setEvents` em todos os locais, e (c) o tipo `NodeExecState` exportado em `lib/workflow/execution-context.ts`. O ganho marginal não justifica a refatoração nos tamanhos de workflow atuais (50 nós + loop de 10 = 500 eventos; ~2ms por rebuild).
- Se métricas futuras (Profiler) mostrarem o painel renderizando > 16ms com >1000 eventos, reabrir a discussão e migrar para reducer incremental — o store fica trivial naquele momento.

### Critério de aceite

- [ ] Workflow com 50 nós + loop de 10 iterações: tela continua interativa durante run.
- [ ] Tamanho médio de evento SSE < 2 KB (verificar via `preview_network`).
- [ ] Preview de nó retorna em < 500ms para até 1000 linhas.
- [ ] Cancelamento da execução ainda funciona corretamente (eventos `node_canceled` chegam).
- [ ] Nenhum teste backend/frontend existente quebra.

### Prompt para agente

```
Implemente Fase 1 do plano em D:\Labs\shift-project\docs\flowfile-implementation-plan.md.

Contexto obrigatório (leia primeiro):
- D:\Labs\shift-project\docs\flowfile-implementation-plan.md (seção "Princípios não-negociáveis" e "Fase 1")
- D:\Labs\shift-project\benchmarking_flowfile_performance_shift.md seções 4 e 6
- D:\Labs\shift-project\shift-backend\app\orchestration\flows\dynamic_runner.py (entender estrutura de eventos atual)
- D:\Labs\shift-project\shift-frontend\components\workflow\execution-panel.tsx (componente atual)

Tarefa:
1. Reduzir payload do evento node_complete no backend para conter apenas:
   {node_id, status, row_count, schema_fingerprint, output_reference, duration_ms, error?}
   Não incluir dados do output. output_reference deve ser um identificador (DuckDbReference serializado ou ID).

2. Criar endpoint GET /api/v1/executions/{execution_id}/nodes/{node_id}/preview que aceita
   query params limit (default 100, max 1000) e offset (default 0). Retorna primeiras N linhas
   do output do nó. Usar a referência DuckDB já persistida pelo runner. Responder 404 se o nó
   não tiver rodado ainda. Auth padrão do projeto.

3. No frontend, criar shift-frontend/components/workflow/execution-store.ts usando Zustand
   (já é dep do projeto). Estrutura: { byNodeId: Record<string, NodeExecState>, order: string[] }.
   Eventos do SSE atualizam só o nó afetado. Substituir o uso atual de array de eventos +
   useMemo de buildNodeStates pela leitura direta do store.

4. Quando o usuário selecionar um nó no editor, fazer fetch ao novo endpoint de preview e
   armazenar em estado local do painel (não no store global). Mostrar loading state.

5. Manter retrocompatibilidade do tipo do evento — campo opcional `legacy_output` removido
   apenas após confirmar que o frontend não depende dele em outros lugares.

Critério de aceite:
- Workflow com 50 nós + loop de 10 iterações continua interativo durante run.
- Tamanho médio de evento SSE inspecionado via preview_network < 2 KB.
- Preview de nó retorna em < 500ms para 1000 linhas.
- Testes existentes em shift-backend/tests/test_dynamic_runner.py passam.
- Verificar que cancelamento ainda emite node_canceled corretamente.

Após implementar, abra o frontend no preview do Claude (preview_start em
shift-frontend), execute um workflow de exemplo, e tire screenshot do painel
mostrando estado dos nós + preview de um nó selecionado. Reporte tamanhos de
payload via preview_network.

NÃO mexa em runtime de execução, só em protocolo de eventos e renderização.
Não introduza Prefect/Celery (não usados no Shift). Manter DuckDbReference como
contrato.
```

---

## Fase 2 — Nós tabulares simples

**Objetivo:** Adicionar 4 nós de baixo risco que faltam no Shift: `sort`, `sample`, `record_id`, `union`. Implementação direta via SQL DuckDB.

**Pré-requisitos:** nenhum.

**Risco:** Baixo. Padrão DuckDB já estabelecido em [`shift-backend/app/services/workflow/nodes/`](../shift-backend/app/services/workflow/nodes/).

**Esforço estimado:** 4-6 dias (1-1.5 dias por nó).

**Valor entregue:** elimina 4 lacunas funcionais do catálogo recorrentes; usuário não precisa mais cair em `sql_script` para fazer ordenação ou amostragem.

### Entregáveis

Para cada nó: `sort`, `sample`, `record_id`, `union`:

- `shift-backend/app/services/workflow/nodes/{nome}_node.py` — processor com classificação `NODE_PROFILE`.
- `shift-backend/app/schemas/workflow.py` — Pydantic config schema.
- `shift-backend/tests/test_{nome}_node.py` — testes com dados representativos.
- `shift-frontend/components/workflow/nodes/{nome}-config.tsx` — UI de configuração.
- `shift-frontend/components/workflow/node-library.tsx` — registrar no menu.

### Critério de aceite

- [ ] Cada nó implementa contrato padrão (input handles, output handles, output_summary com row_count_in/out, warnings).
- [ ] `NODE_PROFILE` declarado para todos os 4 (ver `benchmarking_flowfile_nodes_shift.md §7`).
- [ ] `sort` aceita lista de colunas com direção e nulls first/last.
- [ ] `sample` suporta modos `first_n`, `random` (com seed obrigatória em workflows publicados), `percent`.
- [ ] `record_id` suporta `partition_by` opcional e `order_by`. Warning quando `order_by` ausente.
- [ ] `union` suporta `by_name` e `by_position`, modo `strict_schema` default true, opcional `source_column`.
- [ ] Cobertura de testes ≥ 80% nos novos arquivos.

### Prompt para agente

```
Implemente Fase 2 do plano em D:\Labs\shift-project\docs\flowfile-implementation-plan.md.

Contexto obrigatório (leia primeiro):
- D:\Labs\shift-project\docs\flowfile-implementation-plan.md (Princípios não-negociáveis e Fase 2)
- D:\Labs\shift-project\benchmarking_flowfile_nodes_shift.md seções 4.1 a 4.4
- Um nó existente como referência de padrão: leia
  D:\Labs\shift-project\shift-backend\app\services\workflow\nodes\filter_node.py
  e D:\Labs\shift-project\shift-backend\app\services\workflow\nodes\aggregator_node.py
  para entender contrato (entrada DuckDbReference, saída DuckDbReference, eventos, summary).

Tarefa: implementar 4 nós novos seguindo o padrão DuckDB existente.

Para cada nó (sort, sample, record_id, union):

1. Backend:
   - shift-backend/app/services/workflow/nodes/{nome}_node.py com classe processor.
   - Declarar no início do arquivo:
     NODE_PROFILE = {
       "node_type": "<nome>",
       "shape": "narrow|wide",  # ver benchmarking_flowfile_nodes_shift §7
       "default_strategy": "local_thread",
       "input_handles": ["input"],   # union: ["input_1","input_2",...]
       "output_handles": ["success"],
     }
   - Usar SQL DuckDB conforme exemplos em benchmarking_flowfile_nodes_shift.md §4.1-4.4.
   - Output sempre DuckDbReference materializado.
   - Retornar output_summary com row_count_in, row_count_out, warnings[].

2. Schema Pydantic em shift-backend/app/schemas/workflow.py — seguir padrão dos schemas
   já existentes (ex: NodeFilterConfig).

3. Testes em shift-backend/tests/test_{nome}_node.py com pytest. Casos mínimos:
   - happy path
   - input vazio
   - colunas faltando
   - parâmetros inválidos (deve falhar com erro claro)
   - para sample: seed reproduz mesmo resultado
   - para union: modo strict_schema falha com schemas diferentes
   - para record_id: sem order_by emite warning

4. Frontend:
   - shift-frontend/components/workflow/nodes/{nome}-config.tsx seguindo padrão de
     filter-config.tsx ou aggregator-config.tsx (ler para referência).
   - Componentes shadcn/ui (Input, Select, Switch já no projeto).

5. Registrar nos catálogos:
   - shift-backend/app/services/workflow/processor_registry.py (ou equivalente)
   - shift-frontend/components/workflow/node-library.tsx

Específicos por nó:

SORT (wide, lazy):
- Aceita lista de {column, direction: 'asc'|'desc', nulls: 'first'|'last'}
- Limite opcional para top-N (LIMIT ao final do SQL)
- SQL: SELECT * FROM input ORDER BY ... [LIMIT n]

SAMPLE (narrow):
- Modos: first_n (LIMIT), random (USING SAMPLE reservoir(n ROWS) REPEATABLE(seed)), percent
- Seed obrigatória quando modo=random e workflow está publicado (verificar via flag is_published)
- Registrar modo + seed no output_summary

RECORD_ID (wide):
- Adiciona coluna sequencial. Config: {output_column, start_at, order_by[], partition_by?}
- SQL: SELECT row_number() OVER (PARTITION BY ... ORDER BY ...) + offset AS record_id, *
- Sem order_by → warning "non-deterministic without order_by"

UNION (narrow, multi-input):
- N inputs (mínimo 2, sem máximo definido). Modo by_name (UNION ALL BY NAME) ou by_position.
- strict_schema=true falha quando colunas diferem.
- allow_missing_columns=false default. Quando true, fazer SELECT explícito com NULLs.
- source_column opcional adiciona coluna identificando origem.

Critério de aceite:
- 4 nós backend + 4 configs frontend + testes passando.
- Workflow de exemplo end-to-end usando os 4 nós roda sem erro.
- Cobertura ≥ 80% nos novos arquivos.

NÃO copie da implementação Polars do Flowfile — Shift é DuckDB-first.
Usar bytes Polars/LazyFrame quebra o contrato.
```

---

## Fase 3 — Nós analíticos

**Objetivo:** Adicionar `pivot`, `unpivot`, `text_to_rows`. Operações comuns em ETL analítico que hoje exigem SQL manual.

**Pré-requisitos:** Fase 2 (mesmo padrão de contrato e SQL DuckDB).

**Risco:** Médio. `pivot` exige descobrir valores únicos (query separada antes da geração de SQL); `text_to_rows` pode multiplicar linhas significativamente.

**Esforço estimado:** 5-7 dias.

**Valor entregue:** preparação de planilhas largas, normalização de campos multi-valorados, transformação wide↔long visível na UI.

### Entregáveis

Para cada nó: `pivot`, `unpivot`, `text_to_rows`:

- Mesma estrutura da Fase 2 (backend node + schema + testes + frontend config + registro).
- Em `pivot`: query separada para descobrir valores únicos com `max_pivot_values=200` default.
- Em `unpivot`: usar `UNPIVOT` nativo do DuckDB se versão suportar; fallback com `UNION ALL`.
- Em `text_to_rows`: estimativa de multiplicação no preview.

### Critério de aceite

- [ ] `pivot` falha com mensagem clara acima de `max_pivot_values`.
- [ ] `unpivot` aceita seleção por tipo (`all_numeric`, `all_string`).
- [ ] `text_to_rows` registra `row_count_in` e `row_count_out` no summary.
- [ ] Documentação de cada nó em `docs/users/nodes/{nome}.md` com screenshot e exemplo.

### Prompt para agente

```
Implemente Fase 3 do plano em D:\Labs\shift-project\docs\flowfile-implementation-plan.md.

Contexto obrigatório:
- D:\Labs\shift-project\docs\flowfile-implementation-plan.md (Princípios + Fase 3)
- D:\Labs\shift-project\benchmarking_flowfile_nodes_shift.md seções 4.5, 4.6, 4.7
- Confirme que a Fase 2 foi mergeada (4 nós: sort, sample, record_id, union já existem em
  shift-backend/app/services/workflow/nodes/). Caso não esteja, pause e avise.

Tarefa: implementar 3 nós analíticos seguindo o mesmo padrão da Fase 2.

PIVOT (wide, eager):
- Config: {index_columns[], pivot_column, value_column, aggregations[], max_pivot_values: 200}
- Implementação em duas queries:
  1. SELECT DISTINCT pivot_column FROM input LIMIT max_pivot_values+1
     Se retornar > max_pivot_values, falhar com erro claro.
  2. Gerar SQL com SUM(CASE WHEN pivot_column = 'A' THEN value_column ELSE 0 END) AS A_<agg>
     para cada valor único e cada agregação.
- Sanitizar nomes de colunas (remover caracteres inválidos, lidar com duplicatas).
- Persistir mapping {valor_original: nome_coluna_gerada} no summary.

UNPIVOT (wide, lazy):
- Config: {index_columns[], value_columns[] | by_type, variable_column_name, value_column_name, cast_value_to?}
- Tentar UNPIVOT nativo do DuckDB primeiro:
    SELECT * FROM input UNPIVOT (val FOR var IN (col1, col2, col3))
- Fallback se versão não suportar: UNION ALL gerado.
- Validar que tipos das colunas value_columns são compatíveis ou fazer cast explícito.

TEXT_TO_ROWS (wide):
- Config: {column_to_split, delimiter, output_column?, keep_empty: false, trim_values: true,
            max_splits?, max_output_rows?}
- SQL: SELECT input.* EXCLUDE (col), UNNEST(string_split(col, delim)) AS output
- Se trim_values, fazer trim na expressão.
- Se keep_empty=false, filtrar valores vazios.
- Estimar multiplicação média em preview e registrar em output_summary.
- max_output_rows aplicado em modo preview para evitar explosão.

Para todos:
1. Backend node + schema + testes (mesmos critérios da Fase 2).
2. Frontend config component.
3. Registro nos catálogos.
4. Documentação em docs/users/nodes/{nome}.md com:
   - Descrição do nó
   - Screenshot do config (capturar via preview)
   - Exemplo de input/output
   - Tabela de configurações
   - Notas de performance e limites

Critério de aceite:
- 3 nós + configs frontend + testes + docs.
- Workflow de exemplo combinando pivot + unpivot end-to-end roda corretamente
  (deve ser idempotente: pivot seguido de unpivot retorna ao formato original).
- text_to_rows com input de 1k linhas e fanout médio 5x produz 5k linhas com row_count
  correto no summary.

DuckDB-first. Não usar Polars.
```

---

## Fase 4 — Observability foundations

**Objetivo:** Instrumentação que captura sinais reais antes de mudar comportamento. Três artefatos passivos: `ExecutionPlanSnapshot`, `NodeExecutionProfile`, `StrategyDecision em modo observação`. Mais o `parameter_resolver ${var}` recursivo (já útil sozinho, agora com fail-fast). Recomendação `benchmarking_flowfile_shift.md §11 Fase 0` + §9.

**Pré-requisitos:** nenhum (pode rodar em paralelo a Fases 1-3).

**Risco:** Baixo. Tudo aqui é leitura/log, não muda decisão de execução. Exceto o parameter_resolver que altera comportamento — mas em direção a fail-fast (mais seguro).

**Esforço estimado:** 4-6 dias.

**Valor entregue:** dados reais para validar heurísticas das Fases 5-6; usuários veem erro claro de parâmetro ausente antes de qualquer side effect.

### Entregáveis

- `shift-backend/app/orchestration/flows/execution_plan.py` — builder do snapshot.
  - `ExecutionPlanSnapshot` Pydantic: `{execution_id, levels[], node_count, edge_count, predicted_strategies}`.
  - Persistir em coluna JSON em `workflow_executions` ou tabela dedicada `workflow_execution_plans`.
- `shift-backend/app/orchestration/flows/node_profile.py` — registry imutável `NODE_EXECUTION_PROFILE` mapeando cada `node_type` para `{shape: narrow|wide|io|output|control, default_strategy}`.
- `shift-backend/app/orchestration/flows/strategy_observer.py` — função `observe_strategy(node, state)` que **só calcula e loga** uma `StrategyDecision`. Não toma decisão real. Emite evento `node_strategy_observed` no SSE.
- `shift-backend/app/orchestration/flows/parameter_resolver.py` — porte do mecanismo descrito em [`flowfile-mechanisms.md §4`](flowfile-mechanisms.md). Recursivo em Pydantic BaseModel/dict/list. Fail-fast antes do primeiro nó rodar.

### Critério de aceite

- [ ] Após qualquer execução, é possível ler o `ExecutionPlanSnapshot` via `GET /executions/{id}/plan`.
- [ ] Workflow com `${var}` não definido falha com mensagem `Unresolved parameter references: ['x', 'y']` antes do primeiro nó executar.
- [ ] Logs estruturados mostram `strategy_observed` por nó com `{strategy, reason, shape, cache_hit}` — pronto para análise em SQL/Grafana.
- [ ] `NODE_EXECUTION_PROFILE` tem entrada para todos os ~33 node types existentes.

### Prompt para agente

```
Implemente Fase 4 do plano em D:\Labs\shift-project\docs\flowfile-implementation-plan.md.

Contexto obrigatório:
- D:\Labs\shift-project\docs\flowfile-implementation-plan.md (Princípios + Fase 4)
- D:\Labs\shift-project\benchmarking_flowfile_shift.md seções 4.1, 4.2, 5.1, 9
- D:\Labs\shift-project\docs\flowfile-mechanisms.md §1, §4, §6
- D:\Labs\shift-project\shift-backend\app\orchestration\flows\dynamic_runner.py (entender topologia atual)

Tarefa: criar 4 artefatos de observabilidade SEM mudar a lógica de decisão do runner.

ARTEFATO 1: NODE_EXECUTION_PROFILE
Arquivo: shift-backend/app/orchestration/flows/node_profile.py

Mapear cada node_type existente para:
  {
    "shape": "narrow" | "wide" | "io" | "output" | "control",
    "default_strategy": "local_thread" | "data_worker" | "io_thread"
  }

Liste todos os ~33 nós existentes em shift-backend/app/services/workflow/nodes/ e
classifique. Use as definições do Flowfile em
D:\Labs\Flowfile\flowfile_core\flowfile_core\configs\node_store\nodes.py como referência.

Exemplo:
NODE_EXECUTION_PROFILE: dict[str, dict] = {
    "filter": {"shape": "narrow", "default_strategy": "local_thread"},
    "join": {"shape": "wide", "default_strategy": "data_worker"},
    "sql_database": {"shape": "io", "default_strategy": "io_thread"},
    "load": {"shape": "output", "default_strategy": "io_thread"},
    "if_node": {"shape": "control", "default_strategy": "local_thread"},
    # ...
}

ARTEFATO 2: ExecutionPlanSnapshot
Arquivo: shift-backend/app/orchestration/flows/execution_plan.py

Pydantic model:
class ExecutionPlanSnapshot(BaseModel):
    execution_id: UUID
    plan_version: int = 1
    levels: list[list[str]]  # topological levels com node_ids
    node_count: int
    edge_count: int
    skip_nodes: list[str] = []  # nós desabilitados
    predicted_strategies: dict[str, dict]  # {node_id: {strategy, shape, reason}}
    created_at: datetime

Função build_snapshot(graph, execution_id) -> ExecutionPlanSnapshot.
Chamar logo após a topological sort em dynamic_runner.py.
Persistir: adicionar coluna JSON `plan_snapshot` em workflow_executions
(criar migration alembic).

Endpoint GET /api/v1/executions/{execution_id}/plan que retorna o snapshot.

ARTEFATO 3: StrategyObserver (modo passivo)
Arquivo: shift-backend/app/orchestration/flows/strategy_observer.py

@dataclass
class StrategyDecision:
    should_run: bool
    strategy: str  # "skip" | "local_thread" | "data_worker" | "io_thread"
    reason: str   # "output_node" | "cache_hit" | "narrow_default" | ...

def observe_strategy(node, state, profile, run_mode) -> StrategyDecision: ...

Lógica baseada no executor.py do Flowfile (ver flowfile-mechanisms.md §1).
Adaptado: enums diferentes do Flowfile (sem REMOTE/LOCAL_WITH_SAMPLING — Shift não tem).

Plugar em dynamic_runner.py: ANTES de executar cada nó, chamar observe_strategy
e emitir evento SSE node_strategy_observed com a decisão. NÃO mudar comportamento real.

Modo passivo permite coletar dados e validar a heurística antes da Fase 5 ativá-la.

ARTEFATO 4: Parameter Resolver fail-fast
Arquivo: shift-backend/app/orchestration/flows/parameter_resolver.py

Porte direto do código em flowfile-mechanisms.md §4. Adaptar:
- Pydantic v2 (model_fields em vez de __fields__)
- Função apply_parameters_in_place(workflow_definition, params) que percorre todos os
  node configs antes da execução.
- Validação fail-fast: se há ${var} não resolvido, raise ParameterError("Unresolved
  parameter references: {names}") ANTES de qualquer side effect.
- Não pre-resolver dentro de sql_script body — eles têm bindings runtime intencional.
  Adicionar lista PARAMETER_RESOLVER_SKIP_FIELDS por node_type.

Plugar em dynamic_runner.py: chamar resolve antes do loop de execução. Capturar exceção
e marcar execution como failed com mensagem clara.

Critério de aceite:
- GET /executions/{id}/plan retorna snapshot estruturado após qualquer execução.
- Eventos node_strategy_observed aparecem no SSE durante execução (verificar via
  preview_eval com curl).
- Workflow com ${INEXISTENTE} falha em < 100ms com mensagem clara, sem ter rodado nenhum nó.
- NODE_EXECUTION_PROFILE cobre todos os node_types existentes (verificar via teste:
  for node_type in PROCESSOR_REGISTRY: assert node_type in NODE_EXECUTION_PROFILE).
- Testes em shift-backend/tests/ para cada artefato.

NÃO mudar decisão real do runner ainda — isso é Fase 5.
```

---

## Fase 5 — Strategy resolver ativo + schema callback básico + hash semântico

**Objetivo:** Promover o observador da Fase 4 a decisor real. Adicionar schema callback básico (predicted schema sem rodar) para 5 nós-chave. Implementar hash semântico para `sql_database`, `join`, `lookup`, `aggregator` — base para cache correto.

**Pré-requisitos:** Fase 4 (sem ela, decisão ativa não tem dados para se basear).

**Risco:** Médio. Decisão ativa muda quem-roda-quando. Hash semântico errado é classe perigosa de bug. Por isso a Fase 4 captura dados antes.

**Esforço estimado:** 6-9 dias.

**Valor entregue:** runner mais previsível e testável; UI mostra colunas downstream antes de rodar; base para cache de transformação.

### Entregáveis

- `shift-backend/app/orchestration/flows/strategy_resolver.py` — promove `StrategyObserver` da Fase 4 a decisor real.
- `shift-backend/app/services/workflow/schema_inference/` (novo módulo) — função `predict_output_schema(node_type, config, input_schemas)` para `sql_database`, `mapper`, `filter`, `join`, `select`. Retorna `list[FieldDescriptor]` ou `None` (schema desconhecido).
- `shift-backend/app/services/workflow/semantic_hash.py` — `compute_semantic_hash(config, input_fingerprints, version=1)` excluindo campos runtime (`cache_enabled`, `cache_ttl_seconds`).
- Endpoint `GET /api/v1/workflows/{id}/nodes/{nid}/predicted-schema` — frontend chama on-edit.
- Frontend: badge "coluna `X` não disponível" em configs que referenciam coluna.

### Critério de aceite

- [ ] Workflow com 100 runs idênticas produz mesmo hash para todos os nós cacheáveis (verificável em log).
- [ ] Runner respeita decisão do `strategy_resolver` (skip se cache hit; force run se `force_refresh=true`).
- [ ] Editor mostra warning visual quando filtro referencia coluna que upstream não produz mais.
- [ ] Testes parametrizados para matriz de cenários: cache hit, cache miss, never_ran, output_node, force_refresh, narrow_default, wide_default.

### Prompt para agente

```
Implemente Fase 5 do plano em D:\Labs\shift-project\docs\flowfile-implementation-plan.md.

Contexto obrigatório:
- D:\Labs\shift-project\docs\flowfile-implementation-plan.md (Princípios + Fase 5)
- D:\Labs\shift-project\benchmarking_flowfile_shift.md §4.2 e §5.2
- D:\Labs\shift-project\docs\flowfile-mechanisms.md §1, §5
- Confirme Fase 4 mergeada: arquivos node_profile.py, execution_plan.py,
  strategy_observer.py, parameter_resolver.py em shift-backend/app/orchestration/flows/.

Tarefa em 3 partes:

PARTE 1: Promover StrategyObserver a StrategyResolver ativo
Arquivo: shift-backend/app/orchestration/flows/strategy_resolver.py

Mesma assinatura do observer da Fase 4, mas agora dynamic_runner.py CONSULTA a decisão e
respeita:
- strategy=SKIP: pular nó, marcar como skipped no result, ainda emitir eventos.
- strategy=LOCAL_THREAD: comportamento atual (asyncio.to_thread).
- strategy=DATA_WORKER: por enquanto fallback para LOCAL_THREAD com TODO marker
  (worker real é Fase 6).
- strategy=IO_THREAD: igual a LOCAL_THREAD por enquanto, semantica futura.

Adicionar matriz de testes em shift-backend/tests/test_strategy_resolver.py cobrindo:
- output_node sempre roda
- force_refresh=True invalida cache
- cache_hit retorna SKIP
- cache_miss + node cacheable retorna estratégia padrão
- nunca rodou retorna estratégia padrão
- pinned/disabled retorna SKIP

PARTE 2: Schema inference para 5 nós
Arquivo: shift-backend/app/services/workflow/schema_inference/__init__.py

class FieldDescriptor(BaseModel):
    name: str
    data_type: str  # SQL type
    nullable: bool

def predict_output_schema(
    node_type: str,
    config: dict,
    input_schemas: dict[str, list[FieldDescriptor]]  # handle -> schema
) -> list[FieldDescriptor] | None: ...

Implementar para:
- sql_database: executar EXPLAIN ou SELECT ... LIMIT 0 contra a connection. Cache schema
  por (connection_id + query_hash).
- mapper: declarado pelo config (lista de output_columns).
- filter: passa input adiante (mesmas colunas).
- join: merge dos dois schemas com prefix/conflict resolution conforme config.
- select: subset declarado.

Para outros node_types, retornar None (schema desconhecido até executar).

Endpoint GET /api/v1/workflows/{workflow_id}/nodes/{node_id}/predicted-schema que
retorna o predicted schema baseado no estado salvo do workflow.

Frontend:
- Em filter-config, mapper-config, join-config: chamar endpoint quando o nó é selecionado.
- Mostrar colunas disponíveis em dropdown.
- Badge vermelho "coluna 'X' não está mais disponível" quando config referencia coluna
  que upstream não produz.

PARTE 3: Hash semântico
Arquivo: shift-backend/app/services/workflow/semantic_hash.py

def compute_semantic_hash(
    config: dict,
    input_fingerprints: list[str],
    algo_version: int = 1
) -> str:
    \"\"\"Hash determinístico que ignora campos runtime-only.\"\"\"

Excluir RUNTIME_ONLY_FIELDS = {"cache_enabled", "cache_ttl_seconds", "force_refresh"}.
Para cada node_type, lista de fields excluídos pode ser estendida — definir em
NODE_EXECUTION_PROFILE (Fase 4).

Para sql_database: connection identificada por ID, NÃO pela connection_string bruta.
Para outros nós com referência a connection_id, mesmo padrão.

Aplicar a sql_database, join, lookup, aggregator (os 4 onde cache vale mais).

Persistir hash em NodeRunState (já existe estrutura na Fase 4 via execution_plan).
StrategyResolver usa hash para decidir cache_hit.

Critério de aceite:
- 100 runs idênticas produzem mesmo hash em sql_database, join, lookup, aggregator
  (teste: rodar workflow 10x, agregar hashes do banco, deve haver exatamente 1 hash distinto
  por nó).
- Editor mostra warning visual quando coluna inexistente referenciada.
- Strategy resolver é hot path — adicionar timing, deve adicionar < 5ms por nó.
- Cobertura de testes ≥ 80% nos novos arquivos.

NÃO implemente worker remoto — DATA_WORKER é fallback nesta fase.
NÃO confie no hash para skip automático em nós não-cacheable. Comece conservador.
```

---

## Fase 6 — Worker subprocess para nós pesados

**Objetivo:** Isolar `join`, `lookup`, `aggregator`, `deduplication` em subprocesso quando volume é alto. Reduz risco de OOM derrubar FastAPI inteiro. Recomendação `benchmarking_flowfile_performance_shift.md §5` + `benchmarking_flowfile_shift.md §4.3`.

**Pré-requisitos:** Fase 5 (strategy resolver é quem decide quando despachar para worker).

**Risco:** Médio-Alto. Comunicação inter-processo, cancelamento, timeout, ciclo de vida de subprocesso.

**Esforço estimado:** 8-12 dias.

**Valor entregue:** plataforma resiste a operações que explodem memória; tela continua respondendo durante runs pesados; cancelamento mais efetivo.

### Entregáveis

- `shift-backend/app/orchestration/data_worker/` (novo módulo)
  - `runtime.py` — `DataWorkerRuntime.submit(task) → task_id`, `get_status(task_id)`, `fetch_result(task_id)`, `cancel(task_id)`.
  - `subprocess_handler.py` — script `python -m shift_data_worker` que recebe stdin JSON, executa node, escreve resultado em DuckDB, retorna referência.
  - `task_registry.py` — dict in-memory + lock; chave `task_id`; valores `{status, started_at, pid, output_ref, error}`.
- Migrações no `dynamic_runner.py` — quando strategy resolver retorna `DATA_WORKER`, despacha via runtime em vez de `asyncio.to_thread`.
- Adaptar processors `join_node.py`, `lookup_node.py`, `aggregator_node.py`, `deduplication_node.py` para serem invocáveis em subprocesso (sem dependência de banco da app — só DuckDB).

### Critério de aceite

- [ ] Join de 10M × 1M registros não derruba o FastAPI. Tela continua interativa.
- [ ] Cancelamento via UI termina o subprocesso em < 2s.
- [ ] Runner detecta crash do subprocesso (exit code != 0) e marca nó como failed.
- [ ] Métrica `data_worker_active_tasks` exposta. APScheduler limpa tasks órfãs (> 30min sem update).
- [ ] Testes de integração com workload realista (10M rows).

### Prompt para agente

```
Implemente Fase 6 do plano em D:\Labs\shift-project\docs\flowfile-implementation-plan.md.

Contexto obrigatório:
- D:\Labs\shift-project\docs\flowfile-implementation-plan.md (Princípios + Fase 6)
- D:\Labs\shift-project\benchmarking_flowfile_shift.md §4.3
- D:\Labs\shift-project\benchmarking_flowfile_performance_shift.md §5
- D:\Labs\shift-project\docs\flowfile-mechanisms.md §2 (protocolo HTTP do Flowfile —
  ADAPTAR, não copiar — Shift não usa serialização Polars)
- Confirme Fase 5 mergeada (strategy_resolver.py decidindo DATA_WORKER).
- Leia os processors atuais:
  shift-backend/app/services/workflow/nodes/{join,lookup,aggregator,deduplication}_node.py

Tarefa: criar runtime de worker local subprocessado. NÃO rede, NÃO HTTP — subprocess
direto via multiprocessing.

ARQUITETURA:
- Cada task recebe: {task_id, node_type, config, input_refs (DuckDbReference[]), timeout_s}.
- Subprocess script executa o processor existente do nó passando inputs como
  caminhos de arquivo DuckDB.
- Output: DuckDbReference materializado em arquivo temporário do execution.
- Comunicação:
  - Submit: pai cria pipe, dispara subprocess, escreve task em stdin como JSON, fecha stdin.
  - Status: pai lê linhas de stdout (formato JSON-lines: {"event": "progress", ...} ou
    {"event": "done", "output_ref": ...}).
  - Cancel: SIGTERM seguido de SIGKILL após 2s.
  - Crash: detectar via exit code != 0 e stderr.
- Lock-free para reads de status, lock para writes (uso de threading.RLock).

ENTREGÁVEIS:

1. shift-backend/app/orchestration/data_worker/runtime.py
   class DataWorkerRuntime:
       def __init__(self, max_concurrent: int = 4): ...
       async def submit(self, task: WorkerTask) -> str: ...  # retorna task_id
       async def get_status(self, task_id: str) -> WorkerStatus: ...
       async def fetch_result(self, task_id: str) -> DuckDbReference: ...
       async def cancel(self, task_id: str) -> bool: ...

   class WorkerTask(BaseModel):
       task_id: UUID
       execution_id: UUID
       node_id: str
       node_type: str
       config: dict
       input_refs: dict[str, DuckDbReference]  # handle -> ref
       timeout_seconds: int = 600

2. shift-backend/app/orchestration/data_worker/subprocess_handler.py
   Script standalone (entry point: python -m shift_backend.data_worker).
   - Lê WorkerTask de stdin como JSON.
   - Resolve processor pelo node_type a partir do PROCESSOR_REGISTRY existente.
   - Para cada input_ref, abre conexão DuckDB read-only.
   - Executa processor com config + inputs, escreve resultado em arquivo temporário.
   - Emite progresso por stdout (JSON-lines) opcional.
   - Emite final {"event": "done", "output_ref": {...}} ou {"event": "error", "message": ...}.
   - Captura SIGTERM e cleanup.

3. shift-backend/app/orchestration/data_worker/task_registry.py
   Dict in-memory: {task_id: {status, started_at, pid, output_ref, error}}.
   Cleanup periódico via APScheduler: remove tasks finalizadas > 1h, mata tasks > 30min sem update.

4. shift-backend/app/orchestration/flows/dynamic_runner.py
   Quando strategy_resolver retorna DATA_WORKER:
   - submit ao runtime
   - aguardar com timeout, cancelar se exceder
   - emit eventos node_progress baseados em stdout do worker
   - fetch_result e injetar como output

5. Adaptar processors {join,lookup,aggregator,deduplication}_node.py:
   - Garantir que NÃO dependem de session SQLAlchemy.
   - Receber inputs como DuckDbReference (caminho + dataset/table).
   - Devolver DuckDbReference materializado.
   - Já devem estar próximo disso — verificar e ajustar.

6. Telemetria:
   - Métrica data_worker_active_tasks (gauge)
   - Métrica data_worker_task_duration (histogram por node_type)
   - Métrica data_worker_oom_kills (counter — exit code 137)

Critério de aceite:
- Test de stress: workflow com join 10M × 1M rows. FastAPI continua respondendo
  (medir latência do GET /health durante execução: < 100ms p99).
- Cancelamento UI termina subprocess em < 2s.
- Crash de subprocess (matar -9 manualmente) é detectado e nó marcado como failed
  com mensagem "Worker process crashed (exit code 137 = OOM kill)".
- Tasks órfãs (> 30min sem update) são limpas pelo APScheduler.
- Multi-replica: cada réplica tem seu runtime. Coordenação via Postgres (já existente
  via SQLAlchemyJobStore).

NÃO usar HTTP/WebSocket entre core e worker — subprocess local é mais simples e
suficiente. NÃO usar Polars LazyFrame como contrato — Shift é DuckDB-first.
NÃO substituir asyncio.to_thread para nós leves (LOCAL_THREAD continua igual).
```

---

## Fase 7 — Fuzzy match + cross_join com guardrails

**Objetivo:** Adicionar dois nós pesados de alto valor diferencial. Ambos exigem worker (Fase 6) + guardrails fortes contra explosão.

**Pré-requisitos:** Fase 6 (`DATA_WORKER` real funcionando).

**Risco:** Médio. Algoritmos pesados, mas confinados ao worker. Guardrails impedem cardinalidade descontrolada.

**Esforço estimado:** 5-7 dias.

**Valor entregue:** caso de uso clássico em ERPs legados (deduplicar fornecedores/clientes com nomes inconsistentes); produto cartesiano controlado para combinações.

### Entregáveis

- `shift-backend/app/services/workflow/nodes/fuzzy_match_node.py` — sempre `DATA_WORKER`. Suporta `levenshtein`, `jaro_winkler`, `token_set_ratio` via `rapidfuzz`. Exige `blocking_keys` quando ambos inputs > 10k linhas.
- `shift-backend/app/services/workflow/nodes/cross_join_node.py` — guardrail `MAX_CROSS_JOIN_ROWS=10M` configurável. Estimar `left_count * right_count` antes de executar.
- Frontend: configs com preview de candidatos (fuzzy) e estimativa de output (cross_join).

### Critério de aceite

- [ ] Fuzzy match de 100k × 50k registros completa em < 5 min usando blocking key.
- [ ] Fuzzy match sem blocking key e ambos > 10k linhas falha com erro claro indicando o limite.
- [ ] Cross join acima do limite falha antes de executar com mensagem clara `Estimated 50M rows exceeds MAX_CROSS_JOIN_ROWS=10M`.
- [ ] Output do fuzzy match inclui colunas `match_score` e `match_method`.

### Prompt para agente

```
Implemente Fase 7 do plano em D:\Labs\shift-project\docs\flowfile-implementation-plan.md.

Contexto obrigatório:
- D:\Labs\shift-project\benchmarking_flowfile_nodes_shift.md §4.8 e §4.9
- D:\Labs\shift-project\docs\flowfile-implementation-plan.md (Princípios + Fase 7)
- Confirme Fase 6 mergeada: DataWorkerRuntime funciona end-to-end.
- Adicione dependência rapidfuzz>=3.0 ao pyproject.toml.

Tarefa: implementar 2 nós que SEMPRE rodam em DATA_WORKER.

FUZZY MATCH:
shift-backend/app/services/workflow/nodes/fuzzy_match_node.py

NODE_PROFILE = {
    "shape": "wide", "default_strategy": "data_worker",
    "input_handles": ["left", "right"], "output_handles": ["matches"]
}

Config:
- left_columns[], right_columns[]: colunas a comparar (mesmo número)
- algorithm: levenshtein | jaro_winkler | token_set_ratio
- threshold: 0.0-1.0 (mínimo de score)
- blocking_keys: list[{left, right}] (opcional mas obrigatório se ambos inputs > 10k rows)
- max_matches_per_left: int default 1
- output_score_column: str default "match_score"

Implementação:
1. Estimar tamanhos: SELECT COUNT(*) em cada input.
2. Se left_count > 10k e right_count > 10k e blocking_keys vazio → ERRO claro.
3. Se blocking_keys: criar tabela bloqueada com INNER JOIN nas chaves de bloqueio.
4. Para cada par bloqueado, calcular score via rapidfuzz.
5. Filtrar por threshold.
6. Para cada left, manter top max_matches_per_left.
7. Output: schema = left.* + right.* + match_score + match_method.

Sempre rodar em DATA_WORKER (strategy resolver respeita default_strategy do PROFILE).

CROSS JOIN:
shift-backend/app/services/workflow/nodes/cross_join_node.py

NODE_PROFILE = {
    "shape": "wide", "default_strategy": "data_worker",
    "input_handles": ["left", "right"], "output_handles": ["product"]
}

Config:
- left_columns[]: subset de colunas do left (obrigatório, evitar puxar tudo)
- right_columns[]: subset do right
- max_rows: int default 10M (configurável via env SHIFT_CROSS_JOIN_MAX_ROWS)

Implementação:
1. SELECT COUNT(*) em ambos inputs.
2. Estimar = left_count * right_count.
3. Se > max_rows → ERRO `Estimated {N} rows exceeds max_rows={max_rows}. Configure
   left_columns/right_columns to reduce, or increase max_rows.`
4. SQL DuckDB: SELECT l.col1, l.col2, r.col1, r.col2 FROM left l CROSS JOIN right r.

Frontend (para ambos):
- Config com seleção de colunas multi.
- Preview button: chama endpoint dedicado que faz só o COUNT e mostra estimativa antes de
  rodar — UX mais segura.

Testes:
- Fuzzy match 100k × 50k com blocking key completa em < 5 min (smoke test).
- Fuzzy match 50k × 50k sem blocking key → erro.
- Cross join 1k × 1k = 1M rows → ok.
- Cross join 10k × 10k = 100M rows → erro (> default 10M).
- Output schema do fuzzy inclui match_score e match_method.

NÃO implemente cross join sem o guardrail de estimativa. É fácil derrubar produção.
```

---

## Fase 8 — Dataset Registry + dataset triggers

**Objetivo:** Transformar outputs em ativos reutilizáveis cross-workflow. Adicionar trigger por dado pronto (push + poll dual path). Recomendação `benchmarking_flowfile_shift.md §6`.

**Pré-requisitos:** Fase 5 (hash semântico ajuda no versionamento).

**Risco:** Médio. Modelagem de dados + concorrência de triggers + locks anti-duplicate-fire.

**Esforço estimado:** 8-12 dias.

**Valor entregue:** workflows passam a depender de datasets, não horários; latência entre dado pronto e workflow consumidor cai; lineage cross-workflow.

### Entregáveis

- Migrações Alembic: `datasets`, `dataset_versions`, `dataset_subscriptions`.
- `shift-backend/app/services/datasets/registry.py` — CRUD + `register_version(workflow_execution_id, dataset_id, schema, row_count, storage_uri)`.
- `shift-backend/app/services/workflow/nodes/dataset_writer_node.py`, `dataset_reader_node.py`.
- `shift-backend/app/services/datasets/trigger_dispatcher.py`:
  - **Push path:** `dataset_writer` chama `dispatch_for_dataset(dataset_id, version_id)` que enfileira `dataset_set_trigger` schedules dependentes.
  - **Poll path:** APScheduler job de 30s que reconciliar — encontra `subscriptions` cujo `last_seen_version_id < dataset.current_version_id` e ainda não disparou.
- Frontend: nova área `/projeto/datasets/` listando datasets do workspace + last_updated + lineage.

### Critério de aceite

- [ ] Workflow A escreve dataset `sales_daily` → workflow B (subscription) dispara em < 5s (push path).
- [ ] Se push path falhar (kill do processo durante dispatch), poll path detecta delta na próxima tick.
- [ ] Dois pushes simultâneos do mesmo dataset não disparam B duas vezes (lock + `has_active_run` guard).
- [ ] Dataset versions são imutáveis; rollback via `current_version_id = old_version_id`.

### Prompt para agente

```
Implemente Fase 8 do plano em D:\Labs\shift-project\docs\flowfile-implementation-plan.md.

Contexto obrigatório:
- D:\Labs\shift-project\benchmarking_flowfile_shift.md §6 (todas as subseções)
- D:\Labs\shift-project\docs\flowfile-mechanisms.md §8 (dual path)
- D:\Labs\shift-project\docs\flowfile-implementation-plan.md (Princípios + Fase 8)
- Confirme Fase 5 mergeada (semantic_hash disponível).

MODELAGEM:

migration: add datasets and dataset_versions tables

datasets:
- id UUID PK
- workspace_id UUID FK
- name VARCHAR(255) UNIQUE per workspace
- producer_workflow_id UUID FK NULL (workflow que tipicamente produz)
- current_version_id UUID FK NULL
- description TEXT
- created_at, updated_at

dataset_versions:
- id UUID PK
- dataset_id UUID FK
- producer_execution_id UUID FK
- producer_node_id VARCHAR(255)
- schema_json JSONB
- schema_fingerprint VARCHAR(64)
- row_count BIGINT
- storage_type VARCHAR(32)  -- "duckdb_file" | "postgres_table" | "s3_parquet"
- storage_uri VARCHAR(1024)
- created_at TIMESTAMP
- INDEX (dataset_id, created_at DESC)

dataset_subscriptions:
- id UUID PK
- consumer_workflow_id UUID FK
- dataset_id UUID FK
- mode VARCHAR(16)  -- "any_change" | "set_complete"
- enabled BOOLEAN default true
- last_seen_version_id UUID NULL
- last_dispatched_at TIMESTAMP NULL
- INDEX (dataset_id, enabled)

dataset_set_subscriptions (para mode=set_complete):
- subscription_id UUID FK
- dataset_id UUID FK
- last_seen_version_id UUID NULL

NODES:

dataset_writer_node.py
- NODE_PROFILE: shape=output, default_strategy=io_thread
- Config: {dataset_name, mode: "overwrite"|"append"|"new_version"}
- Materializa input em arquivo (storage path determinado por config global).
- Cria dataset_version e atualiza current_version_id.
- DEPOIS de commitar, chama trigger_dispatcher.dispatch_for_dataset(dataset_id, version_id).

dataset_reader_node.py
- NODE_PROFILE: shape=io, default_strategy=io_thread
- Config: {dataset_id, version: "current"|"specific", version_id?}
- Lê o dataset_version e expõe como input para downstream.
- Schema callback (Fase 5): retorna schema do version selecionado.

DISPATCHER (push + poll):

shift-backend/app/services/datasets/trigger_dispatcher.py

class TriggerDispatcher:
    async def dispatch_for_dataset(self, dataset_id, version_id):
        \"\"\"Push path. Chamado pelo dataset_writer.\"\"\"
        # Para cada subscription enabled:
        #   1. update last_seen_version_id = version_id atomicamente
        #   2. se mode=any_change: enqueue workflow execution
        #   3. se mode=set_complete: verificar se TODOS datasets do set foram atualizados
        #      desde last_dispatch; se sim, enqueue.
        # Guards anti-duplo-disparo:
        #   - has_active_run(consumer_workflow_id) — não disparar se já há ativo
        #   - row lock no subscription via SELECT FOR UPDATE

    async def reconcile(self):
        \"\"\"Poll path. Chamado por APScheduler a cada 30s.\"\"\"
        # SELECT subscriptions WHERE enabled AND
        #   (last_seen_version_id IS NULL OR
        #    last_seen_version_id != dataset.current_version_id)
        # Para cada, replicar lógica do push path.
        # Esse caminho é safety net: se push falhou (crash), poll resgata.

Plugar reconcile() como APScheduler job (ver main.py:lifespan onde outros jobs estão).
Interval: 30s.

ENDPOINTS:
- GET /api/v1/datasets/?workspace_id=...
- GET /api/v1/datasets/{id}/versions
- POST /api/v1/datasets/{id}/subscriptions (criar subscription)
- GET /api/v1/datasets/{id}/lineage (datasets que dependem deste)

FRONTEND:
- Página /projeto/datasets listando datasets do workspace com columns:
  nome, último_update, row_count, producer_workflow, n_subscribers.
- Detalhe do dataset com timeline de versões + grafo de lineage simples (use ReactFlow).

Critério de aceite:
- Workflow A com dataset_writer "sales_daily" → workflow B com subscription dispara em < 5s.
- Mata processo durante dispatch (kill -9 do shift-backend) → reconcile pega no próximo tick.
- 2 execuções simultâneas de A não disparam B 2x (verificar com sleep + threading).
- Test de versionamento: sales_daily v1, v2, v3 — current_version_id sempre aponta para v3,
  rollback funciona setando current_version_id = v1.

NÃO criar virtual datasets ainda (Fase 11+). Comece com physical apenas.
```

---

## Fase 9 — Code export + YAML save format

**Objetivo:** Workflow exportável como SQL/Python autônomo para auditoria/portabilidade. YAML save format para versionamento em git.

**Pré-requisitos:** Fase 4 (depende de NODE_EXECUTION_PROFILE para classificar exportável vs não).

**Risco:** Médio. Code-gen pode gerar código incorreto silenciosamente — mitigar com testes snapshot.

**Esforço estimado:** 5-7 dias.

**Valor entregue:** transparência ("seu workflow não fica preso na plataforma"); review de transformações em PR; runbook operacional.

### Entregáveis

- `shift-backend/app/services/workflow/exporters/sql_exporter.py` — workflow → SQL DuckDB+dlt standalone.
- `shift-backend/app/services/workflow/exporters/python_exporter.py` — workflow → Python (apenas para nós suportados).
- Endpoint `POST /api/v1/workflows/{id}/export?format=sql|python|yaml`.
- `shift-backend/app/services/workflow/serializers/yaml_serializer.py` — porte do format do `data/templates/flows/order_enrichment.yaml`.
- Frontend: botão "Export" no editor → dropdown com formatos.

### Critério de aceite

- [ ] Workflow com nós suportados (`sql_database, filter, mapper, join, lookup, aggregator, deduplication, load`) exporta como SQL executável standalone.
- [ ] Nós não suportados causam erro com lista completa: `Cannot export: 3 unsupported nodes (ai_node, http_request, code_node).`
- [ ] YAML round-trip: import → export → import produz mesma definição (deep equality).
- [ ] Diff de YAML entre versões do workflow é legível em PR.

### Prompt para agente

```
Implemente Fase 9 do plano em D:\Labs\shift-project\docs\flowfile-implementation-plan.md.

Contexto obrigatório:
- D:\Labs\shift-project\benchmarking_flowfile_shift.md §8
- D:\Labs\shift-project\docs\flowfile-mechanisms.md §3, §10
- D:\Labs\Flowfile\flowfile_core\flowfile_core\flowfile\code_generator\code_generator.py
  como referência ESTRUTURAL (não copiar — Shift gera SQL, não Polars).
- D:\Labs\Flowfile\data\templates\flows\order_enrichment.yaml como referência de format.

Tarefa em 3 partes:

PARTE 1: SQL Exporter
shift-backend/app/services/workflow/exporters/sql_exporter.py

class SQLExporter:
    def export(self, workflow_definition) -> str: ...

Padrão estrutural similar ao code_generator do Flowfile:
1. Topological sort via mesmo algoritmo do dynamic_runner.
2. Para cada nó, dispatch handler _handle_{node_type} que retorna SQL string.
3. Acumular unsupported_nodes; ao final, se houver, raise UnsupportedNodeError com lista.

V1 cobre: sql_database, filter, mapper, join, lookup, aggregator, deduplication, load.

Output: script SQL standalone com:
- CREATE TABLE para cada nó intermediário
- Comentários com node_id e node_type acima de cada bloco
- Variáveis de connection no topo (placeholder com TODO)

PARTE 2: Python Exporter
shift-backend/app/services/workflow/exporters/python_exporter.py

Mesma estrutura. Gera Python script standalone usando duckdb + sqlalchemy.
V1 cobre os mesmos 8 node types do SQL exporter.
Imports no topo, def main(), if __name__ == "__main__": main().

PARTE 3: YAML Serializer
shift-backend/app/services/workflow/serializers/yaml_serializer.py

Format inspirado em data/templates/flows/order_enrichment.yaml:

```yaml
shift_version: "1.0"
workflow_id: "<uuid>"
workflow_name: "<name>"
settings:
  variables: []
  schedule: null
nodes:
  - id: "node_1"
    type: "sql_database"
    position: {x: 0, y: 100}
    inputs: []
    outputs: ["node_2"]
    config:
      connection_id: "<uuid>"
      query: "SELECT * FROM orders"
  - id: "node_2"
    type: "filter"
    inputs: ["node_1"]
    outputs: ["node_3"]
    config:
      condition: "amount > 100"
```

Funções:
- def to_yaml(workflow_definition) -> str
- def from_yaml(yaml_str) -> WorkflowDefinition
- yaml.safe_dump com sort_keys=False, default_flow_style=False

Round-trip must preserve all fields (including extension fields).

ENDPOINT:
POST /api/v1/workflows/{workflow_id}/export?format=sql|python|yaml
Response 200 com Content-Type apropriado e Content-Disposition: attachment;filename=...

POST /api/v1/workflows/import (multipart/form-data com arquivo .yaml)
Cria novo workflow draft a partir do YAML, retorna workflow_id.

FRONTEND:
- Botão "Export" no editor (workflow-editor.tsx) → DropdownMenu com 3 formatos.
- Trigger download via fetch + blob.
- Modal de import na página de workflows.

Critério de aceite:
- Workflow de exemplo (8 nós suportados) exporta como SQL e o SQL gerado roda no DuckDB
  CLI sem modificação (exceto preencher connection strings).
- Workflow com node_type não suportado retorna 422 com body
  {"error": "Unsupported nodes", "nodes": [{"node_id": "...", "node_type": "ai_node",
    "reason": "..."}]}
- YAML round-trip: snapshot test que import-export-import produz mesmo dict.
- Diff de 2 versões do mesmo workflow em YAML é legível (review-friendly).

NÃO copiar código Polars do Flowfile literalmente — Shift exporta SQL/dlt.
```

---

## Fase 10 — Conectores cloud storage

**Objetivo:** Adicionar conectores S3 e GCS (read/write). Demanda comercial real (clientes corporativos exportam para data lake).

**Pré-requisitos:** Fase 5 (parameter resolver para credentials seguros).

**Risco:** Médio. Credenciais, paths com wildcards, schema drift entre arquivos.

**Esforço estimado:** 4-6 dias por conector.

**Valor entregue:** integração com data lakes corporativos; ponte natural para Dataset Registry (storage_type pode ser `s3_parquet`).

### Entregáveis

- `shift-backend/app/services/connectors/cloud_storage/` — base abstrata.
- `s3_connector.py`, `gcs_connector.py` — implementações.
- Nodes `s3_reader_node.py`, `s3_writer_node.py`, equivalentes para GCS.
- Tipo de connection `cloud_storage` com credentials criptografadas.
- Frontend: novo tipo de connection no formulário; configs de leitura (path/prefix/format) e escrita (path/format/partitioning).

### Critério de aceite

- [ ] Lê CSV/Parquet de S3 via connection_id criptografada.
- [ ] Escreve Parquet em S3 com partitioning por coluna.
- [ ] Schema drift detectado e reportado em warnings.
- [ ] Wildcard `s3://bucket/data/*.parquet` funciona.

### Prompt para agente

```
Implemente Fase 10 do plano em D:\Labs\shift-project\docs\flowfile-implementation-plan.md.

Contexto obrigatório:
- D:\Labs\shift-project\benchmarking_flowfile_nodes_shift.md §4.11
- D:\Labs\shift-project\docs\flowfile-implementation-plan.md (Princípios + Fase 10)
- Leia padrão de connection existente em shift-backend/app/models/connection.py e
  shift-backend/app/services/connection_service.py — credentials criptografadas via
  EncryptedString.
- Confirme Fase 5 mergeada (parameter_resolver para credentials com ${} se necessário).

Tarefa: implementar S3 reader + writer (V1). GCS pode vir depois com mesmo padrão.

DEPENDÊNCIAS (pyproject.toml):
- boto3>=1.34
- pyarrow>=15

CONNECTION TYPE:
Adicionar tipo "cloud_storage" no enum de connection types.
Credentials encriptadas: {provider: "s3"|"gcs", access_key_id, secret_access_key, region, endpoint_url?}.
Para GCS no futuro: service_account_json criptografado.

NODES:

s3_reader_node.py
NODE_PROFILE: shape=io, default_strategy=io_thread
Config:
- connection_id: UUID
- path: s3://bucket/key.csv ou s3://bucket/prefix/*.parquet
- format: csv | parquet | json
- options: {csv_delimiter, csv_header, parquet_columns?, etc}
- max_files: int default 1000

Implementação:
1. Resolver connection → credentials.
2. boto3.client("s3") com credentials.
3. Se path tem wildcard: list_objects_v2 com prefix, filtrar por glob.
4. Para cada arquivo: download para temp dir + load para DuckDB via duckdb.read_csv() ou read_parquet().
5. UNION ALL no DuckDB se múltiplos arquivos.
6. Output: DuckDbReference.
7. Schema drift: comparar schema do primeiro com restante; warnings em output_summary.

s3_writer_node.py
NODE_PROFILE: shape=output
Config:
- connection_id, path, format, partitioning?: list[col]
- mode: "overwrite" | "append"

Implementação:
1. Materializar input como Parquet local (DuckDB COPY).
2. Se partitioning: COPY ... TO 'path' (FORMAT PARQUET, PARTITION_BY (col1, col2)).
3. Upload via boto3.upload_file (paralelizar para múltiplos arquivos).
4. Output: lista de keys escritas no summary.

FRONTEND:
- Novo tipo de connection no connection-form.tsx.
- Configs de S3 reader/writer com:
  - Test connection (lista buckets visíveis).
  - Path browser básico (lista keys com prefix).
- Validação visual: regex s3:// no path.

SECURITY:
- Credentials NUNCA aparecem em response/logs.
- Usar EncryptedString do projeto.
- Mascarar campo no UI após save (mesmo padrão das outras connections).

Critério de aceite:
- Lê CSV de s3://bucket/data.csv e materializa em DuckDB. Test com bucket público
  ou via LocalStack/MinIO para CI.
- Wildcard s3://bucket/year=2025/*.parquet lê múltiplos arquivos com schema drift report.
- Escreve Parquet particionado por coluna (verificar via aws s3 ls).
- Credentials aparecem mascaradas no GET /connections/{id}.

GCS pode ser adicionado depois com mesmo padrão (gcsfs ou google-cloud-storage).
NÃO usar Polars para leitura — DuckDB.read_parquet/read_csv são suficientes e
mantêm contrato DuckdbReference.
```

---

## Como iniciar

1. **Revise os 4 documentos referência** antes de começar qualquer fase.
2. **Implemente em PRs separadas por fase** — uma fase por PR pequena facilita review e rollback.
3. **Não pule a Fase 4.** Ela parece sem valor visível, mas é o que torna as Fases 5-6 verificáveis. Sem dados reais de strategy_observed, qualquer heurística é chute.
4. **Paralelizáveis:** Fases 1, 2, 3 e 4 podem rodar em paralelo (devs/agentes diferentes). A partir da 5, há dependências sequenciais.
5. **Teste com workload realista.** Especialmente Fases 6-8 — sem dados grandes, problemas de concorrência e OOM ficam latentes.
6. **Cada PR deve atualizar o `MEMORY.md` do projeto** registrando decisões não-óbvias para conversas futuras com IA.

## Fora de escopo (deliberadamente)

- **FlowFrame DSL** (Python que constrói DAG). ROI incerto para o público do Shift; SDK pode esperar até haver demanda.
- **Polars como engine alternativo.** DuckDB é a aposta tecnológica. Não introduzir segundo runtime.
- **Custom Node Designer com Python arbitrário.** Multi-tenant SaaS exige sandbox forte; postergar até haver caso de uso e arquitetura de sandbox madura.
- **Virtual datasets.** Postergar até Dataset Registry físico estar maduro e versionamento ser confiável.
- **Polars expression engine** para Formula. Fortalecer SQL/DSL próprio do Shift; não importar dependência adicional pesada.
