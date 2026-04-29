/**
 * Type definitions for the visual workflow editor.
 * Mirrors backend node types from app/schemas/workflow.py.
 */

// ---------------------------------------------------------------------------
// Workflow Variables (globais declaradas no definition["variables"])
// ---------------------------------------------------------------------------

export type WorkflowVariableType =
  | "string"
  | "integer"
  | "number"
  | "boolean"
  | "object"
  | "array"
  | "connection"
  | "file_upload"
  | "secret"

export interface WorkflowVariable {
  name: string
  type: WorkflowVariableType
  required: boolean
  default?: unknown
  description?: string
  connection_type?: "postgres" | "mysql" | "sqlserver" | "oracle" | "mongodb"
  accepted_extensions?: string[]
  ui_group?: string
  ui_order: number
}

// ---------------------------------------------------------------------------
// Node types
// ---------------------------------------------------------------------------

export type NodeCategory = "trigger" | "input" | "transform" | "output" | "decision" | "ai"

export interface NodeDefinition {
  type: string
  label: string
  description: string
  category: NodeCategory
  icon: string // lucide icon name
  color: string // tailwind color token
  defaultData: Record<string, unknown>
  errorHandle?: boolean
}

/**
 * Registry of all available node types, grouped by category.
 */
export const NODE_CATEGORIES: { key: NodeCategory; label: string; color: string }[] = [
  { key: "trigger", label: "Gatilhos", color: "text-amber-500" },
  { key: "input", label: "Entrada", color: "text-blue-500" },
  { key: "transform", label: "Transformação", color: "text-violet-500" },
  { key: "output", label: "Saída", color: "text-emerald-500" },
  { key: "decision", label: "Decisão", color: "text-orange-500" },
  { key: "ai", label: "IA", color: "text-pink-500" },
]

