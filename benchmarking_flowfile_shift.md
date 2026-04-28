# Benchmarking Tecnico Profundo: Flowfile -> Shift

## 1. Tese central

O Flowfile nao e simplesmente "mais um ETL visual". A parte mais valiosa dele esta em como ele separa quatro responsabilidades que, em muitos runners, acabam misturadas:

1. Planejamento do grafo.
2. Decisao de execucao por no.
3. Runtime de dados pesado.
4. Catalogo de dados como produto operacional.

O Shift ja tem uma base forte em runner, observabilidade, retry, cache de extracao, DuckDB por execucao e streaming SQL. O que falta para subir de patamar nao e copiar todos os nos do Flowfile. O ganho real vem de copiar os **padroes estruturais** que tornam o Flowfile mais previsivel em workloads grandes:

1. Um policy engine central para decidir `run/skip/local/worker`.
2. Um worker de dados isolado por processo para operacoes caras.
3. Uma camada formal de estado/cache por no, com hash semantico e invalidacao clara.
4. Triggers orientados a atualizacao de dataset, nao apenas cron.
5. Export do pipeline para codigo, para reproducibilidade e operacao fora da UI.

Minha recomendacao: copiar agressivamente os padroes de execucao e governanca, adaptar o runtime para DuckDB/Shift, e nao copiar cegamente o stack Polars/FlowFrame inteiro.

---

## 2. Resumo do que copiar, adaptar e evitar

| Item | Decisao | Por que |
|---|---|---|
| Execution plan explicito | Copiar | O Shift ja calcula niveis, mas deveria persistir o plano como artefato auditavel. |
| Policy engine por no | Copiar | Hoje o Shift espalha decisoes entre runner, cache, checkpoint e processors. Centralizar reduz comportamento implicito. |
| Worker subprocessado | Copiar adaptando | O padrao e excelente, mas o payload no Shift deve ser `DuckDbReference`/arquivos, nao Polars LazyFrame serializado como contrato principal. |
| Narrow/wide transform taxonomy | Copiar | Ajuda a decidir custo, materializacao, worker e preview. |
| Catalogo com table triggers | Copiar incrementalmente | E a ponte para automacao orientada a dado pronto. |
| Virtual tables com lazy graph | Adaptar | Conceito e forte, mas deve entrar depois de um Dataset Registry minimo. |
| Export para codigo | Copiar | Aumenta confianca operacional e revisao por PR. |
| FlowFrame inteiro | Evitar por enquanto | Adiciona nova camada de runtime ao Shift sem necessidade imediata. |
| WebSocket binario para tudo | Adaptar | Bom para resultados binarios pequenos/medios; para Shift, referencias a arquivos sao mais naturais. |

---

## 3. Diagnostico comparativo rapido

| Capacidade | Flowfile | Shift hoje | Leitura tecnica |
|---|---|---|---|
| Orquestracao topologica | `ExecutionPlan` com stages e skip nodes | Niveis topologicos com `asyncio.gather` | Shift e forte, mas falta snapshot formal do plano. |
| Decisao por no | `NodeExecutor._decide_execution` e `_determine_strategy` | Decisoes distribuidas no runner/processors | Flowfile e mais organizado nessa camada. |
| Runtime pesado | Worker + subprocess + status + cancel | `asyncio.to_thread` + monitor de memoria | Shift protege o processo, mas nao isola workload. |
| Dados intermediarios | Polars LazyFrame/FlowDataEngine | DuckDB por execucao + `DuckDbReference` | Shift tem uma escolha muito boa para ETL SQL-heavy. |
| Extracao grande | Worker e conectores diversos | SQL streaming, particionado, backpressure e spill | Shift e provavelmente superior em extracao SQL. |
| Catalogo | Delta/Parquet, virtual tables, SQL context | Sem registry cross-execution equivalente | Flowfile e superior em governanca de dataset. |
| Scheduling | interval + table trigger + table-set trigger | cron com APScheduler | Shift precisa de schedule orientado a dados. |
| Export | Polars/FlowFrame codegen | Nao ha equivalente | Gap claro de portabilidade. |

---

## 4. Arquitetura de execucao

## 4.1 Plano topologico auditavel

### O que o Flowfile faz

O Flowfile usa um `ExecutionPlan` separado da execucao. Esse plano contem:

- nos pulados (`skip_nodes`);
- stages topologicos;
- ordem achatada dos nos;
- deteccao de ciclo.

Arquivos relevantes:

- `D:\Labs\Flowfile\flowfile_core\flowfile_core\flowfile\util\execution_orderer.py`
- `D:\Labs\Flowfile\flowfile_core\flowfile_core\flowfile\flow_graph.py`

O `run_graph()` calcula o plano e `_execute_stages()` executa os stages sequencialmente, com paralelismo dentro do stage. Ao final de cada stage, falhas sao propagadas para dependentes.

