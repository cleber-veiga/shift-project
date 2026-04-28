# Benchmarking de Performance: Flowfile -> Shift

## 1. Objetivo

Este documento analisa especificamente performance de execucao:

1. execucao interativa disparada pelo frontend;
2. execucao em segundo plano;
3. latencia percebida na tela;
4. throughput e estabilidade sob carga.

A analise compara o que o Flowfile faz em `D:\Labs\Flowfile` com o estado atual do Shift.

---

## 2. Conclusao executiva

O Shift ja e mais rico que o Flowfile em eventos estruturados de execucao para a UI. O Flowfile, por outro lado, e mais maduro em tres pontos que afetam performance real:

1. offload de computacao pesada para worker/subprocesso;
2. execucao com `performance_mode`, evitando geracao de preview/exemplo;
3. estrategia por no: `FULL_LOCAL`, `LOCAL_WITH_SAMPLING`, `REMOTE`, `SKIP`.

O maior ganho para o Shift viria de combinar o melhor dos dois:

- manter SSE estruturado para UX;
- reduzir payload do SSE;
- separar preview de execucao full;
- introduzir worker/process pool para nodes pesados;
- diferenciar fila interativa de fila background;
- usar cache semantico de transformacoes, nao so de extracao.

---

## 3. Como o Flowfile executa pelo frontend

## 3.1 Caminho interativo

No Flowfile, o frontend chama:

- `POST /flow/run/`;
- depois faz polling em `GET /flow/run_status/`;
- logs sao consumidos separadamente via `GET /logs/{flow_id}` com `EventSource`.

Arquivos:

- `D:\Labs\Flowfile\flowfile_core\flowfile_core\routes\routes.py`
- `D:\Labs\Flowfile\flowfile_core\flowfile_core\routes\logs.py`
- `D:\Labs\Flowfile\flowfile_frontend\src\renderer\app\composables\useFlowExecution.ts`
- `D:\Labs\Flowfile\flowfile_frontend\src\renderer\app\views\DesignerView\LogViewer\LogViewer.vue`

O endpoint `/flow/run/` nao fica aguardando a execucao terminar. Ele adiciona `_run_and_track` em `BackgroundTasks` e retorna rapidamente:

```python
background_tasks.add_task(_run_and_track, flow, user_id)
return JSONResponse({"message": "Data started", "flow_id": flow_id})
```

Depois a tela consulta status periodicamente:

```ts
setInterval(checkFn, pollingConfig.interval || 2000)
```

### Leitura tecnica

Esse modelo tem uma vantagem: o request de executar e rapido. A UI nao fica presa no request principal.

Mas tem desvantagens:

- polling de 2s pode dar sensacao de atraso;
- status e menos granular que eventos estruturados por node;
- logs por arquivo sao bons para debug, mas nao sao ideais como modelo de estado da UI.

## 3.2 Comparacao com Shift

O Shift usa stream de eventos para execucao teste/interativa. Isso e melhor para UX em tempo real.

Porem, hoje o Shift paga alguns custos:

- salva workflow antes de executar;
- carrega eventos no array `execEvents`;
- reconstroi estado do painel a partir de todos os eventos;
- manda output no evento `node_complete`;
- `wait=True` mantem a request SSE acoplada ao run.

### Recomendacao

Nao trocar SSE por polling como o Flowfile. O melhor e manter SSE, mas copiar do Flowfile a ideia de "start rapido + execucao desacoplada".

Modelo recomendado:

1. frontend envia `POST /test/start`;
2. backend retorna `execution_id` imediatamente;
3. frontend abre `GET /executions/{id}/events`;
4. runner executa desacoplado, mesmo para teste;
5. eventos ficam em buffer/stream leve.

Isso preserva UX em tempo real e reduz acoplamento request-run.

---

## 4. Performance percebida na tela

## 4.1 Gargalo atual provavel no Shift

No frontend do Shift, a execucao interativa faz:

1. salvar workflow;
2. abrir stream;
3. a cada evento, fazer `setExecEvents((prev) => [...prev, event])`;
4. o painel recalcula `buildNodeStates(events)` a cada render.

Esse padrao degrada conforme o numero de eventos cresce. Em workflows grandes, cada novo evento copia a lista inteira e força recomputacao.

## 4.2 O que Flowfile evita

O Flowfile nao tenta transformar cada evento em estrutura rica no frontend. Ele:

