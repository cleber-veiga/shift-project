# Flowfile — Leitura técnica de mecanismos (companion técnico)

Este documento é **complementar** aos três benchmarks já existentes na raiz do repo:

- [`benchmarking_flowfile_shift.md`](../benchmarking_flowfile_shift.md) — arquitetura geral e roadmap
- [`benchmarking_flowfile_nodes_shift.md`](../benchmarking_flowfile_nodes_shift.md) — catálogo de nós
- [`benchmarking_flowfile_performance_shift.md`](../benchmarking_flowfile_performance_shift.md) — execução / UX

Aqueles três cobrem **o que copiar e por quê**. Este documento cobre **como cada mecanismo está implementado de fato no Flowfile** — código real, com caminhos de arquivo e snippets curtos. Serve para o engenheiro que vai implementar cada item olhar uma referência concreta antes de escrever a versão Shift.

Todos os caminhos abaixo são relativos a `D:/Labs/Flowfile/`. Stack do Shift de referência: FastAPI + APScheduler + asyncio runner em [shift-backend/app/orchestration/flows/dynamic_runner.py](../shift-backend/app/orchestration/flows/dynamic_runner.py); frontend Next.js + React Flow em [shift-frontend/components/workflow/](../shift-frontend/components/workflow/). Prefect **não** é usado no Shift.

---

## 1. Strategy resolver — decisão central de execução

**Por que importa:** É exatamente o "policy engine por nó" recomendado em `benchmarking_flowfile_shift.md §4.2`. Mostro aqui o código de fato.

**Arquivo:** `flowfile_core/flowfile_core/flowfile/flow_node/executor.py:158`

O método `_decide_execution()` é o **único ponto** que responde "este nó deve rodar?". Tudo encadeia retornos de um `ExecutionDecision(should_run, strategy, reason)` — sem `if` espalhado.

```python
def _decide_execution(
    self,
    state: NodeExecutionState,
    run_location: schemas.ExecutionLocationsLiteral,
    performance_mode: bool,
    force_refresh: bool,
) -> ExecutionDecision:
    # Output nodes always run
    if self.node.node_template.node_group == "output":
        strategy = self._determine_strategy(run_location)
        return ExecutionDecision(True, strategy, InvalidationReason.OUTPUT_NODE)

    # Forced refresh (reset_cache=True)
    if force_refresh:
        strategy = self._determine_strategy(run_location)
        return ExecutionDecision(True, strategy, InvalidationReason.FORCED_REFRESH)

    # Cache-enabled nodes: check if cache file is still present
    if self.node.node_settings.cache_results:
        if results_exists(self.node.hash):
            return ExecutionDecision(False, ExecutionStrategy.SKIP, None)
        strategy = self._determine_strategy(run_location)
        return ExecutionDecision(True, strategy, InvalidationReason.CACHE_MISSING)

    # Never ran before
    if not state.has_run_with_current_setup:
        strategy = self._determine_strategy(run_location)
        return ExecutionDecision(True, strategy, InvalidationReason.NEVER_RAN)
```

E o **`_determine_strategy()`** logo abaixo encapsula o mapping `(local_run × tipo_de_transform × cache) → estratégia`:

**Arquivo:** `flowfile_core/flowfile_core/flowfile/flow_node/executor.py:208`

```python
def _determine_strategy(self, run_location: schemas.ExecutionLocationsLiteral) -> ExecutionStrategy:
    if run_location == "local":
        return ExecutionStrategy.FULL_LOCAL
    if self.node.node_settings.cache_results:
        return ExecutionStrategy.REMOTE  # caching needs full materialization
    if self.node.node_default is not None and self.node.node_default.transform_type == "narrow":
        return ExecutionStrategy.LOCAL_WITH_SAMPLING
    return ExecutionStrategy.REMOTE
```

**Como adaptar no Shift:** crie `shift-backend/app/orchestration/flows/strategy_resolver.py` com a mesma forma — `StrategyDecision(should_run, strategy, reason)` e dispatch por `NODE_EXECUTION_PROFILE` (ver `benchmarking_flowfile_shift.md §4.2`). Os enums precisam ser diferentes — Shift não tem `LOCAL_WITH_SAMPLING` (não há sampler externo) nem `REMOTE` (não há worker remoto inicialmente). Use `SKIP / LOCAL_THREAD / DATA_WORKER`.

