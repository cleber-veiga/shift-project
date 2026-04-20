"use client"

import { useEffect, useMemo } from "react"
import { useRouter } from "next/navigation"
import { useDashboard } from "@/lib/context/dashboard-context"
import { hasWorkspacePermission } from "@/lib/permissions"
import { ContextSectionPage } from "@/components/dashboard/context-section-page"
import { useRegisterAIContext } from "@/lib/context/ai-context"

export default function HomePage() {
  const router = useRouter()
  const { selectedWorkspace, selectedProject } = useDashboard()
  const canViewHome = hasWorkspacePermission(selectedWorkspace?.my_role, "MANAGER")

  const aiContext = useMemo(() => ({
    section: "home" as const,
    workspaceId: selectedWorkspace?.id ?? null,
    workspaceName: selectedWorkspace?.name ?? null,
    projectId: selectedProject?.id ?? null,
    projectName: selectedProject?.name ?? null,
    userRole: {
      workspace: (selectedWorkspace?.my_role ?? null) as "VIEWER" | "CONSULTANT" | "MANAGER" | null,
      project: null,
    },
    stats: {
      workflowsCount: 0,
      connectionsCount: 0,
      recentExecutions: 0,
    },
  }), [selectedWorkspace, selectedProject])

  useRegisterAIContext(aiContext)

  useEffect(() => {
    if (selectedWorkspace && !canViewHome) {
      router.replace("/espaco/grupo-economico")
    }
  }, [selectedWorkspace, canViewHome, router])

  if (!canViewHome) return null

  return <ContextSectionPage scope="space" section="visao-geral" />
}
