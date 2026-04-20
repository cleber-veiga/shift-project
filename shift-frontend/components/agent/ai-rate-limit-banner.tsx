"use client"

import { AlertTriangle } from "lucide-react"
import { useEffect, useState } from "react"

interface AIRateLimitBannerProps {
  /** Mensagem retornada pelo backend (detail do 429). */
  message: string
  /** Segundos a aguardar antes de poder tentar novamente. */
  retryAfterSeconds: number
  onDismiss?: () => void
}

function formatRemaining(seconds: number): string {
  if (seconds <= 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  if (minutes < 60) return rest === 0 ? `${minutes}m` : `${minutes}m${rest}s`
  const hours = Math.floor(minutes / 60)
  const restMin = minutes % 60
  return restMin === 0 ? `${hours}h` : `${hours}h${restMin}m`
}

export function AIRateLimitBanner({
  message,
  retryAfterSeconds,
  onDismiss,
}: AIRateLimitBannerProps) {
  const [remaining, setRemaining] = useState(Math.max(1, Math.floor(retryAfterSeconds)))

  useEffect(() => {
    setRemaining(Math.max(1, Math.floor(retryAfterSeconds)))
  }, [retryAfterSeconds])

  useEffect(() => {
    if (remaining <= 0) return
    const id = window.setInterval(() => {
      setRemaining((current) => {
        const next = current - 1
        if (next <= 0) {
          window.clearInterval(id)
          return 0
        }
        return next
      })
    }, 1000)
    return () => window.clearInterval(id)
  }, [remaining])

  return (
    <div className="mx-3 mb-2 flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-2.5 text-[12px] text-amber-700 dark:text-amber-300">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <div className="flex-1 space-y-1">
        <p className="font-medium leading-tight">{message}</p>
        <p className="text-[11px] opacity-80">
          {remaining > 0
            ? `Tente novamente em ${formatRemaining(remaining)}.`
            : "Voce ja pode tentar novamente."}
        </p>
      </div>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          className="rounded px-2 py-0.5 text-[11px] font-medium text-amber-700 transition hover:bg-amber-500/20 dark:text-amber-300"
        >
          Fechar
        </button>
      ) : null}
    </div>
  )
}