---

## 2. Worker offload — protocolo HTTP cliente/servidor

**Por que importa:** Worker isolado é a recomendação P1 do roadmap. O Flowfile usa um padrão minimalista que vale ser conhecido.

**Cliente (no core).** Envia o LazyFrame como **bytes Polars** no body, com metadata em headers — sem JSON wrapping. Isso é a economia que permite que o handshake seja rápido.

**Arquivo:** `flowfile_core/flowfile_core/flowfile/flow_data_engine/subprocess_operations/subprocess_operations.py:37`

```python
def trigger_df_operation(flow_id, node_id, lf, file_ref, operation_type="store", kwargs=None):
    headers = {
        "Content-Type": "application/octet-stream",
        "X-Task-Id": file_ref,
        "X-Operation-Type": operation_type,
        "X-Flow-Id": str(flow_id),
        "X-Node-Id": str(node_id),
    }
    if kwargs:
        headers["X-Kwargs"] = json.dumps(kwargs)
    v = requests.post(url=f"{WORKER_URL}/submit_query/", data=lf.serialize(), headers=headers)
    return Status(**v.json())
```

**Servidor (no worker).** Recebe os bytes, gera `task_id`, registra status em dict, dispara `BackgroundTasks` e retorna **imediatamente** com o status `Starting`.

**Arquivo:** `flowfile_worker/flowfile_worker/routes.py:34`

```python
@router.post("/submit_query/")
async def submit_query(request: Request, background_tasks: BackgroundTasks) -> models.Status:
    polars_serializable_object = await request.body()
    task_id = request.headers.get("X-Task-Id") or str(uuid.uuid4())
    operation_type = request.headers.get("X-Operation-Type", "store")
    flow_id = int(request.headers.get("X-Flow-Id", "1"))
    node_id = request.headers.get("X-Node-Id", "-1")

    default_cache_dir = create_and_get_default_cache_dir(flow_id)
    file_path = os.path.join(default_cache_dir, f"{task_id}.arrow")

    status = models.Status(background_task_id=task_id, status="Starting", file_ref=file_path, result_type="polars")
    status_dict[task_id] = status

    background_tasks.add_task(
        start_process,
        polars_serializable_object=polars_serializable_object,
        task_id=task_id,
        operation=operation_type,
        file_ref=file_path,
        flowfile_flow_id=flow_id,
        flowfile_node_id=node_id,
        kwargs=kwargs,
    )
    return status
```

**Como adaptar no Shift:** o contrato deve ser `DuckDbReference`, não LazyFrame Polars (ver `benchmarking_flowfile_shift.md §4.3`). Use `application/json` com refs a arquivos DuckDB no body — mais natural para o stack atual. O padrão "submit retorna task_id imediatamente, polling em /status/{task_id}" é o que importa.

---

## 3. Code generation reverso — DAG visual → script Python autônomo

**Por que importa:** Recomendação `benchmarking_flowfile_shift.md §8`. É um diferencial competitivo (transparência, vendor lock-in escape) e custa relativamente pouco.

**Entry point:** ordena topologicamente, despacha por nó, falha explicitamente em nós não suportados — listando todos antes de retornar.

**Arquivo:** `flowfile_core/flowfile_core/flowfile/code_generator/code_generator.py:47`

```python
def convert(self) -> str:
    stages = determine_execution_order(
        all_nodes=[node for node in self.flow_graph.nodes if node.is_correct],
        flow_starts=self.flow_graph._flow_starts + self.flow_graph.get_implicit_starter_nodes(),
    )
    for node in (node for stage in stages for node in stage):
        self._generate_node_code(node)

    if self.unsupported_nodes:
        error_messages = []
        for node_id, node_type, reason in self.unsupported_nodes:
            error_messages.append(f"  - Node {node_id} ({node_type}): {reason}")
        raise UnsupportedNodeError(
            node_type=self.unsupported_nodes[0][1],
            node_id=self.unsupported_nodes[0][0],
            reason=(
                f"The flow contains {len(self.unsupported_nodes)} node(s) that cannot be converted to code:\n"
                + "\n".join(error_messages)
            ),
        )
    return self._build_final_code()
```

