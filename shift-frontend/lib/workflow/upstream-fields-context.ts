import { createContext, useContext } from "react"

/**
 * Provides upstream column names to node config components.
 * Populated by NodeConfigModal from the first upstream output that has columns.
 */
export const UpstreamFieldsContext = createContext<string[]>([])

export function useUpstreamFields(): string[] {
  return useContext(UpstreamFieldsContext)
}

/**
 * Set of source field names already used by the current node's mappings.
 * Populated by NodeConfigModal and consumed by SchemaView to highlight used fields.
 */
export const UsedSourcesContext = createContext<Set<string>>(new Set())

export function useUsedSources(): Set<string> {
  return useContext(UsedSourcesContext)
}