### Como esta hoje no Shift

O Shift tambem calcula niveis topologicos em `dynamic_runner.py` e executa cada nivel com `asyncio.gather`. O runner ainda e mais rico em alguns pontos:

- branch condicional por handles ativos/inativos;
- retry por no;
- timeout por no;
- checkpoint;
- cache de extracao;
- eventos `node_start`, `node_complete`, `node_error`, `execution_end`.

Ou seja: o Shift nao esta atras no algoritmo de grafo. O gap e que o plano nao vira um artefato claro, versionado e consultavel.

### O que mudaria no Shift

Criar um `ExecutionPlanSnapshot`, gerado antes da execucao real:

```json
{
  "execution_id": "...",
  "plan_version": 1,
  "levels": [["extract"], ["filter", "lookup"], ["join"], ["load"]],
  "node_count": 5,
  "edge_count": 4,
  "predicted_strategies": {
    "join": {
      "strategy": "data_worker",
      "reason": "wide_transform"
    }
  }
}
```

### Ganho esperado

- Melhor debugging: antes de perguntar "por que falhou?", da para saber "o que o runner pretendia fazer".
- Comparacao entre execucoes: se uma nova versao do workflow muda o plano, isso fica claro.
- Base para custo estimado por execucao.
- Base para dry-run real.

### Implementacao recomendada

1. Criar um builder em `shift-backend/app/orchestration/flows/execution_plan.py`.
2. Chamar logo apos `_topological_sort_levels`.
3. Persistir em uma tabela simples `workflow_execution_plans` ou em campo JSON da execucao, dependendo do modelo atual.
4. Incluir no payload final de observabilidade apenas um resumo; o JSON completo fica no banco.

### Cuidado

Nao transformar isso em um novo scheduler. O plano deve ser artefato de observabilidade e decisao, nao uma duplicacao do runner.

---

## 4.2 Policy engine por no

### O que o Flowfile faz

O Flowfile tem um ponto central para decidir se um no roda e como roda: `NodeExecutor._decide_execution()`.

Ele considera:

- no de output sempre roda;
- refresh forcado;
- cache materializado existente;
- performance mode;
- primeira execucao;
- arquivo fonte alterado;
- skip se nada mudou.

Depois `_determine_strategy()` decide:

- `FULL_LOCAL`;
- `LOCAL_WITH_SAMPLING`;
- `REMOTE`;
- `SKIP`.

O ponto mais importante e a classificacao `narrow` vs `wide`:

- `narrow`: select, formula, filter, sample, union. Operacoes que geralmente nao exigem reorganizacao global.
- `wide`: join, group by, sort, pivot, fuzzy match. Operacoes que podem exigir shuffle, ordenacao, cardinalidade alta ou materializacao.

### Como esta hoje no Shift

O Shift tem decisoes boas, mas espalhadas:

- cache de extracao no runner;
- checkpoint no runner;
- retry no runner;
- materializacao nos processors;
- DuckDB refs nos nodes;
- memoria no `memory_monitor`.

O problema nao e ausencia de capacidade. O problema e que nao existe um lugar unico que responda:

> Este no deve rodar? Se sim, em thread, processo local ou worker? Por qual motivo?

### O que mudaria no Shift

Criar `ExecutionStrategyResolver` com contrato explicito:

```python
class NodeStrategy(str, Enum):
    SKIP = "skip"
    LOCAL_THREAD = "local_thread"
    LOCAL_PROCESS = "local_process"
    DATA_WORKER = "data_worker"

@dataclass
class StrategyDecision:
    should_run: bool
    strategy: NodeStrategy
    reason: str
    invalidation_reasons: list[str]
    estimated_cost: str
```

O resolver deveria considerar:

- tipo do no;
- classificacao `narrow/wide/io/output/control`;
- existencia de cache/checkpoint;
- tamanho estimado de input;
- quantidade de inputs;
- configuracao de timeout/retry;
- pressao de memoria;
- flags como `force_refresh`.

### Ganho esperado

- O runner fica menos cheio de excecoes especificas.
- Cada decisao vira testavel por matriz de cenarios.
- Fica facil introduzir worker sem reescrever todos os processors.
- Eventos passam a explicar a decisao, nao apenas o resultado.

### Implementacao recomendada

1. Criar metadados de no:

```python
NODE_EXECUTION_PROFILE = {
    "filter": {"shape": "narrow", "default_strategy": "local_thread"},
    "mapper": {"shape": "narrow", "default_strategy": "local_thread"},
    "join": {"shape": "wide", "default_strategy": "data_worker"},
    "aggregator": {"shape": "wide", "default_strategy": "data_worker"},
    "lookup": {"shape": "wide", "default_strategy": "data_worker"},
    "sql_database": {"shape": "io", "default_strategy": "local_thread"},
    "load": {"shape": "output", "default_strategy": "local_thread"}
}
```