**Gerador por nó (filter como exemplo):** delega expressões avançadas a `polars_expr_transformer.simple_function_to_expr` e gera fallback "no filter applied" quando o filtro está incompleto.

**Arquivo:** `flowfile_core/flowfile_core/flowfile/code_generator/code_generator.py:227`

```python
def _handle_filter(self, settings, var_name, input_vars):
    input_df = input_vars.get("main", "df")
    if settings.filter_input.is_advanced():
        self.imports.add(
            "from polars_expr_transformer.process.polars_expr_transformer import simple_function_to_expr"
        )
        self._add_code(f"{var_name} = {input_df}.filter(")
        self._add_code(f'simple_function_to_expr("{settings.filter_input.advanced_filter}")')
        self._add_code(")")
    else:
        basic = settings.filter_input.basic_filter
        if basic is not None and basic.field:
            filter_expr = self._create_basic_filter_expr(basic)
            self._add_code(f"{var_name} = {input_df}.filter({filter_expr})")
        else:
            self._add_code(f"{var_name} = {input_df}  # No filter applied")
```

**Como adaptar no Shift:** crie `shift-backend/app/services/workflow/exporters/sql_exporter.py` que gere SQL DuckDB+dlt, não Polars. Padrão idêntico: dispatch por `node_type`, lista de não-suportados acumulada, erro explícito ao final. V1 cobrindo `sql_database, filter, mapper, join, lookup, aggregator, deduplication, load` é suficiente para mostrar valor.

---

## 4. Parameter resolver — `${var}` recursivo em BaseModel

**Por que importa:** O Shift hoje resolve em pontos isolados; falta uma etapa global pré-execução com **fail-fast** (ver `benchmarking_flowfile_shift.md §9`).

O ponto não-óbvio: o resolver mantém **lista de restaurações** porque Pydantic models são mutados in-place. Após a execução, você pode reverter para preservar a definição original do workflow para a próxima run.

**Arquivo:** `flowfile_core/flowfile_core/flowfile/parameter_resolver.py:18`

```python
def resolve_parameters(text: str, params: dict[str, str]) -> str:
    """Replace ${name} patterns. Unknown references are left unchanged."""
    if not params or "${" not in text:
        return text
    return _PARAM_PATTERN.sub(lambda m: params.get(m.group(1), m.group(0)), text)


def apply_parameters_in_place(obj: Any, params: dict[str, str]) -> _Restorations:
    """Mutate obj's string fields in place, substituting ${name} patterns.
    Returns (target, field, original_value) triples for later restoration."""
    if not params or obj is None:
        return []

    restorations: _Restorations = []
    _apply_recursive(obj, params, restorations)

    # Validate: no unresolved refs should remain — fail-fast
    unresolved = find_unresolved_in_model(obj)
    if unresolved:
        restore_parameters(restorations)
        raise ValueError(
            f"Unresolved parameter references in node settings: {sorted(unresolved)}. "
            "Check that all referenced parameters are defined on the flow."
        )
    return restorations


def _apply_recursive(obj, params, restorations):
    if isinstance(obj, BaseModel):
        for field_name in obj.model_fields:
            value = getattr(obj, field_name, None)
            if isinstance(value, str) and "${" in value:
                resolved = resolve_parameters(value, params)
                if resolved != value:
                    restorations.append((obj, field_name, value))
                    object.__setattr__(obj, field_name, resolved)
            elif isinstance(value, (BaseModel, dict, list)):
                _apply_recursive(value, params, restorations)
```

**Como adaptar no Shift:** `shift-backend/app/orchestration/flows/parameter_resolver.py`. O Shift já tem `variables-panel.tsx` no frontend — falta o resolver server-side recursivo + validação fail-fast antes de qualquer side effect. Atenção em `sql_script.py` que **propositalmente** não pre-resolve bindings runtime: aplique apenas em settings estáticos.

---

## 5. Schema callback — predicted schema sem rodar

**Por que importa:** Permite que o frontend mostre colunas downstream com warnings ("coluna `X` não está mais disponível") **antes** de executar. Recomendação `benchmarking_flowfile_shift.md` (validação visual de schema).

