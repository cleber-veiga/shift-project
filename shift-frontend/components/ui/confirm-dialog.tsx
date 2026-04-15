"use client"

import { useEffect } from "react"
import { X } from "lucide-react"
import { cn } from "@/lib/utils"
import { MorphLoader } from "@/components/ui/morph-loader"

type ConfirmVariant = "default" | "destructive"

interface ConfirmDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  confirmText?: string
  cancelText?: string
  confirmVariant?: ConfirmVariant
  loading?: boolean
  onConfirm: () => void | Promise<void>
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmText = "Confirmar",
  cancelText = "Cancelar",
  confirmVariant = "default",
  loading = false,
  onConfirm,
}: ConfirmDialogProps) {
  useEffect(() => {
    if (!open) return
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !loading) {
        onOpenChange(false)
      }
    }
    document.addEventListener("keydown", onEscape)
    return () => document.removeEventListener("keydown", onEscape)
  }, [loading, onOpenChange, open])

  useEffect(() => {
    if (!open) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [open])

  if (!open) return null

  const confirmClass =
    confirmVariant === "destructive"
      ? "bg-destructive text-white hover:bg-destructive/90"
      : "bg-primary text-primary-foreground hover:opacity-90"

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-[2px]"
      role="presentation"
      onClick={() => !loading && onOpenChange(false)}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-[min(520px,96vw)] rounded-2xl border border-border bg-card shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <p className="text-base font-semibold text-foreground">{title}</p>
            {description ? <p className="text-xs text-muted-foreground">{description}</p> : null}
          </div>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={loading}
            className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-60"
            aria-label="Fechar"
          >
            <X className="size-4" />
          </button>
        </div>

        <div className="px-5 py-4">
          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              disabled={loading}
              className="inline-flex h-8 items-center justify-center rounded-xl border border-border bg-card px-4 text-xs font-medium text-foreground transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
            >
              {cancelText}
            </button>
            <button
              type="button"
              onClick={() => !loading && void onConfirm()}
              disabled={loading}
              className={cn(
                "inline-flex h-8 items-center justify-center gap-2 rounded-xl px-4 text-xs font-bold transition disabled:cursor-not-allowed disabled:opacity-60",
                confirmClass
              )}
            >
              {loading ? <MorphLoader className="size-3" /> : null}
              {confirmText}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