2. Resolver estrategia antes de montar o coroutine do no.
3. Adicionar `strategy_decision` em `node_start`.
4. Criar testes parametrizados para `cache_hit`, `checkpoint`, `wide_transform`, `disabled`, `force_refresh`.

### Cuidado

Nao comecar com heuristica sofisticada demais. Primeiro copie o padrao de decisao explicita. Auto-tuning vem depois.

---

## 4.3 Worker de dados isolado por processo

### O que o Flowfile faz

O Flowfile separa o core do worker:

- core envia task;
- worker cria subprocesso;
- task tem `task_id`;
- status fica consultavel;
- resultado fica em arquivo/cache;
- cancelamento usa `process.terminate()` e `join()`;
- WebSocket envia progresso e resultado binario;
- REST existe como fallback.

Arquivos relevantes:

- `D:\Labs\Flowfile\flowfile_worker\flowfile_worker\streaming.py`
- `D:\Labs\Flowfile\flowfile_worker\flowfile_worker\routes.py`
- `D:\Labs\Flowfile\flowfile_worker\flowfile_worker\process_manager.py`
- `D:\Labs\Flowfile\flowfile_core\flowfile_core\flowfile\flow_data_engine\subprocess_operations\subprocess_operations.py`

Esse desenho isola memoria e falhas. Se um join/fuzzy match explode memoria, o core nao necessariamente cai junto.

### Como esta hoje no Shift

O Shift executa processors com `asyncio.to_thread`, o que evita travar o event loop, mas nao isola memoria. Um processor pesado ainda roda no mesmo processo Python.

O Shift tem um `memory_monitor.py` que cancela a execucao mais antiga sob pressao de RSS. Isso e bom como ultima linha de defesa, mas e uma protecao global. Nao e isolamento por task.

### O que mudaria no Shift

Adicionar um `DataWorkerRuntime` para workloads pesados.

O contrato do Shift nao deveria ser Polars LazyFrame serializado como no Flowfile. O Shift ja tem um bom contrato: `DuckDbReference`. Entao o worker deveria receber referencias a arquivos DuckDB/tabelas e devolver outra referencia materializada.

Contrato sugerido:

```json
{
  "task_id": "uuid",
  "execution_id": "uuid",
  "node_id": "join_12",
  "node_type": "join",
  "input_refs": {
    "left": {
      "database_path": "...",
      "dataset_name": "main",
      "table_name": "customers"
    },
    "right": {
      "database_path": "...",
      "dataset_name": "main",
      "table_name": "orders"
    }
  },
  "config": {
    "join_type": "left",
    "conditions": [...]
  }
}
```

### Ganho esperado

- Reducao do risco de derrubar o processo FastAPI em transformacoes caras.
- Cancelamento mais efetivo.
- Metricas por task pesada.
- Possibilidade de escalar workers separadamente no futuro.

### Implementacao recomendada

Fase 1:

- worker local via subprocess, sem rede;
- aplicar primeiro a `join`, `lookup`, `aggregator`, `deduplication`;
- resultado continua sendo `DuckDbReference`.

Fase 2:

- API task-based (`submit/status/fetch/cancel`);
- worker como processo/servico separado;
- telemetria por task.

Fase 3:

- filas e limite de concorrencia por workspace/projeto.

### Cuidado

Nao mover tudo para worker. Nos leves devem continuar em thread para evitar overhead. A regra inicial deve ser conservadora:

| Tipo | Estrategia inicial |
|---|---|
| filter/mapper/math simples | `LOCAL_THREAD` |
| join/lookup/aggregator/dedup grande | `DATA_WORKER` |
| sql_database | manter runtime atual |
| load/bulk_insert | avaliar por volume |
| control flow | `LOCAL_THREAD` |

---

## 4.4 Memoria: Flowfile e Shift resolvem problemas diferentes

### O que o Flowfile faz

O Flowfile usa `FlowDataEngine` como wrapper sobre `pl.DataFrame`/`pl.LazyFrame`. Ele carrega metadados, schema, lazy/eager, callbacks, origem e operacoes de transformacao.

No worker, a coleta tenta streaming:

```python
try:
    return lf.collect(engine="streaming")
except PanicException:
    return lf.collect(engine="in-memory")
```

Isso e forte quando o pipeline e Polars-first.

### Como esta hoje no Shift

O Shift e DuckDB-first no runtime de workflow:

- dados intermediarios viram `DuckDbReference`;
- `JsonlStreamer` materializa incrementos;
- extração SQL usa cursor server-side e `fetchmany`;
- `BoundedChunkQueue` aplica backpressure e spill;
- transformacoes rodam SQL DuckDB contra arquivos/tabelas.