A engenhosidade está em `SingleExecutionFuture` — uma promise que executa **uma vez**, cacheia o resultado, e tem error_callback dedicado para não quebrar quando o setup do nó está incompleto.

**Arquivo:** `flowfile_core/flowfile_core/flowfile/flow_node/flow_node.py:248`

```python
@property
def schema_callback(self) -> SingleExecutionFuture:
    """Lazy-creates schema prediction callback. Used to predict output schema
    without full execution."""
    if self._schema_callback is None:
        if self.user_provided_schema_callback is not None:
            self.schema_callback = self.user_provided_schema_callback
        elif self.is_start:
            self.schema_callback = self.create_schema_callback_from_function(self._function)
    return self._schema_callback

@schema_callback.setter
def schema_callback(self, f: Callable):
    if f is None:
        return

    output_field_config = getattr(self._setting_input, "output_field_config", None)
    if output_field_config and output_field_config.enabled:
        f = create_schema_callback_with_output_config(f, output_field_config)

    def error_callback(e: Exception) -> list:
        logger.warning(e)
        self.node_settings.setup_errors = True
        return []

    self._schema_callback = SingleExecutionFuture(f, error_callback)
```

**Como adaptar no Shift:** isso é um esforço **alto** porque exige que cada processor declare como prevê seu schema dado o schema de input. Uma versão pragmática V1 cobre só o caminho fácil — `sql_database` retorna `cursor.description`, `mapper`/`select` retornam lista declarada, `filter` passa input adiante, `join` faz merge dos dois inputs. `aggregator`, `pivot`, `code_node` ficam como "schema desconhecido" até executar.

---

## 6. NodeExecutionState — separação `definition` vs `runtime state`

**Por que importa:** Recomendação `benchmarking_flowfile_shift.md §5.1`. É o pré-requisito arquitetural para cache semântico, dry-run e execução stateless.

A chave: `FlowNode` (definição) é separado de `NodeExecutionState` (mutável). Cada execução tem o seu state, e o state pode ser persistido/recuperado.

**Arquivo:** `flowfile_core/flowfile_core/flowfile/flow_node/state.py:58`

```python
@dataclass
class NodeExecutionState:
    """All mutable state for a node's execution.

    This can be:
    - Stored in memory (current behavior)
    - Persisted to database (stateless workers)
    - Stored in Redis/cache (distributed execution)
    """
    has_run_with_current_setup: bool = False
    has_completed_last_run: bool = False
    is_canceled: bool = False
    error: str | None = None

    # Results (not serialized - too large)
    resulting_data: FlowDataEngine | None = field(default=None, repr=False)
    example_data_path: str | None = None
    example_data_generator: Callable[[], pa.Table] | None = field(default=None, repr=False)

    # Schema
    result_schema: list[FlowfileColumn] | None = field(default=None, repr=False)
    predicted_schema: list[FlowfileColumn] | None = field(default=None, repr=False)

    # Source tracking (for read nodes)
    source_file_info: SourceFileInfo | None = None

    # Hash for cache lookup
    execution_hash: str | None = None

    def reset(self) -> None:
        self.has_run_with_current_setup = False
        self.has_completed_last_run = False
        self.error = None

    def mark_successful(self) -> None:
        self.has_run_with_current_setup = True
        self.has_completed_last_run = True
        self.error = None

    def to_dict(self) -> dict:
        """Serialize for external storage (stateless mode)."""
        return {
            "has_run_with_current_setup": self.has_run_with_current_setup,
            "has_completed_last_run": self.has_completed_last_run,
            "execution_hash": self.execution_hash,
            "source_file_info": self.source_file_info.to_dict() if self.source_file_info else None,
        }
```

**Como adaptar no Shift:** o Shift tem `node_executions` no banco — formalize um `NodeRunState` Pydantic que espelhe esse modelo, com campos `semantic_hash`, `output_reference` (DuckDbReference serializado), `schema_fingerprint`, `row_count`. O `to_dict` aqui é o protocolo de persistência: o snapshot fica auditável e reusável.

---

## 7. Custom Node Designer — carregar nós Python em runtime

