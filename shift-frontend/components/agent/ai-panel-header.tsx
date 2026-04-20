"use client"

import { History, Maximize2, Plus, Sparkles, X } from "lucide-react"
import { useRouter } from "next/navigation"
import { useAIPanelContext } from "@/lib/context/ai-panel-context"
import { Tooltip } from "@/components/ui/tooltip"

export function AIPanelHeader() {
  const { activeThreadId, close, startNewThread, toggleHistory } = useAIPanelContext()
  const router = useRouter()

  const handleExpand = () => {
    const url = activeThreadId ? `/ai?threadId=${activeThreadId}` : "/ai"
    router.push(url)
  }

  return (
    <div className="flex h-12 shrink-0 items-center justify-between border-b border-border px-3">
      <div className="flex items-center gap-2">
        <Sparkles className="size-4 text-primary" />
        <span className="text-sm font-semibold text-foreground">Shift AI</span>
      </div>

      <div className="flex items-center gap-0.5">
        <Tooltip text="Nova conversa">
          <button
            type="button"
            onClick={startNewThread}
            className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
            aria-label="Nova conversa"
          >
            <Plus className="size-4" />
          </button>
        </Tooltip>

        <Tooltip text="Expandir">
          <button
            type="button"
            onClick={handleExpand}
            className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
            aria-label="Expandir para tela cheia"
          >
            <Maximize2 className="size-4" />
          </button>
        </Tooltip>

        <Tooltip text="Historico">
          <button
            type="button"
            onClick={toggleHistory}
            className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
            aria-label="Ver historico de conversas"
          >
            <History className="size-4" />
          </button>
        </Tooltip>

        <Tooltip text="Fechar">
          <button
            type="button"
            onClick={close}
            className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
            aria-label="Fechar assistente"
          >
            <X className="size-4" />
          </button>
        </Tooltip>
      </div>
    </div>
  )
}
