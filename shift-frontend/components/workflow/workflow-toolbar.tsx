"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import {
  ArrowLeft,
  Clock,
  Download,
  FileJson,
  Loader2,
  Pencil,
  Play,
  Rocket,
  Save,
  Undo2,
  Redo2,
  Upload,
  ZoomIn,
  ZoomOut,
  Maximize2,
} from "lucide-react"
import { useReactFlow } from "@xyflow/react"
import type { WorkflowScheduleStatus } from "@/lib/auth"

interface WorkflowToolbarProps {
  name: string
  description: string
  status: "draft" | "published"
  isTemplate: boolean
  isPublished: boolean
  onNameChange: (name: string) => void
  onDescriptionChange: (description: string) => void
  onStatusChange: (status: "draft" | "published") => void
  onIsTemplateChange: (value: boolean) => void
  onIsPublishedChange: (value: boolean) => void
  onSave: () => void
  onExecute: () => void
  onExport: () => void
  onImport: () => void
  onOpenIoSchema?: () => void
  onOpenPublish?: () => void
  scheduleStatus?: WorkflowScheduleStatus | null
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
  status,
  isTemplate,
  isPublished,
  onNameChange,
  onDescriptionChange,
  onStatusChange,
  onIsTemplateChange,
  onIsPublishedChange,
  onSave,
  onExecute,
  onExport,
  onImport,
  onOpenIoSchema,
  onOpenPublish,
  scheduleStatus,
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

  const isProduction = status === "published"

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

      {/* Right section: toggles + save + execute */}
      <div className="flex items-center gap-2">
        {/* Schedule badge (cron ativo no Prefect) */}
        {scheduleStatus?.has_cron_node ? (
          <div
            className={`inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-xs font-medium ${
              scheduleStatus.is_active
                ? "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-400"
                : "border-border bg-muted/40 text-muted-foreground"
            }`}
            title={
              scheduleStatus.is_active
                ? `Agendamento ativo: ${scheduleStatus.cron_expression} (${scheduleStatus.timezone})`
                : "Cron configurado, mas inativo. Ative Produção e Publicado para agendar."
            }
          >
            <Clock className="size-3.5" />
            {scheduleStatus.is_active ? "Agendado" : "Inativo"}
          </div>
        ) : null}

        {/* Toggle: Teste / Produção */}
        <button
          type="button"
          onClick={() => onStatusChange(isProduction ? "draft" : "published")}
          className={`inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-xs font-medium transition-colors ${
            isProduction
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/20 dark:text-emerald-400"
              : "border-amber-500/30 bg-amber-500/10 text-amber-700 hover:bg-amber-500/20 dark:text-amber-400"
          }`}
        >
          <span className={`size-2 rounded-full ${isProduction ? "bg-emerald-500" : "bg-amber-500"}`} />
          {isProduction ? "Produção" : "Teste"}
        </button>

        {/* Toggle: Template */}
        <button
          type="button"
          onClick={() => onIsTemplateChange(!isTemplate)}
          className={`inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-xs font-medium transition-colors ${
            isTemplate
              ? "border-violet-500/30 bg-violet-500/10 text-violet-700 hover:bg-violet-500/20 dark:text-violet-400"
              : "border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground"
          }`}
        >
          <span className={`size-2 rounded-full ${isTemplate ? "bg-violet-500" : "bg-muted-foreground/40"}`} />
          Template
        </button>

        {/* Toggle: Publicado */}
        <button
          type="button"
          onClick={() => onIsPublishedChange(!isPublished)}
          className={`inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-xs font-medium transition-colors ${
            isPublished
              ? "border-sky-500/30 bg-sky-500/10 text-sky-700 hover:bg-sky-500/20 dark:text-sky-400"
              : "border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground"
          }`}
        >
          <span className={`size-2 rounded-full ${isPublished ? "bg-sky-500" : "bg-muted-foreground/40"}`} />
          Publicado
        </button>

        <div className="h-5 w-px bg-border" />

        {onOpenIoSchema && (
          <button
            type="button"
            onClick={onOpenIoSchema}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted"
            aria-label="Editar schema de I/O"
            title="Editar inputs/outputs expostos quando este workflow é chamado como sub-workflow"
          >
            <FileJson className="size-3.5" />
            Schema de I/O
          </button>
        )}

        {onOpenPublish && (
          <button
            type="button"
            onClick={onOpenPublish}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 text-xs font-medium text-emerald-700 transition-colors hover:bg-emerald-500/20 dark:text-emerald-400"
            aria-label="Publicar versão"
            title="Publicar uma nova versão imutável deste workflow"
          >
            <Rocket className="size-3.5" />
            Publicar Versão
          </button>
        )}

        <div className="h-5 w-px bg-border" />

        <button
          type="button"
          onClick={onImport}
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted"
          aria-label="Importar fluxo"
        >
          <Upload className="size-3.5" />
          Importar
        </button>

        <button
          type="button"
          onClick={onExport}
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted"
          aria-label="Exportar fluxo"
        >
          <Download className="size-3.5" />
          Exportar
        </button>

        <div className="h-5 w-px bg-border" />

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
