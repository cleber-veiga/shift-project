"use client"

import { createContext, useCallback, useContext, useEffect, useState } from "react"

const STORAGE_KEY = "shift.ai-panel"
const SESSION_KEY = "shift.ai-panel.thread"
const MIN_WIDTH = 320
const MAX_WIDTH = 600
const DEFAULT_WIDTH = 380

interface StoredPrefs {
  isOpen: boolean
  width: number
}

interface AIPanelState {
  isOpen: boolean
  width: number
  activeThreadId: string | null
  historyOpen: boolean
  open: () => void
  close: () => void
  toggle: () => void
  setWidth: (w: number) => void
  setActiveThread: (id: string | null) => void
  startNewThread: () => void
  toggleHistory: () => void
}

const defaultState: AIPanelState = {
  isOpen: false,
  width: DEFAULT_WIDTH,
  activeThreadId: null,
  historyOpen: false,
  open: () => undefined,
  close: () => undefined,
  toggle: () => undefined,
  setWidth: () => undefined,
  setActiveThread: () => undefined,
  startNewThread: () => undefined,
  toggleHistory: () => undefined,
}

const AIPanelCtx = createContext<AIPanelState>(defaultState)

function clampWidth(w: number): number {
  if (!Number.isFinite(w) || w < MIN_WIDTH || w > MAX_WIDTH) return DEFAULT_WIDTH
  return Math.round(w)
}

export function AIPanelProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(false)
  const [width, setWidthState] = useState(DEFAULT_WIDTH)
  const [activeThreadId, setActiveThreadIdState] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [hydrated, setHydrated] = useState(false)

  // Rehidratacao client-side — evita SSR mismatch
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY)
      if (raw) {
        const prefs = JSON.parse(raw) as StoredPrefs
        setIsOpen(prefs.isOpen === true)
        setWidthState(clampWidth(prefs.width))
      }
    } catch { /* ignora storage corrompida */ }

    try {
      const tid = window.sessionStorage.getItem(SESSION_KEY)
      if (tid) setActiveThreadIdState(tid)
    } catch { /* ignora */ }

    setHydrated(true)
  }, [])

  const persistPrefs = useCallback((nextOpen: boolean, nextWidth: number) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ isOpen: nextOpen, width: nextWidth }))
    } catch { /* ignora */ }
  }, [])

  const open = useCallback(() => {
    setIsOpen(true)
    persistPrefs(true, width)
  }, [width, persistPrefs])

  const close = useCallback(() => {
    setIsOpen(false)
    setHistoryOpen(false)
    persistPrefs(false, width)
  }, [width, persistPrefs])

  const toggle = useCallback(() => {
    setIsOpen((prev) => {
      const next = !prev
      if (!next) setHistoryOpen(false)
      persistPrefs(next, width)
      return next
    })
  }, [width, persistPrefs])

  const setWidth = useCallback((w: number) => {
    const clamped = clampWidth(w)
    setWidthState(clamped)
    persistPrefs(isOpen, clamped)
  }, [isOpen, persistPrefs])

  const setActiveThread = useCallback((id: string | null) => {
    setActiveThreadIdState(id)
    try {
      if (id) window.sessionStorage.setItem(SESSION_KEY, id)
      else window.sessionStorage.removeItem(SESSION_KEY)
    } catch { /* ignora */ }
  }, [])

  const startNewThread = useCallback(() => {
    setActiveThread(null)
    setHistoryOpen(false)
  }, [setActiveThread])

  const toggleHistory = useCallback(() => {
    setHistoryOpen((prev) => !prev)
  }, [])

  // Sem render ate hidratar — evita flash de estado errado
  if (!hydrated) {
    return <AIPanelCtx.Provider value={defaultState}>{children}</AIPanelCtx.Provider>
  }

  return (
    <AIPanelCtx.Provider
      value={{
        isOpen,
        width,
        activeThreadId,
        historyOpen,
        open,
        close,
        toggle,
        setWidth,
        setActiveThread,
        startNewThread,
        toggleHistory,
      }}
    >
      {children}
    </AIPanelCtx.Provider>
  )
}

export function useAIPanelContext(): AIPanelState {
  return useContext(AIPanelCtx)
}
