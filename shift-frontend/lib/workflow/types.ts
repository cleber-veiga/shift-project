/**
 * Type definitions for the visual workflow editor.
 * Mirrors backend node types from app/schemas/workflow.py.
 */

export type NodeCategory = "trigger" | "input" | "transform" | "output" | "decision" | "ai"

export interface NodeDefinition {
  type: string
  label: string
  description: string
  category: NodeCategory
  icon: string // lucide icon name
  color: string // tailwind color token
  defaultData: Record<string, unknown>
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
  {
    type: "polling",
    label: "Polling",
    description: "Monitoramento periódico de dados",
    category: "trigger",
    icon: "RefreshCw",
    color: "amber",
    defaultData: { type: "polling", connection_id: "", query: "" },
  },

  // --- Input ---
  {
    type: "sql_database",
    label: "SQL Database",
    description: "Extrair dados via query SQL",
    category: "input",
    icon: "Database",
    color: "blue",
    defaultData: { type: "sql_database", connection_id: "", query: "", chunk_size: 1000 },
  },
  {
    type: "csv_input",
    label: "CSV",
    description: "Ler arquivo CSV local ou remoto",
    category: "input",
    icon: "FileSpreadsheet",
    color: "blue",
    defaultData: { type: "csv_input", url: "", delimiter: ",", has_header: true, encoding: "utf-8" },
  },
  {
    type: "excel_input",
    label: "Excel",
    description: "Ler planilha Excel (.xlsx)",
    category: "input",
    icon: "Sheet",
    color: "blue",
    defaultData: { type: "excel_input", url: "", sheet_name: null, header_row: 0 },
  },
  {
    type: "api_input",
    label: "API REST",
    description: "Extrair dados de API paginada",
    category: "input",
    icon: "Globe",
    color: "blue",
    defaultData: { type: "api_input", url: "", method: "GET", data_path: "$", pagination_type: "none" },
  },
  {
    type: "http_request",
    label: "HTTP Request",
    description: "Requisição HTTP genérica",
    category: "input",
    icon: "Send",
    color: "blue",
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
    defaultData: { type: "code", code: "", result_variable: "result" },
  },
  {
    type: "sql_script",
    label: "SQL Script",
    description: "Executar SQL arbitrário parametrizado",
    category: "transform",
    icon: "Terminal",
    color: "slate",
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
    defaultData: { type: "truncate_table", connection_id: "", target_table: "", mode: "truncate" },
  },
  {
    type: "bulk_insert",
    label: "Inserção em Massa",
    description: "Inserir dados em tabela de destino",
    category: "output",
    icon: "Upload",
    color: "emerald",
    defaultData: { type: "bulk_insert", connection_id: "", target_table: "", column_mapping: [], batch_size: 1000 },
  },
  {
    type: "loadNode",
    label: "Destino SQL",
    description: "Gravar dados em banco de destino",
    category: "output",
    icon: "DatabaseZap",
    color: "emerald",
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

  // --- AI ---
  {
    type: "aiNode",
    label: "LLM / IA",
    description: "Processar dados com modelo de linguagem",
    category: "ai",
    icon: "Sparkles",
    color: "pink",
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