Esse desenho e excelente para ETL operacional, especialmente com SQL e dados tabulares grandes.

### O que mudaria no Shift

Copiar a ideia do Flowfile de **classificar materializacao**, mas preservar DuckDB como base:

- `reference_only`: no passa apenas a referencia;
- `duckdb_sql`: no cria tabela derivada por SQL;
- `streamed_write`: no escreve em chunks;
- `worker_materialized`: no roda em worker e devolve referencia;
- `preview_sample`: no gera amostra separada para UI.

### Ganho esperado

- Menos materializacao acidental.
- Decisoes de memoria mais visiveis.
- Melhor experiencia em preview sem comprometer execucao full.

### Cuidado

Evitar introduzir Polars como segundo runtime obrigatorio agora. O Shift ja tem uma linha coerente com DuckDB; misturar dois engines no caminho critico pode dobrar complexidade operacional.

---

## 5. Estado, cache e invalidacao

## 5.1 Estado de execucao separado da definicao do no

### O que o Flowfile faz

O Flowfile separa `FlowNode` de `NodeExecutionState`.

`NodeExecutionState` guarda:

- `has_run_with_current_setup`;
- `has_completed_last_run`;
- erro;
- schema previsto/resultante;
- informacoes de arquivo fonte;
- hash de execucao;
- exemplo/cache de dados.

Isso permite pensar em execucao stateless no futuro, porque o estado mutavel nao precisa morar dentro da definicao do no.

### Como esta hoje no Shift

O Shift guarda estado principalmente durante a execucao:

- `results`;
- `node_executions`;
- checkpoint;
- cache de extracao;
- eventos persistidos.

Isso funciona, mas nao existe um objeto formal de estado de no comparavel.

### O que mudaria no Shift

Criar um `NodeRunState` por execucao:

```json
{
  "execution_id": "...",
  "node_id": "join_1",
  "semantic_hash": "...",
  "strategy": "data_worker",
  "status": "completed",
  "input_fingerprints": ["..."],
  "output_reference": {...},
  "schema_fingerprint": "...",
  "row_count": 1000000
}
```

### Ganho esperado

- Melhor reuso de resultados.
- Melhor auditoria de por que um no rodou.
- Base para cache de transformacao, nao apenas extracao.

### Implementacao recomendada

Comecar sem cache de transformacao. Primeiro persista estado. Cache vem depois.

---

## 5.2 Hash semantico por no

### O que o Flowfile faz

O Flowfile tem cuidado especial com hash quando resolve parametros temporarios. Ele salva o hash original, resolve configuracao para executar, e depois restaura o estado para evitar invalidacao falsa.

Essa preocupacao e importante: se o hash muda por detalhe runtime, cache e reexecucao ficam imprevisiveis.

### Como esta hoje no Shift

O Shift tem `extract_cache_service.make_cache_key()`, que remove campos runtime-only como `cache_enabled` e `cache_ttl_seconds`.

Isso e bom, mas concentrado em extracao.

### O que mudaria no Shift

Criar hashing semantico para todos os tipos importantes:

- config normalizada;
- conexoes referenciadas por ID/fingerprint, nao segredo bruto;
- inputs por fingerprint;
- versao do algoritmo de hash;
- campos runtime excluidos.

### Ganho esperado

- Cache mais correto.
- Menos reprocessamento por mudanca irrelevante.
- Base para "incremental recompute" por no.

### Cuidado

Hash errado e pior que nao ter cache. Comecar com observabilidade de hash antes de confiar nele para skip automatico em transformacoes.

---

## 6. Catalogo, datasets e schedules orientados a dado

## 6.1 Dataset Registry minimo

### O que o Flowfile faz

O Flowfile tem catalogo com:

- tabelas fisicas;
- tabelas virtuais;
- Delta/Parquet;
- schema, row count, size;
- lineage com fluxo produtor;
- preview;
- SQL contra catalogo;
- historico Delta.

### Como esta hoje no Shift

O Shift tem referencias DuckDB por execucao. Isso e muito bom para runtime, mas nao equivale a um catalogo cross-execution.

Hoje, quando uma execucao termina, o conhecimento sobre "este dataset foi produzido por esse workflow e atualizado neste instante" nao parece estar formalizado como produto de dados reutilizavel.

### O que mudaria no Shift

Criar um Dataset Registry minimo:

```text
datasets
  id
  workspace_id
  name
  storage_type
  current_version_id
  producer_workflow_id
  updated_at

dataset_versions
  id
  dataset_id
  producer_execution_id
  schema_json
  schema_fingerprint
  row_count
  storage_uri
  created_at
```

### Ganho esperado

