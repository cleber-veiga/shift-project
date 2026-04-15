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
  sourcePosition,
  targetPosition,
  selected,
  markerEnd,
  style,
}: EdgeProps) {
  const { setEdges } = useReactFlow()
  const [hovered, setHovered] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout>>()

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

  return (
    <>
      <BaseEdge
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          ...style,
          stroke: isActive ? "hsl(var(--primary))" : style?.stroke,
          strokeWidth: isActive ? 2.5 : ((style?.strokeWidth as number) ?? 2),
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
