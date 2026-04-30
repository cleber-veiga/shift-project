"use client"

import { useCallback, useRef, useState } from "react"
import {
  EdgeLabelRenderer,
  getBezierPath,
  useReactFlow,
  type EdgeProps,
} from "@xyflow/react"
import { X } from "lucide-react"

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
    curvature: 0.15,
  })

  const onEnter = () => { clearTimeout(timerRef.current); setHovered(true) }
  const onLeave = () => { timerRef.current = setTimeout(() => setHovered(false), 80) }

  const onDelete = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation()
      setEdges((eds) => eds.filter((edge) => edge.id !== id))
    },
    [id, setEdges],
  )

  const isActive = hovered || selected
  const isErrorEdge = sourceHandleId === "on_error"
  const gradId = `ef-grad-${id}`

  return (
    <>
      {/* Gradient definition — recomputed when source/target positions change */}
      {!isErrorEdge && (
        <defs>
          <linearGradient
            id={gradId}
            gradientUnits="userSpaceOnUse"
            x1={sourceX}
            y1={sourceY}
            x2={targetX}
            y2={targetY}
          >
            <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="0.45" />
            <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity="0.9" />
          </linearGradient>
        </defs>
      )}

      {/* Wide invisible hit area for easy interaction */}
      <path
        d={edgePath}
        fill="none"
        strokeWidth={20}
        stroke="transparent"
        onMouseEnter={onEnter}
        onMouseLeave={onLeave}
      />

      {/* Visible path */}
      <path
        d={edgePath}
        className="workflow-edge-path"
        fill="none"
        markerEnd={markerEnd}
        strokeLinecap="round"
        strokeWidth={isActive ? 1.5 : 1}
        stroke={
          isErrorEdge
            ? (isActive ? "#dc2626" : "#ef4444")
            : isActive
            ? `url(#${gradId})`
            : "#94a3b8"
        }
        strokeDasharray="6 4"
        style={{
          transition: "stroke 0.2s ease, stroke-width 0.2s ease, stroke-opacity 0.2s ease",
          filter: isActive && !isErrorEdge
            ? "drop-shadow(0 0 3px hsl(var(--primary) / 0.35))"
            : undefined,
        }}
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
