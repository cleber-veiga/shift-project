"use client"

import { useCallback, useEffect, useRef } from "react"
import { useAIPanelContext } from "@/lib/context/ai-panel-context"

export function AIPanelResizeHandle() {
  const { width, setWidth } = useAIPanelContext()
  const dragStartX = useRef<number | null>(null)
  const dragStartWidth = useRef<number>(width)

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragStartX.current = e.clientX
    dragStartWidth.current = width
    document.body.style.cursor = "col-resize"
    document.body.style.userSelect = "none"
  }, [width])

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (dragStartX.current === null) return
      const delta = dragStartX.current - e.clientX
      setWidth(dragStartWidth.current + delta)
    }

    const onMouseUp = () => {
      if (dragStartX.current === null) return
      dragStartX.current = null
      document.body.style.cursor = ""
      document.body.style.userSelect = ""
    }

    document.addEventListener("mousemove", onMouseMove)
    document.addEventListener("mouseup", onMouseUp)
    return () => {
      document.removeEventListener("mousemove", onMouseMove)
      document.removeEventListener("mouseup", onMouseUp)
    }
  }, [setWidth])

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Redimensionar painel"
      onMouseDown={onMouseDown}
      className="absolute left-0 top-0 h-full w-1 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors"
    />
  )
}