- congela o canvas;
- inicia run;
- faz polling de status;
- streama logs como texto.

Ou seja, ele evita parte da pressao de renderizacao incremental. A contrapartida e uma UX menos precisa.

## 4.3 O que copiar para o Shift

Copiar a simplicidade operacional, nao a perda de granularidade.

Mudancas recomendadas:

1. Substituir `execEvents[]` como fonte de verdade por reducer incremental.
2. Manter apenas ring buffer de eventos recentes para log visual.
3. Guardar estado de node em map:

```ts
{
  order: string[],
  byNodeId: {
    "node_1": {
      status: "running",
      started_at: "...",
      progress: {...}
    }
  }
}
```

4. Fazer `ExecutionPanel` receber `nodeStates` pronto, nao reconstruir a partir do historico inteiro.
5. Enviar dados detalhados sob demanda quando usuario seleciona o node.

### Ganho esperado

- menos renders caros;
- menos parsing JSON grande;
- tela mais responsiva em workflows com muitos nodes/loops;
- menor memoria no browser.

---

## 5. Worker e offload: principal ganho do Flowfile

## 5.1 O que o Flowfile faz

O Flowfile usa um worker separado para operacoes pesadas. O core envia LazyFrame serializado, o worker cria subprocesso e retorna resultado.

Arquivos:

- `D:\Labs\Flowfile\flowfile_worker\flowfile_worker\streaming.py`
- `D:\Labs\Flowfile\flowfile_worker\flowfile_worker\process_manager.py`
- `D:\Labs\Flowfile\flowfile_core\flowfile_core\flowfile\flow_data_engine\subprocess_operations\subprocess_operations.py`

Pontos importantes:

- WebSocket para payload binario;
- fallback REST/polling;
- status por `task_id`;
- cancelamento real com processo;
- progresso;
- resultado em arquivo/cache.

## 5.2 Como esta no Shift

O Shift executa processadores via `asyncio.to_thread`. Isso evita bloquear o event loop, mas nao isola memoria/CPU do processo FastAPI.

Para background e execucao interativa, isso significa que transformacoes pesadas podem competir com API/SSE.

## 5.3 O que copiar

Criar um `DataWorkerRuntime` no Shift.

Mas diferente do Flowfile, o contrato principal deve ser `DuckDbReference`, nao LazyFrame:

```json
{
  "task_id": "...",
  "execution_id": "...",
  "node_type": "join",
  "input_refs": {
    "left": {"database_path": "...", "table_name": "..."},
    "right": {"database_path": "...", "table_name": "..."}
  },
  "config": {}
}
```

### Ganho esperado

- background nao degrada tanto o FastAPI;
- tela continua respondendo mesmo com join/agregacao grande;
- cancelamento mais efetivo;
- CPU/memoria por task ficam observaveis.

---

## 6. Performance mode e preview

## 6.1 O que o Flowfile faz

O Flowfile tem `performance_mode`. Em varios pontos, quando esse modo esta ativo, ele evita gerar example data/preview.

No `FlowNode`:

- `performance_mode=True` pula geracao de example data;
- `LOCAL_WITH_SAMPLING` executa transformacao local, mas joga sampling para worker;
- `REMOTE` materializa ou busca resultado pesado remotamente.

Isso e uma separacao importante:

- executar pipeline;
- gerar preview para UI;
- materializar cache.

## 6.2 Como esta no Shift

O Shift tem `run_mode=preview|full|validate` e `preview_max_rows`, mas o caminho de botao/teste ainda mistura execucao com retorno de outputs para painel.

## 6.3 O que potencializar

Definir tres modos de execucao bem diferentes:

| Modo | Uso | Comportamento |
|---|---|---|
| `validate` | antes de rodar | resolve parametros, conexoes, schema quando possivel |
| `preview` | botao frontend | limita linhas, outputs pequenos, sem side effects perigosos por default |
| `full` | background/producao | executa completo, sem mandar payload pesado para UI |

### Ganho esperado

- botao "Executar" na tela responde mais rapido;
- preview fica barato;
- full run nao carrega custo de UI;
- menos serializacao de dados em evento.

---

## 7. Background execution

## 7.1 O que o Flowfile faz

O Flowfile cria run record antes da execucao e completa depois. Para scheduler, tem engine separado com lock e triggers.

Pontos fortes:

- run fica visivel como ativo antes de terminar;
- scheduler evita duplicidade com active run;
- table trigger reduz runs desnecessarios.

