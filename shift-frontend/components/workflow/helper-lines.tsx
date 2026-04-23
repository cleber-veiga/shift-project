"use client"

import { useViewport } from "@xyflow/react"
import type { GuideLine } from "@/lib/workflow/helper-lines"

interface HelperLinesProps {
  horizontal?: GuideLine
  vertical?: GuideLine
}

const STROKE = "#ec4899"
const OPACITY = 0.65
const STROKE_WIDTH = 1
const TICK = 4

/**
 * Figma-style alignment guides: thin dashed line bounded between the two
 * aligned nodes, with small tick caps at each end. Rendered as an SVG overlay
 * and transformed via the current viewport (pan + zoom).
 */
export function HelperLines({ horizontal, vertical }: HelperLinesProps) {
  const { x: vx, y: vy, zoom } = useViewport()

  if (!horizontal && !vertical) return null

  return (
    <svg
      className="pointer-events-none absolute inset-0 z-[5] h-full w-full"
      style={{ overflow: "visible" }}
    >
      {vertical && (() => {
        const x = vertical.pos * zoom + vx
        const y1 = vertical.start * zoom + vy
        const y2 = vertical.end * zoom + vy
        return (
          <g stroke={STROKE} strokeWidth={STROKE_WIDTH} opacity={OPACITY}>
            <line x1={x} y1={y1} x2={x} y2={y2} strokeDasharray="3 3" />
            <line x1={x - TICK} y1={y1} x2={x + TICK} y2={y1} />
            <line x1={x - TICK} y1={y2} x2={x + TICK} y2={y2} />
          </g>
        )
      })()}
      {horizontal && (() => {
        const y = horizontal.pos * zoom + vy
        const x1 = horizontal.start * zoom + vx
        const x2 = horizontal.end * zoom + vx
        return (
          <g stroke={STROKE} strokeWidth={STROKE_WIDTH} opacity={OPACITY}>
            <line x1={x1} y1={y} x2={x2} y2={y} strokeDasharray="3 3" />
            <line x1={x1} y1={y - TICK} x2={x1} y2={y + TICK} />
            <line x1={x2} y1={y - TICK} x2={x2} y2={y + TICK} />
          </g>
        )
      })()}
    </svg>
  )
}
