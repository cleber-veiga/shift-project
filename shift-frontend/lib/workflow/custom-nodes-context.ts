import { createContext, useContext } from "react"
import type { CustomNodeDefinition } from "@/lib/auth"

/**
 * Custom (composite_insert) node definitions available in the current workflow's scope.
 * Populated by WorkflowEditor via listWorkspaceCustomNodeDefinitions and consumed by
 * NodeLibrary (palette), onDrop (snapshot blueprint), NodeConfigPanel (mapping UI).
 */
export const CustomNodesContext = createContext<CustomNodeDefinition[]>([])

export function useCustomNodes(): CustomNodeDefinition[] {
  return useContext(CustomNodesContext)
}

export function findCustomNode(
  list: CustomNodeDefinition[],
  definitionId: string | null | undefined,
): CustomNodeDefinition | undefined {
  if (!definitionId) return undefined
  return list.find((d) => d.id === definitionId)
}
