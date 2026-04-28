"use client"

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import {
  ArrowLeft,
  ChevronDown,
  Clock,
  Download,
  FileJson,
  MoreHorizontal,
  Pencil,
  Play,
  Rocket,
  Save,
  SlidersHorizontal,
  Tag as TagIcon,
  Upload,
  Check,
  X,
} from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import { cn } from "@/lib/utils"
import type { WorkflowScheduleStatus } from "@/lib/auth"

interface WorkflowToolbarProps {
  name: string
  description: string
  tags: string[]
  status: "draft" | "published"
  isTemplate: boolean
  isPublished: boolean
  onNameChange: (name: string) => void
  onDescriptionChange: (description: string) => void
  onTagsChange: (tags: string[]) => void
  onStatusChange: (status: "draft" | "published") => void
  onIsTemplateChange: (value: boolean) => void
  onIsPublishedChange: (value: boolean) => void
  onSave: () => void
  onExecute: () => void
  onExport: () => void
  onImport: () => void
  onOpenIoSchema?: () => void
  onOpenPublish?: () => void
  onOpenVariables?: () => void
  variableCount?: number
  scheduleStatus?: WorkflowScheduleStatus | null
  isSaving?: boolean
  isExecuting?: boolean
}

export function WorkflowToolbar({
  name,
  description,
  tags,
  status,
  isTemplate,
  isPublished,
  onNameChange,
  onDescriptionChange,
  onTagsChange,
  onStatusChange,
  onIsTemplateChange,
  onIsPublishedChange,
  onSave,
  onExecute,
  onExport,
  onImport,
  onOpenIoSchema,
  onOpenPublish,
  onOpenVariables,
  variableCount = 0,
  scheduleStatus,
  isSaving = false,
  isExecuting = false,
}: WorkflowToolbarProps) {
  const router = useRouter()
  const [editingName, setEditingName] = useState(false)
  const [editingDesc, setEditingDesc] = useState(false)

  const isProduction = status === "published"
  const hasSchedule = !!scheduleStatus?.has_cron_node
  const scheduleActive = hasSchedule && !!scheduleStatus?.is_active

  return (
    <div className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-border bg-card px-3">
      {/* ── LEFT: back + title/description ─────────────────────────────────── */}
      <div className="flex min-w-0 items-center gap-2">
        <button
          type="button"
          onClick={() => router.back()}
          className="flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="Voltar"
        >
          <ArrowLeft className="size-4" />
        </button>

        <div className="h-5 w-px shrink-0 bg-border" />

        <div className="flex min-w-0 flex-col justify-center gap-0">
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
              className="group flex min-w-0 items-center gap-1.5 text-left"
            >
              <span className="truncate text-sm font-semibold text-foreground">
                {name || "Sem título"}
              </span>
              <Pencil className="size-3 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
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
              className="truncate text-left text-[11px] text-muted-foreground transition-colors hover:text-foreground"
            >
              {description || "Adicionar descrição..."}
            </button>
          )}
        </div>
      </div>

      {/* ── RIGHT: status + variables + more + save + execute ─────────────── */}
      <div className="flex shrink-0 items-center gap-2">
        <StatusChip
          isProduction={isProduction}
          isTemplate={isTemplate}
          isPublished={isPublished}
          scheduleStatus={scheduleStatus}
          hasSchedule={hasSchedule}
          scheduleActive={scheduleActive}
          onStatusChange={onStatusChange}
          onIsTemplateChange={onIsTemplateChange}
          onIsPublishedChange={onIsPublishedChange}
        />

        {onOpenVariables && (
          <button
            type="button"
            onClick={onOpenVariables}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-2.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
            title="Declarar variáveis globais preenchidas na execução"
          >
            <SlidersHorizontal className="size-3.5" />
            Variáveis
            {variableCount > 0 && (
              <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold text-primary-foreground">
                {variableCount}
              </span>
            )}
          </button>
        )}

        <TagsChip tags={tags} onTagsChange={onTagsChange} />

        <MoreMenu
          onOpenIoSchema={onOpenIoSchema}
          onOpenPublish={onOpenPublish}
          onImport={onImport}
          onExport={onExport}
        />

        <div className="h-5 w-px bg-border" />

        <button
          type="button"
          onClick={onSave}
          disabled={isSaving}
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-50"
        >
          {isSaving ? <MorphLoader className="size-3.5" /> : <Save className="size-3.5" />}
          Salvar
        </button>

        <button
          type="button"
          onClick={onExecute}
          disabled={isExecuting}
          className="inline-flex h-8 items-center gap-1.5 rounded-md bg-emerald-600 px-3.5 text-xs font-semibold text-white transition-colors hover:bg-emerald-700 disabled:opacity-50"
        >
          {isExecuting ? <MorphLoader className="size-3.5" /> : <Play className="size-3.5" />}
          Executar
        </button>
      </div>
    </div>
  )
}

