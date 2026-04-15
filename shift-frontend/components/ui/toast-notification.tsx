"use client"

import { useEffect, useState, useCallback } from "react"
import { CheckCircle2, XCircle, AlertTriangle, Info, X, Copy, Check } from "lucide-react"
import { cn } from "@/lib/utils"

// ─── Types ────────────────────────────────────────────────────────────────────

export type ToastType = "success" | "error" | "warning" | "info"

export interface ToastData {
  id: string
  type: ToastType
  title: string
  description?: string
  /** Duration in ms. 0 = no auto-dismiss. Defaults: success/info/warning=5000, error=0 */
  duration?: number
}

// ─── Config ───────────────────────────────────────────────────────────────────

const config = {
  success: {
    icon: CheckCircle2,
    accentClass: "border-l-emerald-500",
    iconClass: "text-emerald-400",
    bgIconClass: "bg-emerald-500/10",
    progressClass: "bg-emerald-500",
  },
  error: {
    icon: XCircle,
    accentClass: "border-l-red-500",
    iconClass: "text-red-400",
    bgIconClass: "bg-red-500/10",
    progressClass: "bg-red-500",
  },
  warning: {
    icon: AlertTriangle,
    accentClass: "border-l-amber-500",
    iconClass: "text-amber-400",
    bgIconClass: "bg-amber-500/10",
    progressClass: "bg-amber-500",
  },
  info: {
    icon: Info,
    accentClass: "border-l-blue-500",
    iconClass: "text-blue-400",
    bgIconClass: "bg-blue-500/10",
    progressClass: "bg-blue-500",
  },
}

const DEFAULT_DURATION: Record<ToastType, number> = {
  success: 5000,
  info: 5000,
  warning: 6000,
  error: 0, // no auto-dismiss
}

// ─── ToastItem ────────────────────────────────────────────────────────────────

function ToastItem({
  toast,
  onRemove,
}: {
  toast: ToastData
  onRemove: (id: string) => void
}) {
  const duration = toast.duration ?? DEFAULT_DURATION[toast.type]
  const hasTimer = duration > 0

  const [progress, setProgress] = useState(100)
  const [isLeaving, setIsLeaving] = useState(false)
  const [copied, setCopied] = useState(false)

  const dismiss = useCallback(() => {
    setIsLeaving(true)
    setTimeout(() => onRemove(toast.id), 280)
  }, [toast.id, onRemove])

  useEffect(() => {
    if (!hasTimer) return
    const startTime = Date.now()
    const interval = setInterval(() => {
      const elapsed = Date.now() - startTime
      const remaining = Math.max(0, 100 - (elapsed / duration) * 100)
      setProgress(remaining)
      if (remaining <= 0) {
        clearInterval(interval)
        dismiss()
      }
    }, 16)
    return () => clearInterval(interval)
  }, [hasTimer, duration, dismiss])

  function handleCopy() {
    const text = [toast.title, toast.description].filter(Boolean).join("\n")
    void navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const { icon: Icon, accentClass, iconClass, bgIconClass, progressClass } = config[toast.type]

  return (
    <div
      className={cn(
        "group relative w-80 overflow-hidden rounded-xl border border-l-4 shadow-lg transition-all duration-280",
        "border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900",
        accentClass,
        isLeaving
          ? "translate-x-full opacity-0"
          : "translate-x-0 opacity-100"
      )}
    >
      <div className="flex gap-3 p-4">
        {/* Icon */}
        <div className={cn("flex size-9 shrink-0 items-center justify-center rounded-lg", bgIconClass)}>
          <Icon className={cn("size-5", iconClass)} />
        </div>

        {/* Content */}
        <div className="flex-1 space-y-0.5 min-w-0">
          <p className="text-sm font-semibold leading-snug text-neutral-900 dark:text-white">{toast.title}</p>
          {toast.description && (
            <p className="text-xs leading-relaxed break-words text-neutral-500 dark:text-neutral-400">{toast.description}</p>
          )}
        </div>

        {/* Actions */}
        <div className="flex shrink-0 items-start gap-1">
          {/* Copy button — only for errors */}
          {toast.type === "error" && (
            <button
              onClick={handleCopy}
              title="Copiar mensagem"
              className="rounded-md p-1 transition-colors text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600 dark:text-neutral-500 dark:hover:bg-white/5 dark:hover:text-neutral-300"
            >
              {copied ? <Check className="size-3.5 text-emerald-500" /> : <Copy className="size-3.5" />}
            </button>
          )}
          {/* Close button */}
          <button
            onClick={dismiss}
            className="rounded-md p-1 opacity-0 transition-opacity group-hover:opacity-100 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600 dark:text-neutral-500 dark:hover:bg-white/5 dark:hover:text-neutral-300"
          >
            <X className="size-3.5" />
          </button>
        </div>
      </div>

      {/* Progress bar */}
      {hasTimer && (
        <div
          className={cn("absolute bottom-0 left-0 h-0.5 transition-all duration-100", progressClass)}
          style={{ width: `${progress}%` }}
        />
      )}
    </div>
  )
}

// ─── ToastContainer ───────────────────────────────────────────────────────────

export function ToastContainer({
  toasts,
  onRemove,
}: {
  toasts: ToastData[]
  onRemove: (id: string) => void
}) {
  if (toasts.length === 0) return null

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[200] flex flex-col gap-3">
      {toasts.map((toast) => (
        <div key={toast.id} className="pointer-events-auto">
          <ToastItem toast={toast} onRemove={onRemove} />
        </div>
      ))}
    </div>
  )
}
