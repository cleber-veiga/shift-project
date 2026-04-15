"use client"

import { useRef, useState } from "react"
import { cn } from "@/lib/utils"

interface TooltipProps {
  text: string
  children: React.ReactNode
  /** Quando true suprime o tooltip (ex: menu pai já está aberto) */
  open?: boolean
  /** Posição em relação ao elemento. Padrão: "bottom" */
  side?: "top" | "bottom"
}

interface Coords {
  x: number
  y: number
}

export function Tooltip({ text, children, open = false, side = "bottom" }: TooltipProps) {
  const triggerRef = useRef<HTMLDivElement>(null)
  const [coords, setCoords] = useState<Coords | null>(null)
  const [visible, setVisible] = useState(false)

  function show() {
    if (open || !triggerRef.current) return
    const rect = triggerRef.current.getBoundingClientRect()
    setCoords({
      x: rect.left + rect.width / 2,
      y: side === "bottom" ? rect.bottom : rect.top,
    })
    setVisible(true)
  }

  function hide() {
    setVisible(false)
  }

  return (
    <>
      <div
        ref={triggerRef}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
      >
        {children}
      </div>

      {visible && coords && (
        <div
          className="pointer-events-none fixed z-[300] -translate-x-1/2 transition-opacity duration-150"
          style={{
            left: coords.x,
            top: side === "bottom" ? coords.y + 6 : undefined,
            bottom: side === "top" ? window.innerHeight - coords.y + 6 : undefined,
          }}
        >
          {/* Seta */}
          <div
            className={cn(
              "absolute left-1/2 size-2 -translate-x-1/2 rotate-45 border-border bg-card",
              side === "bottom"
                ? "top-0 -translate-y-1/2 border-l border-t"
                : "bottom-0 translate-y-1/2 border-b border-r"
            )}
          />
          <div className="whitespace-nowrap rounded-md border border-border bg-card px-2.5 py-1 text-[11px] font-medium text-foreground shadow-lg">
            {text}
          </div>
        </div>
      )}
    </>
  )
}