- Workflows podem depender de datasets, nao apenas de horarios.
- UI pode mostrar lineage e ultima atualizacao.
- Base para table triggers.
- Base para leitura de dataset publicado em outro workflow.

### Implementacao recomendada

V1:

- registrar apenas outputs de `load` ou um novo `dataset_writer`;
- sem virtual table;
- storage inicial pode ser DuckDB/Parquet, dependendo do padrao atual de deploy.

V2:

- `dataset_reader`;
- triggers;
- schema diff.

V3:

- virtual datasets;
- materializacao sob demanda;
- historico/versionamento mais rico.

---

## 6.2 Table trigger e table-set trigger

### O que o Flowfile faz

O Flowfile combina dois caminhos:

- push path: quando uma tabela e sobrescrita, dispara schedules imediatamente;
- poll path: scheduler verifica periodicamente se houve atualizacao nao processada.

Isso resolve duas coisas ao mesmo tempo:

- baixa latencia;
- tolerancia a falha do disparo imediato.

Tambem existe `table_set_trigger`: so dispara quando todas as tabelas do conjunto foram atualizadas desde a ultima execucao.

### Como esta hoje no Shift

O Shift usa APScheduler com cron em workflows publicados. Isso e robusto para tempo, mas limitado para dependencias de dados.

### O que mudaria no Shift

Adicionar schedule por dataset:

```json
{
  "schedule_type": "dataset_trigger",
  "dataset_id": "sales_daily"
}
```

E para conjunto:

```json
{
  "schedule_type": "dataset_set_trigger",
  "dataset_ids": ["sales_daily", "customers_daily"],
  "mode": "all"
}
```

### Ganho esperado

- Menos execucoes vazias.
- Menor atraso entre dado pronto e pipeline dependente.
- Melhor orquestracao batch/event-driven.

### Cuidado

E preciso ter travas anti-duplo-disparo:

- nao disparar se ja ha execucao ativa;
- gravar `last_seen_dataset_version`;
- reconciliar por poll.

---

## 6.3 Virtual datasets

### O que o Flowfile faz

O Flowfile resolve virtual tables de duas formas:

- SQL virtual: monta `pl.SQLContext`, registra tabelas referenciadas e executa query;
- flow virtual: reexecuta o fluxo produtor ate o writer ou usa LazyFrame serializado se valido.

Ele tambem protege contra recursao e referencia circular.

### Como esta hoje no Shift

Nao ha equivalente direto. O Shift pode compor dados por workflow, mas nao parece ter dataset virtual catalogado que represente uma query/fluxo sem materializacao imediata.

### O que mudaria no Shift

Depois do Dataset Registry minimo, adicionar:

- `virtual_dataset` como query SQL sobre datasets publicados;
- cache/materializacao opcional;
- invalidacao por versao das fontes.

### Ganho esperado

- Menos duplicacao de dados.
- Reuso de regras de negocio como datasets logicos.
- Melhor composicao entre times/workflows.

### Cuidado

Nao implementar virtual dataset antes de ter dataset fisico e versionado. Sem versao/fingerprint, invalidacao vira fragil.

---

## 7. Funcionalidades ETL especificas

## 7.1 Cobertura de nos

### O que o Flowfile tem de interessante

Pelo `node_store`, o Flowfile inclui:

- join, cross join, union;
- group by, record count, pivot, unpivot;
- fuzzy match;
- graph solver;
- random split;
- text to rows;
- Polars code;
- SQL query;
- Python script;
- cloud reader/writer;
- catalog reader/writer;
- Kafka source;
- Google Analytics.

### Como esta hoje no Shift

O Shift ja tem um conjunto operacional forte:

- SQL database;
- SQL script;
- CSV/Excel input;
- API input;
- HTTP request;
- filter, mapper, math;
- join, lookup, aggregator, dedup;
- load, bulk insert, composite insert;
- condition/if/switch/loop/sub-workflow;
- triggers cron/webhook/polling/manual;
- notification/dead letter/assert.

### O que realmente copiar em features

Prioridade alta:

| Feature Flowfile | Por que vale copiar |
|---|---|
| Fuzzy match | Alto valor em dados reais, cadastros, CRM, conciliacao. |
| Pivot/unpivot | Operacoes comuns em ETL analitico. |
| Union multi-input | Shift pode ganhar ergonomia para consolidacao de varias fontes. |
| Text to rows | Muito usado em normalizacao de campos semi-estruturados. |
| Catalog reader/writer | Necessario para Dataset Registry. |
| Kafka source | Bom para roadmap event/streaming, mas nao antes do registry. |
| GA4 reader | Bom conector vertical, se houver demanda de produto. |

Prioridade menor:

| Feature | Motivo |
|---|---|
| Graph solver | Poderoso, mas nichado. |
| Random split | Util para ML, mas nao parece core do Shift agora. |
| Polars code | Shift ja tem `code_node`; melhor fortalecer sandbox/contrato antes. |

