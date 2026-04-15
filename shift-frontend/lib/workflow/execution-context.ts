import { createContext, useContext } from "react"

export type NodeExecStatus = "running" | "success" | "error" | "skipped"

export type NodeExecState = {
  status: NodeExecStatus
  duration_ms?: number
  output?: Record<string, unknown>
  error?: string
  is_pinned?: boolean
}

export const NodeExecutionContext = createContext<Record<string, NodeExecState>>({})

export function useNodeExecution(nodeId: string): NodeExecState | undefined {
  const ctx = useContext(NodeExecutionContext)
  return ctx[nodeId]
}
