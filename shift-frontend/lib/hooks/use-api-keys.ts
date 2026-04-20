"use client"

import { useCallback, useEffect, useState } from "react"
import {
  type AgentApiKey,
  type AgentApiKeyCreatePayload,
  createAgentApiKey,
  listAgentApiKeys,
  revokeAgentApiKey,
} from "@/lib/auth"
import { useDashboard } from "@/lib/context/dashboard-context"
import type { CreateApiKeyInput, ProjectApiKeyCreated } from "@/lib/types/agent-api-key"

export function useApiKeys() {
  const { selectedWorkspace, selectedProject } = useDashboard()
  const [keys, setKeys] = useState<AgentApiKey[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const workspaceId = selectedWorkspace?.id ?? null
  const projectId = selectedProject?.id ?? null

  const refetch = useCallback(async () => {
    if (!workspaceId || !projectId) return
    setIsLoading(true)
    setError(null)
    try {
      const { items } = await listAgentApiKeys(workspaceId)
      setKeys(items.filter((k) => k.project_id === projectId))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar chaves.")
    } finally {
      setIsLoading(false)
    }
  }, [workspaceId, projectId])

  useEffect(() => {
    refetch()
  }, [refetch])

  const createKey = useCallback(
    async (input: CreateApiKeyInput): Promise<ProjectApiKeyCreated> => {
      if (!workspaceId || !projectId) {
        throw new Error("Workspace ou projeto não selecionado.")
      }

      let expiresAt: string | null = null
      if (input.expiresInDays !== null) {
        const d = new Date()
        d.setDate(d.getDate() + input.expiresInDays)
        expiresAt = d.toISOString()
      }

      const payload: AgentApiKeyCreatePayload = {
        workspace_id: workspaceId,
        project_id: projectId,
        name: input.name,
        max_workspace_role: "VIEWER",
        max_project_role: "EDITOR",
        allowed_tools: input.allowedTools,
        require_human_approval: true,
        expires_at: expiresAt,
      }

      const result = await createAgentApiKey(payload)
      await refetch()
      return {
        plaintextKey: result.api_key,
        id: result.key.id,
        name: result.key.name,
        prefix: result.key.prefix,
      }
    },
    [workspaceId, projectId, refetch],
  )

  const revokeKey = useCallback(async (keyId: string): Promise<void> => {
    await revokeAgentApiKey(keyId)
    setKeys((prev) =>
      prev.map((k) =>
        k.id === keyId ? { ...k, revoked_at: new Date().toISOString() } : k,
      ),
    )
  }, [])

  return {
    keys,
    isLoading,
    error,
    createKey,
    revokeKey,
    refetch,
  }
}
