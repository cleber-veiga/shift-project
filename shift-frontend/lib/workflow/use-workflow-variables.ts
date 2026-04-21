"use client"

import { useState, useCallback, useEffect } from "react"
import { getWorkflowVariables, updateWorkflowVariables } from "@/lib/api/workflow-variables"
import type { WorkflowVariable } from "@/lib/workflow/types"

export function useWorkflowVariables(workflowId: string) {
  const [variables, setVariables] = useState<WorkflowVariable[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (workflowId === "new") return
    setIsLoading(true)
    setError(null)
    try {
      const vars = await getWorkflowVariables(workflowId)
      setVariables(vars)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar variáveis")
    } finally {
      setIsLoading(false)
    }
  }, [workflowId])

  useEffect(() => {
    load()
  }, [load])

  const save = useCallback(
    async (vars: WorkflowVariable[]): Promise<boolean> => {
      setIsSaving(true)
      setError(null)
      try {
        const saved = await updateWorkflowVariables(workflowId, vars)
        setVariables(saved)
        return true
      } catch (err) {
        setError(err instanceof Error ? err.message : "Erro ao salvar variáveis")
        return false
      } finally {
        setIsSaving(false)
      }
    },
    [workflowId],
  )

  return { variables, setVariables, isLoading, isSaving, error, save, reload: load }
}
