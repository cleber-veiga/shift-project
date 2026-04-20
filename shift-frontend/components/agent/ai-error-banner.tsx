"use client"

import { AlertCircle, X } from "lucide-react"

interface AIErrorBannerProps {
  message: string
  onDismiss: () => void
}

export function AIErrorBanner({ message, onDismiss }: AIErrorBannerProps) {
  return (
    <div className="mx-3 mb-2 flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-xs text-destructive">
      <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
      <span className="flex-1 leading-relaxed">{message}</span>
      <button
        type="button"
        onClick={onDismiss}
        className="ml-1 shrink-0 hover:opacity-70"
        aria-label="Dispensar erro"
      >
        <X className="size-3.5" />
      </button>
    </div>
  )
}