### Cuidado

Nao copiar feature de no sem copiar tambem:

- contrato de entrada/saida;
- comportamento de schema;
- limites de memoria;
- testes com dados grandes;
- observabilidade.

No em ETL nao e apenas uma funcao. E um contrato operacional.

---

## 7.2 Join, lookup e aggregator: onde o Shift ja esta bem

### Como esta hoje no Shift

Os processors de `join`, `lookup` e `aggregator` usam DuckDB diretamente sobre referencias.

Exemplo conceitual do `join_node.py`:

- recebe `left` e `right` por handles;
- abre conexao no DuckDB esquerdo;
- se o direito esta em outro arquivo, faz `ATTACH`;
- executa `CREATE OR REPLACE TABLE ... AS SELECT ... JOIN ...`;
- devolve `DuckDbReference`.

Isso e uma arquitetura muito boa para ETL tabular, porque evita puxar tudo para memoria Python.

### O que copiar do Flowfile aqui

Nao substituir por Polars. Copiar:

- classificacao `wide`;
- strategy resolver;
- offload para worker quando volume for alto;
- preview separado;
- schema prediction antes da execucao quando possivel.

### Ganho esperado

O Shift preserva a eficiencia DuckDB e ganha isolamento operacional.

---

## 7.3 Extracao SQL: o Shift provavelmente esta melhor

### Como esta hoje no Shift

O `extraction_service.py` tem recursos maduros:

- cursor server-side por driver;
- `fetchmany(chunk_size)`;
- particionamento por range;
- pool capacity por tipo de banco;
- `BoundedChunkQueue`;
- spill em disco;
- cancelamento cooperativo;
- `JsonlStreamer` para materializacao incremental.

### O que o Flowfile faz melhor

O Flowfile padroniza execucao remota/task-based para conectores variados.

### O que mudar no Shift

Manter a estrategia SQL atual e envolver em um contrato comum de task quando necessario.

### Ganho esperado

O Shift nao perde a engenharia atual de extracao e ainda ganha uniformidade operacional para novos conectores.

---

## 8. Export de pipeline para codigo

### O que o Flowfile faz

O Flowfile tem `FlowGraphToPolarsConverter` e `FlowGraphToFlowFrameConverter`.

Mais importante do que gerar codigo e o comportamento de erro:

- lista nos nao suportados;
- falha explicitamente;
- separa export standalone Polars de export FlowFrame com I/O.

### Como esta hoje no Shift

Nao ha export equivalente.

### O que mudaria no Shift

Criar um `ShiftPipelineExporter` com V1 limitada:

- SQL database;
- filter;
- mapper simples;
- join;
- lookup;
- aggregator;
- dedup;
- load/dataset writer.

Para nos nao suportados:

```text
Cannot export workflow:
- node ai_1 (aiNode): not deterministic/exportable in V1
- node http_3 (http_request): external side effect requires adapter
```

### Ganho esperado

- Debug local de pipelines.
- Revisao de transformacoes em PR.
- Reexecucao fora da UI.
- Base para "runbook" operacional.

### Cuidado

Nao prometer paridade total no inicio. Export parcial com erro bom e mais valioso que export "quase certo".

---

## 9. Parametrizacao

### O que o Flowfile faz

O Flowfile resolve `${param}` em settings e valida se restaram placeholders nao resolvidos. Isso gera falha rapida e clara.

### Como esta hoje no Shift

O Shift resolve dados/contexto em pontos diferentes (`resolve_data`, parameters de SQL script, injection de connections). Isso funciona, mas nao ha uma etapa global visivel de validacao de parametros do workflow antes do primeiro no rodar.

### O que mudaria no Shift

Adicionar um `WorkflowParameterResolver` antes da execucao:

- resolve `${var}`;
- valida obrigatorios;
- mascara segredos;
- falha antes de qualquer side effect;
- registra parametros efetivos no inicio da execucao, com redaction.

### Ganho esperado

- Menos execucoes parcialmente iniciadas que falham em no intermediario por parametro ausente.
- Melhor UX de erro.
- Melhor reproducibilidade.

### Cuidado

Separar parametro de workflow de referencia a dado upstream. Nem tudo que parece template deve ser resolvido antes: `sql_script.py` ja tem cuidado para nao pre-resolver bindings que dependem de linha/upstream.

---

## 10. Arquitetura alvo proposta para o Shift

```text
Workflow Run
  |
  v
Parameter Resolver
  |
  v
ExecutionPlan Builder
  |
  v
ExecutionStrategyResolver
  |
  +--> SKIP / checkpoint / cache
  |
  +--> LOCAL_THREAD
  |       - control flow
  |       - transforms leves
  |
  +--> DATA_WORKER
          - join grande
          - lookup grande
          - aggregation pesada
          - dedup pesado

Outputs
  |
  v
Dataset Registry
  |
  v
Dataset Triggers
```

