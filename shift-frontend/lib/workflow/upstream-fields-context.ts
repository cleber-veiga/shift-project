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

/**
 * Summary of each upstream node available for the current config panel —
 * usado por pickers (ex.: loop "Origem dos itens") para listar fontes
 * de dataset sem o usuario precisar digitar dotted paths.
 */
export interface UpstreamSummary {
  nodeId: string
  label: string
  nodeType: string
  output: Record<string, unknown> | null
  depth: number
}

export const UpstreamOutputsContext = createContext<UpstreamSummary[]>([])

export function useUpstreamOutputs(): UpstreamSummary[] {
  return useContext(UpstreamOutputsContext)
}
