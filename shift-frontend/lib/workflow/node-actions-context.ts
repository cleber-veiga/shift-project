import { createContext, useContext } from "react"

interface NodeActionsContextValue {
  /** Trigger execution of the full workflow (starting from a specific node in the future) */
  onExecuteNode: (nodeId: string) => void
}

export const NodeActionsContext = createContext<NodeActionsContextValue>({
  onExecuteNode: () => {},
})

export function useNodeActions(): NodeActionsContextValue {
  return useContext(NodeActionsContext)
}