Essa arquitetura preserva o que o Shift tem de melhor:

- DuckDB refs;
- streaming SQL;
- runner assíncrono;
- observabilidade.

E adiciona o que o Flowfile tem de melhor:

- decisao central;
- worker isolado;
- catalogo;
- triggers por dado;
- export.

---

## 11. Roadmap implementavel

## Fase 0: instrumentacao sem mudar comportamento

Objetivo: preparar terreno com baixo risco.

Entregas:

- `ExecutionPlanSnapshot`;
- `NodeExecutionProfile`;
- `StrategyDecision` apenas em modo observacao;
- log/evento com estrategia prevista;
- hash semantico calculado mas sem skip automatico.

Ganho:

- validar heuristicas com execucoes reais antes de mudar runtime.

## Fase 1: policy engine ativo

Objetivo: centralizar decisao.

Entregas:

- `ExecutionStrategyResolver`;
- integracao com checkpoint/cache/disabled/pinned;
- testes de matriz de decisao.

Ganho:

- runner mais previsivel;
- base para worker.

## Fase 2: worker local por subprocess

Objetivo: isolar transformacoes caras sem rede.

Entregas:

- `DataWorkerRuntime` local;
- `submit/status/cancel` em memoria;
- suporte inicial para `join`, `lookup`, `aggregator`, `dedup`;
- output como `DuckDbReference`.

Ganho:

- isolamento real de memoria/cancelamento para operacoes mais perigosas.

## Fase 3: Dataset Registry

Objetivo: transformar outputs em ativos reutilizaveis.

Entregas:

- tabelas `datasets` e `dataset_versions`;
- `dataset_writer`;
- `dataset_reader`;
- schema fingerprint;
- lineage com `producer_execution_id`.

Ganho:

- base para catalogo e triggers.

## Fase 4: triggers orientados a dataset

Objetivo: disparar workflows por dado pronto.

Entregas:

- `dataset_trigger`;
- `dataset_set_trigger`;
- push path no writer;
- poll reconciler;
- guardas anti-duplo-disparo.

Ganho:

- orquestracao muito mais madura que cron puro.

## Fase 5: export para codigo

Objetivo: portabilidade e auditoria.

Entregas:

- exporter V1;
- cobertura parcial declarada;
- erros explicitos para nos nao suportados;
- testes snapshot.

Ganho:

- pipelines revisaveis e reexecutaveis fora da UI.

---

## 12. Matriz de impacto, esforco e risco

| Iniciativa | Impacto | Esforco | Risco | Prioridade |
|---|---:|---:|---:|---:|
| ExecutionPlanSnapshot | Alto | Baixo | Baixo | P0 |
| StrategyDecision em modo observacao | Alto | Baixo | Baixo | P0 |
| ExecutionStrategyResolver ativo | Alto | Medio | Medio | P0 |
| Hash semantico por no | Alto | Medio | Medio | P1 |
| Worker local subprocessado | Muito alto | Medio/alto | Medio | P1 |
| Dataset Registry minimo | Muito alto | Medio | Medio | P1 |
| Dataset triggers | Muito alto | Medio | Medio/alto | P2 |
| Export para codigo | Alto | Medio | Medio | P2 |
| Virtual datasets | Alto | Alto | Alto | P3 |
| Kafka/GA4/cloud parity | Medio | Medio/alto | Medio | P3 |

---

## 13. KPIs para saber se valeu a pena

Medir antes e depois:

1. P95 de duracao por tipo de workflow.
2. P95 de memoria RSS durante execucao.
3. Numero de cancelamentos por pressao de memoria.
4. Tempo medio para cancelamento efetivo.
5. Taxa de cache/checkpoint hit.
6. Taxa de recomputacao evitada por hash semantico.
7. Latencia entre dataset atualizado e workflow dependente iniciado.
8. Numero de execucoes cron sem dados novos.
9. Falhas por timeout em join/aggregator/lookup.
10. Tempo de debug: execucao com plano e strategy decision vs sem.

---

## 14. Anti-recomendacoes

Nao copiar agora:

1. **FlowFrame como dependencia central**
   O Shift ja tem DuckDB como bom runtime. Trocar o eixo para FlowFrame aumentaria risco sem ganho imediato.

2. **Virtual table completa antes de registry fisico**
   Sem dataset versionado, virtual table fica dificil de invalidar corretamente.

3. **Worker remoto antes de worker local**
   Primeiro provar o contrato e o ganho de isolamento em subprocess local.

4. **Cache automatico de transformacao antes de hash confiavel**
   Cache errado em ETL e uma classe perigosa de bug: resultado parece correto, mas esta obsoleto.