**Por que importa:** Permite usuários avançados estenderem a plataforma sem PR. É um item P3/longo prazo do `benchmarking_flowfile_shift.md`, mas o padrão é simples e elegante.

A receita são 7 linhas: `spec_from_file_location` + `module_from_spec` + `exec_module` + `inspect.getmembers` filtrando subclasses da base.

**Arquivo:** `flowfile_core/flowfile_core/configs/node_store/user_defined_node_registry.py:38`

```python
try:
    module_name = file_path.stem  # filename without extension
    spec = importlib.util.spec_from_file_location(module_name, file_path)

    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module  # handle imports within the module
        spec.loader.exec_module(module)

        # Inspect the module for CustomNodeBase subclasses
        for name, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and issubclass(obj, CustomNodeBase) and obj is not CustomNodeBase:
                node_name = getattr(obj, "node_name", name)
                custom_nodes[node_name] = obj
                print(f"Loaded custom node: {node_name} from {file_path.name}")

except Exception as e:
    print(f"Error loading module from {file_path}: {e}")
    continue
```

**Como adaptar no Shift:** Cuidado com **multi-tenant**. No Flowfile (desktop/single-user), carregar arbitrário Python é seguro. No Shift (multi-tenant SaaS), isso é uma porta de execução remota — exige sandboxing forte (kernel runtime já existe) ou um DSL declarativo restrito ao invés de Python livre. V1 pragmática: aceitar só "nós de transformação SQL" (template DuckDB com placeholders), não Python arbitrário.

---

## 8. Scheduler table-trigger — push path + poll path como safety net

**Por que importa:** O insight aqui é **dual path** — push imediato + poll de reconciliação. Não é só "trigger por evento". Fundamental para a recomendação de dataset triggers (`benchmarking_flowfile_shift.md §6.2`).

**Arquivo:** `flowfile_scheduler/flowfile_scheduler/engine.py:201`

```python
def _process_table_trigger_schedules(self, db: Session) -> int:
    """Detect table changes and launch table_trigger flows (poll path).

    A parallel **push path** exists in CatalogService._fire_table_trigger_schedules.
    The push path fires synchronously inside overwrite_table_data and is the
    primary/fast trigger. This poll path serves as a **safety net** — if the
    push path fails (exception, process crash, network error), this method will
    still detect the stale timestamp and launch the flow on the next tick.

    Double-firing is prevented by two guards:
    1. has_active_run (checked inside _maybe_launch)
    2. last_trigger_table_updated_at — the push path commits this value equal
       to table.updated_at before returning
    """
    schedules = (
        db.query(FlowSchedule)
        .filter(FlowSchedule.enabled.is_(True), FlowSchedule.schedule_type == "table_trigger")
        .all()
    )
    for sched in schedules:
        table = db.get(CatalogTable, sched.trigger_table_id)
        if table is None:
            continue
        table_updated = table.updated_at.replace(tzinfo=timezone.utc) if table.updated_at else None
        last_seen = (
            sched.last_trigger_table_updated_at.replace(tzinfo=timezone.utc)
            if sched.last_trigger_table_updated_at else None
        )
        if table_updated is not None and (last_seen is None or table_updated > last_seen):
            # ... launch ...
```

**Como adaptar no Shift:** APScheduler já é o tick natural para o poll path. O push path encaixa em `dataset_writer` — sempre que um workflow grava um dataset, ele dispara as schedules dependentes. Os dois guards (`has_active_run` + `last_trigger_dataset_version_id`) são essenciais; sem eles você terá execuções duplicadas.

---

## 9. flowfile_frame — Python DSL que constrói a mesma DAG do editor

**Por que importa:** Item de longo prazo. Permite usuário escrever pipeline em Python e abrir no editor visual (e vice-versa). É um padrão raro e poderoso.

A operação chave é `.filter()`: ela constrói uma string de **código Polars**, registra como nó no grafo, e retorna um novo `FlowFrame` (filho). Não executa nada — só monta a DAG.

**Arquivo:** `flowfile_frame/flowfile_frame/flow_frame.py:1085`

