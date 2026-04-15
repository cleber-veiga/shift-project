"use client"

import { createContext, useCallback, useContext, useMemo, useState } from "react"

export type DashboardHeaderAction = {
  key: string
  label: string
  icon: React.ElementType
  onClick: () => void
  disabled?: boolean
}

export type DashboardHeaderConfig = {
  breadcrumb?: React.ReactNode
  actions?: DashboardHeaderAction[]
}

type DashboardHeaderContextValue = {
  config: DashboardHeaderConfig
  setConfig: (next: DashboardHeaderConfig) => void
  clear: () => void
}

const DashboardHeaderContext = createContext<DashboardHeaderContextValue | null>(null)

export function DashboardHeaderProvider({ children }: { children: React.ReactNode }) {
  const [config, setConfigState] = useState<DashboardHeaderConfig>({})

  const setConfig = useCallback((next: DashboardHeaderConfig) => {
    setConfigState(next)
  }, [])

  const clear = useCallback(() => {
    setConfigState({})
  }, [])

  const value = useMemo(() => {
    return { config, setConfig, clear }
  }, [config, setConfig, clear])

  return <DashboardHeaderContext.Provider value={value}>{children}</DashboardHeaderContext.Provider>
}

export function useDashboardHeader() {
  const ctx = useContext(DashboardHeaderContext)
  if (!ctx) {
    throw new Error("useDashboardHeader must be used within DashboardHeaderProvider")
  }
  return ctx
}

