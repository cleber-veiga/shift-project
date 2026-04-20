"use client"

import { Sparkles } from "lucide-react"
import { useAIPanelContext } from "@/lib/context/ai-panel-context"
import { Tooltip } from "@/components/ui/tooltip"

export function AIPanelToggle() {
  const { toggle } = useAIPanelContext()

  return (
    <Tooltip text="Assistente Shift">
      <button
        type="button"
        onClick={toggle}
        className="relative inline-flex size-9 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
        aria-label="Abrir/fechar assistente Shift"
      >
        <Sparkles className="size-4" />
      </button>
    </Tooltip>
  )
}