// ── Subcomponents ──────────────────────────────────────────────────────────

function useClickOutside(ref: React.RefObject<HTMLElement | null>, onOutside: () => void, active: boolean) {
  useEffect(() => {
    if (!active) return
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onOutside()
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onOutside()
    }
    document.addEventListener("mousedown", handle)
    document.addEventListener("keydown", handleKey)
    return () => {
      document.removeEventListener("mousedown", handle)
      document.removeEventListener("keydown", handleKey)
    }
  }, [ref, onOutside, active])
}

function StatusChip({
  isProduction,
  isTemplate,
  isPublished,
  scheduleStatus,
  hasSchedule,
  scheduleActive,
  onStatusChange,
  onIsTemplateChange,
  onIsPublishedChange,
}: {
  isProduction: boolean
  isTemplate: boolean
  isPublished: boolean
  scheduleStatus?: WorkflowScheduleStatus | null
  hasSchedule: boolean
  scheduleActive: boolean
  onStatusChange: (status: "draft" | "published") => void
  onIsTemplateChange: (v: boolean) => void
  onIsPublishedChange: (v: boolean) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useClickOutside(ref, () => setOpen(false), open)

  const dotColor = isProduction ? "bg-emerald-500" : "bg-amber-500"
  const label = isProduction ? "Produção" : "Teste"

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "inline-flex h-8 items-center gap-2 rounded-md border px-2.5 text-xs font-medium transition-colors",
          isProduction
            ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/20 dark:text-emerald-400"
            : "border-amber-500/30 bg-amber-500/10 text-amber-700 hover:bg-amber-500/20 dark:text-amber-400",
        )}
        title="Status do workflow"
      >
        <span className={cn("size-2 rounded-full", dotColor)} />
        <span>{label}</span>
        {(isTemplate || isPublished || scheduleActive) && (
          <span className="ml-0.5 flex items-center gap-1 border-l border-current/20 pl-2">
            {isTemplate && (
              <span
                className="inline-flex size-4 items-center justify-center rounded bg-violet-500/15 font-bold text-[9px] text-violet-700 dark:text-violet-400"
                title="Template"
              >
                T
              </span>
            )}
            {isPublished && (
              <span
                className="inline-flex size-4 items-center justify-center rounded bg-sky-500/15 font-bold text-[9px] text-sky-700 dark:text-sky-400"
                title="Publicado"
              >
                P
              </span>
            )}
            {scheduleActive && (
              <Clock
                className="size-3 text-sky-600 dark:text-sky-400"
                aria-label="Agendamento ativo"
              />
            )}
          </span>
        )}
        <ChevronDown className={cn("size-3 transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute right-0 top-9 z-30 w-72 overflow-hidden rounded-lg border border-border bg-card shadow-lg">
          {/* Ambiente: Teste / Produção */}
          <div className="p-2">
            <p className="px-2 pb-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              Ambiente
            </p>
            <div className="flex gap-1 rounded-md border border-border bg-background p-0.5">
              <EnvironmentOption
                active={!isProduction}
                onClick={() => onStatusChange("draft")}
                dotClass="bg-amber-500"
                label="Teste"
                hint="Edição livre"
              />
              <EnvironmentOption
                active={isProduction}
                onClick={() => onStatusChange("published")}
                dotClass="bg-emerald-500"
                label="Produção"
                hint="Ativado para execução real"
              />
            </div>
          </div>

          <div className="border-t border-border" />

          {/* Flags */}
          <div className="p-2">
            <p className="px-2 pb-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              Atributos
            </p>
            <FlagToggle
              active={isTemplate}
              onClick={() => onIsTemplateChange(!isTemplate)}
              accentClass="bg-violet-500"
              label="Template"
              hint="Pode ser clonado por consultores"
            />
            <FlagToggle
              active={isPublished}
              onClick={() => onIsPublishedChange(!isPublished)}
              accentClass="bg-sky-500"
              label="Publicado"
              hint="Visível no catálogo público"
            />
          </div>

          {hasSchedule && (
            <>
              <div className="border-t border-border" />
              <div className="flex items-start gap-2 bg-muted/30 p-3 text-[11px]">
                <Clock
                  className={cn(
                    "mt-0.5 size-3.5 shrink-0",
                    scheduleActive ? "text-sky-600 dark:text-sky-400" : "text-muted-foreground",
                  )}
                />
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-foreground">
                    {scheduleActive ? "Agendamento ativo" : "Agendamento inativo"}
                  </p>
                  <p className="mt-0.5 font-mono text-muted-foreground">
                    {scheduleStatus?.cron_expression} · {scheduleStatus?.timezone}
                  </p>
                  {!scheduleActive && (
                    <p className="mt-1 text-muted-foreground">
                      Ative Produção + Publicado para agendar.
                    </p>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function EnvironmentOption({
  active,
  onClick,
  dotClass,
  label,
  hint,
}: {
  active: boolean
  onClick: () => void
  dotClass: string
  label: string
  hint: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex flex-1 flex-col items-start gap-0.5 rounded px-2 py-1.5 text-left transition-colors",
        active ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-muted",
      )}
    >
      <span className="flex items-center gap-1.5 text-xs font-medium">
        <span className={cn("size-1.5 rounded-full", dotClass)} />
        {label}
      </span>
      <span className="text-[10px] text-muted-foreground">{hint}</span>
    </button>
  )
}

function FlagToggle({
  active,
  onClick,
  accentClass,
  label,
  hint,
}: {
  active: boolean
  onClick: () => void
  accentClass: string
  label: string
  hint: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-muted"
    >
      <span
        className={cn(
          "flex size-4 shrink-0 items-center justify-center rounded border transition-colors",
          active
            ? `${accentClass} border-transparent text-white`
            : "border-border bg-background",
        )}
      >
        {active && <Check className="size-3" strokeWidth={3} />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-xs font-medium text-foreground">{label}</span>
        <span className="block text-[10px] text-muted-foreground">{hint}</span>
      </span>
    </button>
  )
}

function MoreMenu({
  onOpenIoSchema,
  onOpenPublish,
  onImport,
  onExport,
}: {
  onOpenIoSchema?: () => void
  onOpenPublish?: () => void
  onImport: () => void
  onExport: () => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useClickOutside(ref, () => setOpen(false), open)

  function call(fn?: () => void) {
    setOpen(false)
    fn?.()
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex size-8 items-center justify-center rounded-md border border-border bg-background text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
          open && "bg-muted text-foreground",
        )}
        aria-label="Mais ações"
        title="Mais ações"
      >
        <MoreHorizontal className="size-4" />
      </button>

      {open && (
        <div className="absolute right-0 top-9 z-30 w-60 overflow-hidden rounded-lg border border-border bg-card py-1 shadow-lg">
          {onOpenPublish && (
            <MenuItem onClick={() => call(onOpenPublish)} accent="emerald">
              <Rocket className="size-3.5" />
              <div className="flex-1">
                <p className="text-xs font-medium text-foreground">Publicar versão</p>
                <p className="text-[10px] text-muted-foreground">Criar snapshot imutável</p>
              </div>
            </MenuItem>
          )}

          {onOpenIoSchema && (
            <MenuItem onClick={() => call(onOpenIoSchema)}>
              <FileJson className="size-3.5" />
              <div className="flex-1">
                <p className="text-xs font-medium text-foreground">Schema de I/O</p>
                <p className="text-[10px] text-muted-foreground">Inputs/outputs do sub-workflow</p>
              </div>
            </MenuItem>
          )}

          {(onOpenIoSchema || onOpenPublish) && <div className="my-1 border-t border-border" />}

          <MenuItem onClick={() => call(onImport)}>
            <Upload className="size-3.5" />
            <span className="text-xs font-medium text-foreground">Importar</span>
          </MenuItem>
          <MenuItem onClick={() => call(onExport)}>
            <Download className="size-3.5" />
            <span className="text-xs font-medium text-foreground">Exportar</span>
          </MenuItem>
        </div>
      )}
    </div>
  )
}

function MenuItem({
  children,
  onClick,
  accent,
}: {
  children: React.ReactNode
  onClick: () => void
  accent?: "emerald"
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2.5 px-3 py-1.5 text-left transition-colors hover:bg-muted",
        accent === "emerald" && "text-emerald-700 dark:text-emerald-400",
      )}
    >
      {children}
    </button>
  )
}

function TagsChip({
  tags,
  onTagsChange,
}: {
  tags: string[]
  onTagsChange: (tags: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState("")
  const ref = useRef<HTMLDivElement>(null)
  useClickOutside(ref, () => setOpen(false), open)

  function addTag(raw: string) {
    const t = raw.trim().toUpperCase().replace(/\s+/g, "_").slice(0, 50)
    if (!t) return
    if (!tags.includes(t)) onTagsChange([...tags, t])
    setDraft("")
  }

  function removeTag(t: string) {
    onTagsChange(tags.filter((x) => x !== t))
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-2.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
        title="Tags do workflow (salvas com o fluxo)"
      >
        <TagIcon className="size-3.5" />
        Tags
        {tags.length > 0 && (
          <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold text-primary-foreground">
            {tags.length}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-9 z-30 w-72 overflow-hidden rounded-lg border border-border bg-card p-3 shadow-lg">
          <p className="pb-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Tags do workflow
          </p>
          <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-input bg-background px-2 py-1.5 focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20">
            {tags.map((t) => (
              <span
                key={t}
                className="inline-flex items-center gap-1 rounded bg-primary/10 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-primary"
              >
                {t}
                <button
                  type="button"
                  onClick={() => removeTag(t)}
                  className="flex size-3.5 items-center justify-center rounded-sm hover:bg-primary/20"
                  aria-label={`Remover tag ${t}`}
                >
                  <X className="size-2.5" />
                </button>
              </span>
            ))}
            <input
              type="text"
              value={draft}
              onChange={(e) => {
                const v = e.target.value
                if (v.endsWith(",") || v.endsWith(";")) {
                  addTag(v.slice(0, -1))
                } else {
                  setDraft(v.toUpperCase())
                }
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault()
                  if (draft.trim()) addTag(draft)
                } else if (e.key === "Backspace" && !draft && tags.length > 0) {
                  removeTag(tags[tags.length - 1])
                }
              }}
              onBlur={() => draft.trim() && addTag(draft)}
              placeholder={tags.length === 0 ? "Ex: FISCAL, CLIENTES" : ""}
              className="min-w-[100px] flex-1 bg-transparent py-0.5 text-xs uppercase text-foreground outline-none placeholder:text-muted-foreground/50 placeholder:normal-case"
            />
          </div>
          <p className="mt-2 text-[10px] text-muted-foreground">
            Enter ou vírgula para adicionar. Salve o fluxo para persistir.
          </p>
        </div>
      )}
    </div>
  )
}
