"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"
import { useDashboard } from "@/lib/context/dashboard-context"
import { hasWorkspacePermission } from "@/lib/permissions"
import { ContextSectionPage } from "@/components/dashboard/context-section-page"

export default function HomePage() {
  const router = useRouter()
  const { selectedWorkspace } = useDashboard()
  const canViewHome = hasWorkspacePermission(selectedWorkspace?.my_role, "MANAGER")

  useEffect(() => {
    if (selectedWorkspace && !canViewHome) {
      router.replace("/espaco/grupo-economico")
    }
  }, [selectedWorkspace, canViewHome, router])

  if (!canViewHome) return null

  return <ContextSectionPage scope="space" section="visao-geral" />
}