export const NODE_REGISTRY: NodeDefinition[] = [
  // --- Triggers ---
  {
    type: "manual",
    label: "Manual",
    description: "Execução disparada manualmente",
    category: "trigger",
    icon: "MousePointerClick",
    color: "amber",
    defaultData: { type: "manual" },
  },
  {
    type: "cron",
    label: "Agendamento",
    description: "Execução periódica via cron",
    category: "trigger",
    icon: "Clock",
    color: "amber",
    defaultData: {
      type: "cron",
      cron_expression: "*/5 * * * *",
      timezone: "America/Sao_Paulo",
      schedule_kind: "every_5_min",
      specific_hour: 9,
      specific_minute: 0,
      all_weekdays: true,
      weekdays: ["MON", "TUE", "WED", "THU", "FRI"],
      all_months: true,
      months: [],
      all_month_days: true,
      month_days: [],
    },
  },
  {
    type: "webhook",
    label: "Webhook",
    description: "Disparo por chamada HTTP externa",
    category: "trigger",
    icon: "Webhook",
    color: "amber",
    defaultData: { type: "webhook" },
  },
  // --- Input ---
  {
    type: "sql_database",
    label: "SQL Database",
    description: "Extrair dados via query SQL",
    category: "input",
    icon: "Database",
    color: "blue",
    errorHandle: true,
    defaultData: { type: "sql_database", connection_id: "", query: "", chunk_size: 1000 },
  },
  {
    type: "csv_input",
    label: "CSV",
    description: "Ler arquivo CSV local ou remoto",
    category: "input",
    icon: "FileSpreadsheet",
    color: "blue",
    errorHandle: true,
    defaultData: { type: "csv_input", url: "", delimiter: ",", has_header: true, encoding: "utf-8" },
  },
  {
    type: "excel_input",
    label: "Excel",
    description: "Ler planilha Excel (.xlsx)",
    category: "input",
    icon: "Sheet",
    color: "blue",
    errorHandle: true,
    defaultData: { type: "excel_input", url: "", sheet_name: null, header_row: 0 },
  },
  {
    type: "api_input",
    label: "API REST",
    description: "Extrair dados de API paginada",
    category: "input",
    icon: "Globe",
    color: "blue",
    errorHandle: true,
    defaultData: { type: "api_input", url: "", method: "GET", data_path: "$", pagination_type: "none" },
  },
  {
    type: "http_request",
    label: "HTTP Request",
    description: "Requisição HTTP genérica",
    category: "input",
    icon: "Send",
    color: "blue",
    errorHandle: true,
    defaultData: { type: "http_request", method: "GET", url: "", timeout_seconds: 30 },
  },
  {
    type: "inline_data",
    label: "Dados Inline",
    description: "Dados estáticos embutidos no fluxo",
    category: "input",
    icon: "Braces",
    color: "blue",
    defaultData: { type: "inline_data", data: [] },
  },

  // --- Transform ---
  {
    type: "mapper",
    label: "Mapper",
    description: "Mapear e renomear campos",
    category: "transform",
    icon: "ArrowRightLeft",
    color: "violet",
    defaultData: { type: "mapper", mappings: [], drop_unmapped: true },
  },
  {
    type: "filter",
    label: "Filtro",
    description: "Filtrar registros por condições",
    category: "transform",
    icon: "Filter",
    color: "violet",
    defaultData: { type: "filter", conditions: [], logic: "and" },
  },
  {
    type: "aggregator",
    label: "Agregador",
    description: "Agrupar e agregar dados",
    category: "transform",
    icon: "BarChart3",
    color: "violet",
    defaultData: { type: "aggregator", group_by: [], aggregations: [] },
  },
  {
    type: "deduplication",
    label: "Remover Duplicatas",
    description: "Mantém uma linha por combinação de colunas-chave",
    category: "transform",
    icon: "Copy",
    color: "violet",
    defaultData: {
      type: "deduplication",
      partition_by: [],
      order_by: "",
      keep: "first",
    },
  },
  {
    type: "math",
    label: "Matemática",
    description: "Expressões matemáticas em colunas",
    category: "transform",
    icon: "Calculator",
    color: "violet",
    defaultData: { type: "math", expressions: [] },
  },
  {
    type: "code",
    label: "Código",
    description: "Script Python customizado",
    category: "transform",
    icon: "Code",
    color: "violet",
    errorHandle: true,
    defaultData: { type: "code", code: "", result_variable: "result" },
  },
  {
    type: "sql_script",
    label: "SQL Script",
    description: "Executar SQL arbitrário parametrizado",
    category: "transform",
    icon: "Terminal",
    color: "slate",
    errorHandle: true,
    defaultData: {
      type: "sql_script",
      connection_id: "",
      script: "",
      parameters: {},
      mode: "query",
      output_schema: [],
      output_field: "sql_result",
      timeout_seconds: 60,
    },
  },
  {
    type: "loop",
    label: "For Each",
    description: "Iterar sobre dataset invocando um workflow por item",
    category: "transform",
    icon: "Repeat",
    color: "violet",
    errorHandle: true,
    defaultData: {
      type: "loop",
      source_field: "",
      workflow_id: "",
      workflow_version: "latest",
      item_param_name: "item",
      index_param_name: "",
      extra_inputs: {},
      mode: "sequential",
      max_parallelism: 4,
      on_item_error: "fail_fast",
      max_iterations: 10000,
      output_field: "loop_result",
    },
  },

  {
    type: "sort",
    label: "Ordenar",
    description: "Ordenar registros por uma ou mais colunas",
    category: "transform",
    icon: "ArrowDownUp",
    color: "violet",
    defaultData: { type: "sort", sort_columns: [], limit: null },
  },
  {
    type: "sample",
    label: "Amostragem",
    description: "Selecionar uma amostra do dataset",
    category: "transform",
    icon: "Slice",
    color: "violet",
    defaultData: { type: "sample", mode: "first_n", n: null, seed: 42, percent: null },
  },
  {
    type: "record_id",
    label: "ID Sequencial",
    description: "Adicionar coluna de ID incremental por ROW_NUMBER()",
    category: "transform",
    icon: "Hash",
    color: "violet",
    defaultData: {
      type: "record_id",
      id_column: "id",
      start_at: 1,
      partition_by: [],
      order_by: [],
    },
  },
  {
    type: "union",
    label: "União",
    description: "Combinar dois ou mais datasets (UNION ALL)",
    category: "transform",
    icon: "Combine",
    color: "violet",
    defaultData: {
      type: "union",
      mode: "by_name",
      add_source_col: false,
      source_col_name: "_source",
    },
  },
  {
    type: "pivot",
    label: "Pivot",
    description: "Girar linhas em colunas (wide format) com agregação",
    category: "transform",
    icon: "LayoutGrid",
    color: "violet",
    defaultData: {
      type: "pivot",
      index_columns: [],
      pivot_column: "",
      value_column: "",
      aggregations: ["sum"],
      max_pivot_values: 200,
    },
  },
  {
    type: "unpivot",
    label: "Unpivot",
    description: "Converter colunas em linhas (long format)",
    category: "transform",
    icon: "LayoutList",
    color: "violet",
    defaultData: {
      type: "unpivot",
      index_columns: [],
      value_columns: [],
      by_type: null,
      variable_column_name: "variable",
      value_column_name: "value",
      cast_value_to: null,
    },
  },
  {
    type: "text_to_rows",
    label: "Texto → Linhas",
    description: "Explodir coluna de texto delimitado em múltiplas linhas",
    category: "transform",
    icon: "SplitSquareVertical",
    color: "violet",
    defaultData: {
      type: "text_to_rows",
      column_to_split: "",
      delimiter: ",",
      output_column: null,
      keep_empty: false,
      trim_values: true,
      max_output_rows: null,
    },
  },

  // --- Control Flow ---
  {
    type: "sync",
    label: "Aguardar Todos",
    description: "Aguarda a conclusão de todos os ramos paralelos",
    category: "transform",
    icon: "GitMerge",
    color: "violet",
    defaultData: { type: "sync", output_field: "data" },
  },

  // --- Decision ---
  {
    type: "if_node",
    label: "IF",
    description: "Dividir fluxo por condição (verdadeiro/falso)",
    category: "decision",
    icon: "GitBranch",
    color: "orange",
    defaultData: { type: "if_node", conditions: [], logic: "and" },
  },
  {
    type: "switch_node",
    label: "Switch",
    description: "Dividir fluxo por valor de campo (múltiplas saídas)",
    category: "decision",
    icon: "Signpost",
    color: "orange",
    defaultData: { type: "switch_node", switch_field: "", cases: [] },
  },

  // --- Output ---
  {
    type: "composite_insert",
    label: "Nó Composto",
    description: "Inserção multi-tabela reutilizável (ex.: Nota + NotaItem)",
    category: "output",
    icon: "Boxes",
    color: "emerald",
    errorHandle: true,
    defaultData: {
      type: "composite_insert",
      definition_id: null,
      definition_version: null,
      blueprint: null,
      form_schema: null,
      field_mapping: {},
    },
  },
  {
    type: "truncate_table",
    label: "Limpar Tabela",
    description: "Limpar dados da tabela de destino",
    category: "output",
    icon: "Eraser",
    color: "emerald",
    errorHandle: true,
    defaultData: { type: "truncate_table", connection_id: "", target_table: "", mode: "truncate" },
  },
  {
    type: "bulk_insert",
    label: "Inserção em Massa",
    description: "Inserir dados em tabela de destino",
    category: "output",
    icon: "Upload",
    color: "emerald",
    errorHandle: true,
    defaultData: { type: "bulk_insert", connection_id: "", target_table: "", column_mapping: [], batch_size: 1000 },
  },
  {
    type: "loadNode",
    label: "Destino SQL",
    description: "Gravar dados em banco de destino",
    category: "output",
    icon: "DatabaseZap",
    color: "emerald",
    errorHandle: true,
    defaultData: { type: "loadNode", connection_id: "", target_table: "", write_disposition: "append" },
  },
  {
    type: "dead_letter",
    label: "Dead Letter",
    description: "Persiste linhas problemáticas para retry manual",
    category: "output",
    icon: "AlertTriangle",
    color: "red",
    defaultData: { type: "dead_letter" },
  },

  // --- Sub-workflow (entrada/saida/invocacao) ---
  {
    type: "workflow_input",
    label: "Entrada do Fluxo",
    description: "Ponto de entrada quando este fluxo é invocado como sub-fluxo",
    category: "trigger",
    icon: "LogIn",
    color: "amber",
    defaultData: { type: "workflow_input", output_field: "data" },
  },
  {
    type: "workflow_output",
    label: "Saída do Workflow",
    description: "Define os valores retornados ao workflow pai",
    category: "output",
    icon: "LogOut",
    color: "emerald",
    defaultData: { type: "workflow_output", mapping: {} },
  },
  {
    type: "call_workflow",
    label: "Chamar Workflow",
    description: "Invoca outro workflow publicado como sub-workflow",
    category: "transform",
    icon: "Workflow",
    color: "indigo",
    errorHandle: true,
    defaultData: {
      type: "call_workflow",
      workflow_id: "",
      version: "latest",
      input_mapping: {},
      output_field: "workflow_result",
      timeout_seconds: 300,
    },
  },

  // --- AI ---
  {
    type: "aiNode",
    label: "LLM / IA",
    description: "Processar dados com modelo de linguagem",
    category: "ai",
    icon: "Sparkles",
    color: "pink",
    errorHandle: true,
    defaultData: { type: "aiNode", prompt_template: "", model_name: "gpt-4", temperature: 0.7 },
  },
]

/** Lookup a node definition by type */
export function getNodeDefinition(type: string): NodeDefinition | undefined {
  return NODE_REGISTRY.find((n) => n.type === type)
}

/** Get all node definitions for a given category */
export function getNodesByCategory(category: NodeCategory): NodeDefinition[] {
  return NODE_REGISTRY.filter((n) => n.category === category)
}
