import { createContext, useContext } from "react"

/**
 * Provides upstream column names to node config components.
 * Populated by NodeConfigModal from the first upstream output that has columns.
 */
export const UpstreamFieldsContext = createContext<string[]>([])

export function useUpstreamFields(): string[] {
  return useContext(UpstreamFieldsContext)
}
