"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import {
  ArrowLeft,
  Check,
  Loader2,
  Pencil,
  Play,
  Save,
  Settings,
  Undo2,
  Redo2,
  ZoomIn,
  ZoomOut,
  Maximize2,
} from "lucide-react"
import { useReactFlow } from "@xyflow/react"

interface WorkflowToolbarProps {
  name: string
  description: string
  onNameChange: (name: string) => void
  onDescriptionChange: (description: string) => void
  onSave: () => void
  onExecute: () => void
  isSaving?: boolean
  isExecuting?: boolean
  canUndo?: boolean
  canRedo?: boolean
  onUndo?: () => void
  onRedo?: () => void
}

export function WorkflowToolbar({
  name,
  description,
  onNameChange,
  onDescriptionChange,
  onSave,
  onExecute,
  isSaving = false,
  isExecuting = false,
  canUndo = false,
  canRedo = false,
  onUndo,
  onRedo,
}: WorkflowToolbarProps) {
  const router = useRouter()
  const { zoomIn, zoomOut, fitView } = useReactFlow()
  const [editingName, setEditingName] = useState(false)
  const [editingDesc, setEditingDesc] = useState(false)

  return (
    <div className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-card px-3">
      {/* Left section: back + name/description */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => router.back()}
          className="flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="Voltar"
        >
          <ArrowLeft className="size-4" />
        </button>

        <div className="h-5 w-px bg-border" />

        <div className="flex flex-col justify-center gap-0">
          {editingName ? (
            <input
              autoFocus
              value={name}
              onChange={(e) => onNameChange(e.target.value)}
              onBlur={() => setEditingName(false)}
              onKeyDown={(e) => e.key === "Enter" && setEditingName(false)}
              className="h-6 rounded border border-input bg-background px-1.5 text-sm font-semibold text-foreground outline-none focus:ring-1 focus:ring-primary"
            />
          ) : (
            <button
              type="button"
              onClick={() => setEditingName(true)}
              className="group flex items-center gap-1.5 text-left"
            >
              <span className="text-sm font-semibold text-foreground">{name || "Sem título"}</span>
              <Pencil className="size-3 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
            </button>
          )}

          {editingDesc ? (
            <input
              autoFocus
              value={description}
              onChange={(e) => onDescriptionChange(e.target.value)}
              onBlur={() => setEditingDesc(false)}
              onKeyDown={(e) => e.key === "Enter" && setEditingDesc(false)}
              placeholder="Adicionar descrição..."
              className="h-5 rounded border border-input bg-background px-1.5 text-[11px] text-muted-foreground outline-none focus:ring-1 focus:ring-primary"
            />
          ) : (
            <button
              type="button"
              onClick={() => setEditingDesc(true)}
              className="text-left text-[11px] text-muted-foreground transition-colors hover:text-foreground"
            >
              {description || "Adicionar descrição..."}
            </button>
          )}
        </div>
      </div>

      {/* Center section: zoom + undo/redo */}
      <div className="flex items-center gap-0.5 rounded-md border border-border bg-background p-0.5">
        <button
          type="button"
          onClick={onUndo}
          disabled={!canUndo}
          className="flex size-7 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-30"
          aria-label="Desfazer"
        >
          <Undo2 className="size-3.5" />
        </button>
        <button
          type="button"
          onClick={onRedo}
          disabled={!canRedo}
          className="flex size-7 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-30"
          aria-label="Refazer"
        >
          <Redo2 className="size-3.5" />
        </button>

        <div className="mx-0.5 h-4 w-px bg-border" />

        <button
          type="button"
          onClick={() => zoomOut()}
          className="flex size-7 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="Diminuir zoom"
        >
          <ZoomOut className="size-3.5" />
        </button>
        <button
          type="button"
          onClick={() => zoomIn()}
          className="flex size-7 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="Aumentar zoom"
        >
          <ZoomIn className="size-3.5" />
        </button>
        <button
          type="button"
          onClick={() => fitView({ padding: 0.2 })}
          className="flex size-7 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="Ajustar ao canvas"
        >
          <Maximize2 className="size-3.5" />
        </button>
      </div>

      {/* Right section: save + execute */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onSave}
          disabled={isSaving}
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-50"
        >
          {isSaving ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
          Salvar
        </button>

        <button
          type="button"
          onClick={onExecute}
          disabled={isExecuting}
          className="inline-flex h-8 items-center gap-1.5 rounded-md bg-emerald-600 px-3 text-xs font-semibold text-white transition-colors hover:bg-emerald-700 disabled:opacity-50"
        >
          {isExecuting ? <Loader2 className="size-3.5 animate-spin" /> : <Play className="size-3.5" />}
          Executar
        </button>
      </div>
    </div>
  )
}
