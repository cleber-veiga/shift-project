import { createContext, useContext } from "react"

export type NodeExecStatus =
  | "running"
  | "success"
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
  error?: string
  is_pinned?: boolean
  // Progresso intermediario para nos iterativos (ex.: For Each / loop).
  // Populado a partir de eventos node_progress enquanto status === "running".
  progress?: NodeExecProgress
}

export const NodeExecutionContext = createContext<Record<string, NodeExecState>>({})

export function useNodeExecution(nodeId: string): NodeExecState | undefined {
  const ctx = useContext(NodeExecutionContext)
  return ctx[nodeId]
}
