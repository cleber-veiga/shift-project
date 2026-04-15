"use client"

import { createContext, useCallback, useContext, useMemo, useState } from "react"
import { ToastContainer, type ToastData, type ToastType } from "@/components/ui/toast-notification"

// ─── Context ──────────────────────────────────────────────────────────────────

interface ToastContextValue {
  addToast: (toast: Omit<ToastData, "id">) => void
  removeToast: (id: string) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

// ─── Provider ─────────────────────────────────────────────────────────────────

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastData[]>([])

  const addToast = useCallback((toast: Omit<ToastData, "id">) => {
    const id = Math.random().toString(36).slice(2, 11)
    setToasts((prev) => [...prev, { ...toast, id }])
  }, [])

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  return (
    <ToastContext.Provider value={{ addToast, removeToast }}>
      {children}
      <ToastContainer toasts={toasts} onRemove={removeToast} />
    </ToastContext.Provider>
  )
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error("useToast must be used within ToastProvider")

  const { addToast } = ctx

  return useMemo(
    () => ({
      success: (title: string, description?: string) =>
        addToast({ type: "success", title, description }),
      error: (title: string, description?: string) =>
        addToast({ type: "error", title, description }),
      warning: (title: string, description?: string) =>
        addToast({ type: "warning", title, description }),
      info: (title: string, description?: string) =>
        addToast({ type: "info", title, description }),
    }),
    [addToast],
  )
}

export type { ToastType }
