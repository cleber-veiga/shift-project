"use client"

import { createContext, useContext } from "react"
import type { WorkflowVariable } from "@/lib/workflow/types"

interface WorkflowVariablesContextValue {
  variables: WorkflowVariable[]
}

export const WorkflowVariablesContext = createContext<WorkflowVariablesContextValue>({
  variables: [],
})

export function useWorkflowVariablesContext() {
  return useContext(WorkflowVariablesContext)
}