5. **Copiar todos os conectores**
   Melhor copiar o contrato operacional de conector e adicionar fontes conforme demanda real.

---

## 15. Conclusao

O Shift nao precisa virar Flowfile. O melhor caminho e usar o Flowfile como referencia para maturar as fronteiras internas do Shift.

O Shift deve manter:

- DuckDB como contrato principal de dados intermediarios;
- streaming SQL particionado;
- runner assíncrono com eventos;
- cache de extracao;
- observabilidade existente.

O Shift deve copiar:

- plano de execucao como artefato;
- policy engine por no;
- taxonomia narrow/wide/io/control;
- worker isolado para transformacoes caras;
- dataset registry;
- triggers por atualizacao de dado;
- export para codigo;
- parametrizacao fail-fast.

Essa combinacao entrega o maior ganho: mais confiabilidade em grande volume, menos risco de OOM, melhor governanca de dados, e uma base mais limpa para crescer o produto sem transformar o runner principal em um bloco monolitico de regras especiais.

---

## 16. Checklist de implementacao sugerido

1. Criar `NodeExecutionProfile` para todos os node types existentes.
2. Criar `ExecutionPlanSnapshot` e persistir em cada run.
3. Criar `ExecutionStrategyResolver` em modo observacao.
4. Adicionar `strategy_decision` aos eventos de no.
5. Criar `semantic_hash` versionado para `sql_database`, `join`, `lookup`, `aggregator`.
6. Implementar worker local para `join`.
7. Migrar `lookup`, `aggregator`, `dedup` para worker quando strategy pedir.
8. Criar `datasets` e `dataset_versions`.
9. Adicionar `dataset_writer` e `dataset_reader`.
10. Implementar `dataset_trigger` com push e poll.
11. Implementar `dataset_set_trigger`.
12. Criar exporter V1 com cobertura parcial e erros explicitos.

---

## 17. Referencias de codigo

### Flowfile

- `D:\Labs\Flowfile\flowfile_core\flowfile_core\flowfile\flow_graph.py`
- `D:\Labs\Flowfile\flowfile_core\flowfile_core\flowfile\util\execution_orderer.py`
- `D:\Labs\Flowfile\flowfile_core\flowfile_core\flowfile\flow_node\executor.py`
- `D:\Labs\Flowfile\flowfile_core\flowfile_core\flowfile\flow_node\state.py`
- `D:\Labs\Flowfile\flowfile_core\flowfile_core\flowfile\flow_data_engine\flow_data_engine.py`
- `D:\Labs\Flowfile\flowfile_core\flowfile_core\flowfile\flow_data_engine\subprocess_operations\subprocess_operations.py`
- `D:\Labs\Flowfile\flowfile_worker\flowfile_worker\streaming.py`
- `D:\Labs\Flowfile\flowfile_worker\flowfile_worker\routes.py`
- `D:\Labs\Flowfile\flowfile_worker\flowfile_worker\process_manager.py`
- `D:\Labs\Flowfile\flowfile_worker\flowfile_worker\utils.py`
- `D:\Labs\Flowfile\flowfile_core\flowfile_core\catalog\service.py`
- `D:\Labs\Flowfile\flowfile_scheduler\flowfile_scheduler\engine.py`
- `D:\Labs\Flowfile\flowfile_core\flowfile_core\flowfile\parameter_resolver.py`
- `D:\Labs\Flowfile\flowfile_core\flowfile_core\flowfile\code_generator\code_generator.py`
- `D:\Labs\Flowfile\flowfile_core\flowfile_core\configs\node_store\nodes.py`

### Shift

- `D:\Labs\shift-project\shift-backend\app\orchestration\flows\dynamic_runner.py`
- `D:\Labs\shift-project\shift-backend\app\orchestration\tasks\node_processor.py`
- `D:\Labs\shift-project\shift-backend\app\services\memory_monitor.py`
- `D:\Labs\shift-project\shift-backend\app\services\extraction_service.py`
- `D:\Labs\shift-project\shift-backend\app\services\extract_cache_service.py`
- `D:\Labs\shift-project\shift-backend\app\services\scheduler_service.py`
- `D:\Labs\shift-project\shift-backend\app\data_pipelines\duckdb_storage.py`
- `D:\Labs\shift-project\shift-backend\app\services\streaming\bounded_chunk_queue.py`
- `D:\Labs\shift-project\shift-backend\app\services\workflow\nodes\join_node.py`
- `D:\Labs\shift-project\shift-backend\app\services\workflow\nodes\lookup_node.py`
- `D:\Labs\shift-project\shift-backend\app\services\workflow\nodes\aggregator_node.py`
- `D:\Labs\shift-project\shift-backend\app\services\workflow\nodes\sql_script.py`
