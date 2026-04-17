"use client"

import { useCallback, useRef, useState } from "react"
import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  useReactFlow,
  type EdgeProps,
} from "@xyflow/react"
import { X } from "lucide-react"

/**
 * Edge customizado com botão de deletar ao passar o mouse.
 * Registrado como "default" para sobrescrever o edge padrão do React Flow.
 */
export function WorkflowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourceHandleId,
  sourcePosition,
  targetPosition,
  selected,
  markerEnd,
  style,
}: EdgeProps) {
  const { setEdges } = useReactFlow()
  const [hovered, setHovered] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  })

  // Pequeno delay evita que o hover seja perdido ao mover para o botão X
  const onEnter = () => {
    clearTimeout(timerRef.current)
    setHovered(true)
  }
  const onLeave = () => {
    timerRef.current = setTimeout(() => setHovered(false), 80)
  }

  const onDelete = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation()
      setEdges((eds) => eds.filter((edge) => edge.id !== id))
    },
    [id, setEdges],
  )

  const isActive = hovered || selected
  const isErrorEdge = sourceHandleId === "on_error"
  const baseStroke = isErrorEdge ? "#ef4444" : style?.stroke
  const activeStroke = isErrorEdge ? "#dc2626" : "hsl(var(--primary))"

  return (
    <>
      <BaseEdge
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          ...style,
          stroke: isActive ? activeStroke : baseStroke,
          strokeWidth: isActive ? 2.5 : ((style?.strokeWidth as number) ?? 2),
          strokeDasharray: isErrorEdge ? "6 4" : style?.strokeDasharray,
          transition: "stroke 0.15s, stroke-width 0.15s",
        }}
        interactionWidth={20}
        onMouseEnter={onEnter}
        onMouseLeave={onLeave}
      />

      <EdgeLabelRenderer>
        {isActive && (
          <div
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: "all",
            }}
            className="absolute nodrag nopan"
            onMouseEnter={onEnter}
            onMouseLeave={onLeave}
          >
            <button
              type="button"
              onClick={onDelete}
              className="flex size-5 items-center justify-center rounded-full border border-border bg-background text-muted-foreground shadow-md transition-all hover:border-red-400 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/40"
              title="Remover conexão"
              aria-label="Remover conexão"
            >
              <X className="size-2.5" />
            </button>
          </div>
        )}
      </EdgeLabelRenderer>
    </>
  )
}
