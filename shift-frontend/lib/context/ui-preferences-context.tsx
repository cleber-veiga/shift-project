"use client"

import { createContext, useContext } from "react"

export type UiScale = "default"

interface UiPreferencesContextType {
  uiScale: UiScale
  setUiScale: (scale: UiScale) => void
}

const DEFAULT_SCALE: UiScale = "default"
const noop = () => undefined

const UiPreferencesContext = createContext<UiPreferencesContextType>({
  uiScale: DEFAULT_SCALE,
  setUiScale: noop,
})

export function UiPreferencesProvider({ children }: { children: React.ReactNode }) {
  return (
    <UiPreferencesContext.Provider value={{ uiScale: DEFAULT_SCALE, setUiScale: noop }}>
      {children}
    </UiPreferencesContext.Provider>
  )
}

export function useUiPreferences() {
  return useContext(UiPreferencesContext)
}
