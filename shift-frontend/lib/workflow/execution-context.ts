import { createContext, useContext } from "react"

export type NodeExecStatus =
  | "running"
  | "success"
  // "partial" = nó completou sem exception, mas teve linhas rejeitadas
  // (ex.: bulk_insert com 3 linhas inseridas e 2 com erro de tipo).
  // Renderizado com cor de aviso (amber) — diferente de "success" pra
  // o usuario nao confundir falha silenciosa com sucesso pleno.
  | "partial"
  | "error"
  | "skipped"
  | "handled_error"
  // "aborted" cobre nos que estavam em "running" quando a execucao
  // encerrou sem emitir evento terminal (ex.: backend crashou, usuario
  // cancelou, ou irmao em paralelo falhou antes que a UI recebesse o
  // node_complete). Evita que a UI fique com spinner eterno.
  | "aborted"

export type NodeExecProgress = {
  current: number
  total: number
  succeeded: number
  failed: number
}

export type NodeExecState = {
  status: NodeExecStatus
  duration_ms?: number
  output?: Record<string, unknown>
  output_reference?: {
    node_id: string
    storage_type: string
    // Caminho explícito do .duckdb e tabela quando o nó reusa o arquivo
    // de outro (Mapper/Filter/Join compartilham o .duckdb upstream).
    database_path?: string
    table_name?: string
    dataset_name?: string | null
  } | null
  row_count?: number | null
  // Lista de colunas extraidas do output materializado (DuckDB DESCRIBE),
  // emitida pelo SSE node_complete. Alimenta useUpstreamFields() pra que
  // pickers/auto-map de nos downstream tenham acesso sincrono ao schema
  // sem precisar bater na API de preview.
  columns?: string[] | null
  // Quantas linhas foram rejeitadas (status="partial" ou "error") — usado
  // pra renderizar badge "N falharam" no no, evitando que falha silenciosa
  // do bulk_insert passe despercebida.
  failed_rows_count?: number | null
  execution_id?: string
  error?: string
  is_pinned?: boolean
  // Campos de pin v3: presentes quando o estado foi reidratado de um pin
  // materializado que excedeu o limite de linhas (_MAX_PIN_ROWS = 5000).
  pin_truncated?: boolean
  pin_total_rows?: number
  // Progresso intermediario para nos iterativos (ex.: For Each / loop).
  // Populado a partir de eventos node_progress enquanto status === "running".
  progress?: NodeExecProgress
}

export const NodeExecutionContext = createContext<Record<string, NodeExecState>>({})

export function useNodeExecution(nodeId: string): NodeExecState | undefined {
  const ctx = useContext(NodeExecutionContext)
  return ctx[nodeId]
}
