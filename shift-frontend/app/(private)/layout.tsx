"use client"

import { DashboardProvider } from "@/lib/context/dashboard-context"
import { DashboardHeaderProvider } from "@/lib/context/header-context"
import { AIContextProvider } from "@/lib/context/ai-context"
import { AIPanelProvider } from "@/lib/context/ai-panel-context"
import { BuildModeProvider } from "@/lib/workflow/build-mode-context"
import { Sidebar } from "@/components/dashboard/sidebar"
import { Header } from "@/components/dashboard/header"
import { AIPanel } from "@/components/agent/ai-panel"
import { useState } from "react"
import { usePathname } from "next/navigation"
import { useDashboard } from "@/lib/context/dashboard-context"
import { ShiftSplash } from "@/components/ui/shift-loader"
import { SessionGuard } from "@/components/ui/session-guard"

function PrivateLayoutContent({ children }: { children: React.ReactNode }) {
  const [sidebarVisible, setSidebarVisible] = useState(true)
  const { isLoading, error } = useDashboard()
  const pathname = usePathname()
  const isFullBleed = pathname.startsWith("/playground") || pathname.startsWith("/workflow")

  if (isLoading) {
    return <ShiftSplash label="Carregando seu workspace..." />
  }

  if (error) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background px-4 text-foreground">
        <div className="w-full max-w-md rounded-xl border border-border bg-card p-4">
          <p className="text-sm text-destructive">{error}</p>
        </div>
      </main>
    )
  }

  return (
    <AIPanelProvider>
      <DashboardHeaderProvider>
        <AIContextProvider>
          {/* BuildModeProvider vive no layout para que o AIPanel (fora do
              WorkflowEditor) possa consumir buildState e mostrar o card de
              confirmacao de build dentro do chat. Em paginas que nao sao de
              workflow, o provider fica ocioso (buildState=idle) sem side-effects. */}
          <BuildModeProvider>
            <div className={`bg-background text-foreground ${isFullBleed ? "flex h-screen flex-col overflow-hidden" : "min-h-screen"}`}>
              <div className={`flex ${isFullBleed ? "flex-1 overflow-hidden min-w-0" : "min-h-screen"}`}>
                {sidebarVisible && <Sidebar />}
                <div className={`flex flex-col ${isFullBleed ? "flex-1 overflow-hidden min-w-0" : "flex-1"}`}>
                  <Header
                    sidebarVisible={sidebarVisible}
                    setSidebarVisible={setSidebarVisible}
                  />
                  <main className={`${isFullBleed ? "flex-1 overflow-hidden min-w-0 min-h-0" : "flex-1 p-5 sm:p-7"}`}>
                    {children}
                  </main>
                </div>
                {/* Painel AI — sempre renderizado, controla visibilidade internamente */}
                <AIPanel />
              </div>
            </div>
          </BuildModeProvider>
        </AIContextProvider>
      </DashboardHeaderProvider>
    </AIPanelProvider>
  )
}

export default function PrivateLayout({ children }: { children: React.ReactNode }) {
  return (
    <DashboardProvider>
      <SessionGuard />
      <PrivateLayoutContent>{children}</PrivateLayoutContent>
    </DashboardProvider>
  )
}