```python
def filter(self, *predicates, flowfile_formula=None, description=None, **constraints) -> FlowFrame:
    new_node_id = generate_node_id()
    if len(predicates) > 0 or len(constraints) > 0:
        all_input_expr_objects: list[Expr] = []
        pure_polars_expr_strings: list[str] = []

        for pred_input in predicates:
            current_expr_obj = (
                pred_input if isinstance(pred_input, Expr)
                else col(pred_input) if isinstance(pred_input, str) and pred_input in self.columns
                else lit(pred_input)
            )
            all_input_expr_objects.append(current_expr_obj)
            pure_expr_str, _ = _extract_expr_parts(current_expr_obj)
            pure_polars_expr_strings.append(f"({pure_expr_str})")

        for k, v in constraints.items():
            all_input_expr_objects.append(col(k) == lit(v))

        filter_conditions_str = " & ".join(pure_polars_expr_strings) if pure_polars_expr_strings else "pl.lit(True)"
        polars_operation_code = f"input_df.filter({filter_conditions_str})"

        precomputed = self._add_polars_code(
            new_node_id, polars_operation_code, description, method_name="filter",
        )
        return self._create_child_frame(new_node_id, precomputed_result=precomputed)
```

**E `open_graph_in_editor()`** — salva flow em arquivo, garante que servidor está rodando, importa via API, abre no browser. Não é IPC mágico, é HTTP + file:

**Arquivo:** `flowfile/flowfile/api.py:413`

```python
def open_graph_in_editor(flow_graph, storage_location=None, module_name=DEFAULT_MODULE_NAME,
                        automatically_open_browser=True) -> bool:
    flow_graph.flow_settings.execution_location = "local"
    flow_graph.flow_settings.execution_mode = "Development"
    flow_file_path, _ = _save_flow_to_location(flow_graph, storage_location)

    flow_running, flow_in_single_mode = start_flowfile_server_process(module_name)
    flow_graph.flow_settings.path = str(flow_file_path)

    auth_token = get_auth_token()
    flow_id = import_flow_to_editor(flow_file_path, auth_token)

    if flow_id is not None:
        if flow_in_single_mode and automatically_open_browser:
            _open_flow_in_browser(flow_id)
        return True
    return False
```

**Como adaptar no Shift:** público do Shift é menos técnico — o ROI é incerto. Se for fazer, comece com `tester-package/` evoluindo para SDK que constrói o JSON do workflow e faz POST em `/api/v1/workflows/import`. O assistente de IA do Shift (MCP server) já cobre parte desse caso de uso de forma diferente.

---

## 10. Save format YAML — flow versionável em git

**Por que importa:** Recomendação `benchmarking_flowfile_shift.md` (export YAML). Hoje o Shift serializa workflow como JSON no banco. YAML em arquivo permite code review em PR.

**Exemplo real:** `data/templates/flows/order_enrichment.yaml`

```yaml
flowfile_version: 0.8.2
flowfile_id: 4
flowfile_name: Order Enrichment
flowfile_settings:
  execution_mode: Development
  execution_location: local
  max_parallel_workers: 4
  parameters: []
nodes:
- id: 1
  type: read
  is_start_node: true
  x_position: 0
  y_position: 100
  outputs: [3]
  setting_input:
    cache_results: false
    received_file:
      path: __TEMPLATE_DATA_DIR__/orders.csv
      file_type: csv
- id: 3
  type: join
  input_ids: [1]
  right_input_id: 2
  outputs: [4]
  setting_input:
    join_input:
      join_mapping:
      - left_col: product_id
        right_col: product_id
      how: left
- id: 4
  type: formula
  input_ids: [3]
  outputs: [5]
  setting_input:
    function:
      field: { name: total_price, data_type: Auto }
      function: '[quantity] * [unit_price]'
- id: 5
  type: select
  input_ids: [4]
  outputs: [6]
  setting_input:
    select_input:
    - old_name: order_id
    - old_name: customer_id
    - old_name: total_price
```

**Pontos de design notáveis:**
1. `flowfile_version` no topo permite migrações entre versões.
2. `__TEMPLATE_DATA_DIR__` é um placeholder template (não confundir com `${var}` runtime).
3. `outputs: [3]` em cada nó duplica a edge — mas torna o YAML legível sem precisar processar separadamente.
4. `setting_input` é um envelope unificado que vira o dict do nó.