## 7.2 Como esta no Shift

O Shift ja cria `WorkflowExecution`, roda em background com `asyncio.create_task`, usa `execution_registry`, semaforos globais/por projeto e APScheduler para cron.

Isso e bom. O que falta e separacao de lanes:

- execucao interativa;
- execucao background;
- execucao scheduler;
- execucao pesada em worker.

## 7.3 O que potencializar

1. Fila de background duravel.
2. Prioridade para execucao interativa.
3. Pool separado para compute pesado.
4. Rate limit por workspace/projeto.
5. Worker autoscaling futuro.

### Recomendacao de arquitetura

```text
FastAPI
  - API
  - SSE leve
  - preflight

Runner Coordinator
  - monta plano
  - decide estrategia
  - publica tasks

Interactive Worker Pool
  - previews
  - runs manuais curtos

Background Worker Pool
  - cron
  - API full
  - retries

Data Worker Pool
  - joins
  - aggregations
  - fuzzy
  - pivot
```

---

## 8. Melhorias de maior impacto para o Shift

## P0: melhora de tela rapida

1. Executar draft sem salvar antes.
2. Reducer incremental no frontend.
3. SSE sem payload pesado.
4. Lazy fetch de output quando usuario clica no node.
5. Preview mode como default para botao de tela.

## P1: melhora de engine

1. `ExecutionStrategyResolver`.
2. Worker local subprocessado para nodes wide.
3. Cache semantico de transformacoes.
4. Separar `preview` de `full` de forma rigida.

## P2: melhora de background

1. Fila duravel.
2. Prioridade por lane.
3. Dataset triggers para reduzir cron vazio.
4. Worker pool separado para scheduler/background.

---

## 9. O que eu copiaria diretamente do Flowfile para performance

1. `performance_mode`: separar execucao de geracao de preview.
2. `LOCAL_WITH_SAMPLING`: executar transformacao leve e mandar apenas sample para worker/UI.
3. `REMOTE`: offload de operacao pesada.
4. Worker com `task_id`, `status`, `cancel`, `fetch`.
5. WebSocket binario ou protocolo equivalente para resultados quando fizer sentido.
6. Cache por hash para evitar recomputacao.
7. Table trigger para reduzir execucoes background sem dado novo.

---

## 10. O que eu nao copiaria do Flowfile

1. Polling de status a cada 2s como principal UX do Shift.
   O Shift ja tem SSE estruturado; isso e melhor.

2. Log textual como principal fonte de estado da UI.
   Log e para debug; estado visual deve vir de evento estruturado.

3. Payload Polars LazyFrame como contrato principal.
   O Shift deve continuar DuckDB-first.

4. BackgroundTask do FastAPI como modelo final de execucao pesada.
   Serve para app desktop/local, mas em produto web multi-tenant o ideal e fila/worker.

---

## 11. Ranking final de ganhos

| Mudanca | Impacto na tela | Impacto background | Esforco | Prioridade |
|---|---:|---:|---:|---:|
| Reducer incremental no frontend | Muito alto | Baixo | Baixo | P0 |
| SSE leve sem output pesado | Muito alto | Medio | Baixo/medio | P0 |
| Executar draft sem salvar | Alto | Baixo | Medio | P0 |
| Preview mode rigoroso | Alto | Medio | Medio | P0 |
| Worker subprocessado | Alto | Muito alto | Medio/alto | P1 |
| Strategy resolver | Medio | Alto | Medio | P1 |
| Cache semantico transformacoes | Muito alto | Muito alto | Medio/alto | P1 |
| Fila background duravel | Baixo | Muito alto | Alto | P2 |
| Dataset triggers | Baixo | Alto | Medio/alto | P2 |

---

## 12. Conclusao

O Flowfile confirma que o maior salto de performance para o Shift nao vem de trocar framework nem de reescrever tudo. Vem de separar responsabilidades:

- UI recebe eventos pequenos e incrementais;
- preview nao e full run;
- FastAPI nao executa compute pesado;
- worker/processo isolado roda transformacoes caras;
- background tem fila e prioridade propria;
- cache evita recomputacao.

Para execucao pelo frontend, a prioridade deve ser reduzir latencia percebida e custo de renderizacao. Para background, a prioridade deve ser throughput, isolamento e filas. O Shift ja tem uma base melhor que o Flowfile em eventos estruturados, mas deve copiar do Flowfile o desenho de offload, performance mode e estrategia por no.