**Como adaptar no Shift:** adicionar export/import YAML em [shift-backend/app/api/v1/workflow_versions.py](../shift-backend/app/api/v1/workflow_versions.py). Esforço **baixo** — o JSON já existe, basta `yaml.dump` com config `sort_keys=False`. O ganho é principalmente cultural (reviews em PR).

---

## 11. Modo Development vs Performance — preview vs full run

**Por que importa:** Recomendação chave de `benchmarking_flowfile_performance_shift.md §6`. O insight: **executar pipeline ≠ gerar preview ≠ materializar cache** — três caminhos com custos diferentes.

No Flowfile, `performance_mode=True` pula geração de exemplo de dados. Combinado com `LOCAL_WITH_SAMPLING`, a estratégia decide qual desses três você está fazendo.

A integração disso aparece no executor (já mostrado no §1): `performance_mode` é um dos 4 inputs de `_decide_execution`. E na strategy: `narrow + remote = LOCAL_WITH_SAMPLING` (computa local, joga sample para worker; UI nunca trafega o frame inteiro).

**Como adaptar no Shift:** o backend já tem `run_mode = preview | full | validate`. O gap é no protocolo SSE — hoje o evento `node_complete` traz output completo, o que infla o stream. Separar:
- evento `node_complete` apenas com `row_count`, `schema_fingerprint`, `output_reference`
- endpoint dedicado `GET /executions/{id}/nodes/{nid}/preview?limit=100` que o frontend chama **só quando o usuário clica no nó**

Isso elimina o pior gargalo de UX que `benchmarking_flowfile_performance_shift.md §4` descreve.

---

## Padrões transversais — o que aparece em mais de um mecanismo

Olhando os 11 itens acima, três padrões se repetem:

### A. **Single source of truth + dispatch + razão registrada**

Aparece em (1) `_decide_execution`, (3) `code_generator.convert`, (10) `_process_table_trigger_schedules`. Sempre a mesma forma:

- método único, retorna `Decision/Result(action, reason, metadata)`
- razão é enum, não string livre
- erro acumulado e reportado ao final, não na primeira falha

Isso troca código difuso por código testável por matriz.

### B. **Estado mutável separado da definição**

Aparece em (6) `NodeExecutionState`, e implicitamente em (4) com o `_Restorations`. Definição é imutável durante a run; mutação fica em estrutura paralela que pode ser persistida ou descartada.

### C. **Lazy via promise cacheada**

Aparece em (5) `SingleExecutionFuture` para schema callback. Mesmo padrão pode ser usado para preview (calcula uma vez, serve N consultas), validation (valida uma vez por edição), e estimativa de cardinalidade.

---

## Onde isso encaixa no roadmap dos benchmarks anteriores

| Mecanismo deste doc | Recomendação correspondente | Doc original |
|---|---|---|
| §1 Strategy resolver | Policy engine por nó | benchmarking_flowfile_shift.md §4.2 |
| §2 Worker offload | Worker subprocessado | benchmarking_flowfile_shift.md §4.3 |
| §3 Code generation | Export para código | benchmarking_flowfile_shift.md §8 |
| §4 Parameter resolver | Parametrização fail-fast | benchmarking_flowfile_shift.md §9 |
| §5 Schema callback | Validação de schema entre nós | (gap dos docs) |
| §6 NodeExecutionState | Estado de execução separado | benchmarking_flowfile_shift.md §5.1 |
| §7 Custom Node Designer | (longo prazo, P3) | benchmarking_flowfile_shift.md §11 |
| §8 Table trigger dual path | Triggers orientados a dataset | benchmarking_flowfile_shift.md §6.2 |
| §9 flowfile_frame DSL | (não recomendado curto prazo) | benchmarking_flowfile_shift.md §14 |
| §10 YAML save format | Export YAML do workflow | (gap dos docs) |
| §11 Performance mode | Preview vs full rigoroso | benchmarking_flowfile_performance_shift.md §6 |

Quem vai implementar deve ler **primeiro** o doc estratégico correspondente para entender por quê e em que ordem; **depois** voltar aqui para ver como o Flowfile resolveu na prática.
