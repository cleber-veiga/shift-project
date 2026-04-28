"use client"

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { AlertCircle, ArrowRight, DatabaseZap, Settings2, X } from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import { cn } from "@/lib/utils"
import { useDashboard } from "@/lib/context/dashboard-context"
import { listWorkspacePlayers, createWorkflow, type WorkspacePlayer } from "@/lib/auth"

// ── Types ──────────────────────────────────────────────────────────────────────

type WorkflowType = "data-migration" | "system-config"

interface WorkflowTypeOption {
  type: WorkflowType
  icon: React.ReactNode
  label: string
  description: string
}

const WORKFLOW_TYPES: WorkflowTypeOption[] = [
  {
    type: "data-migration",
    icon: <DatabaseZap className="size-5" />,
    label: "Migração de Dados",
    description: "Extraia, transforme e carregue dados entre sistemas",
  },
  {
    type: "system-config",
    icon: <Settings2 className="size-5" />,
    label: "Configuração de Sistema",
    description: "Automatize processos de configuração e parametrização",
  },
]

// Simplified badge for DB type
const DB_LABELS: Record<string, string> = {
  POSTGRESQL: "PostgreSQL",
  MYSQL: "MySQL",
  SQLSERVER: "SQL Server",
  ORACLE: "Oracle",
  FIREBIRD: "Firebird",
  SQLITE: "SQLite",
  SNOWFLAKE: "Snowflake",
}

// ── Component ─────────────────────────────────────────────────────────────────

interface NewWorkflowModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function NewWorkflowModal({ open, onOpenChange }: NewWorkflowModalProps) {
  const router = useRouter()
  const nameRef = useRef<HTMLInputElement>(null)
  const { selectedWorkspace } = useDashboard()

  const [selectedType, setSelectedType] = useState<WorkflowType>("data-migration")
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [tags, setTags] = useState<string[]>([])
  const [tagDraft, setTagDraft] = useState("")

  function addTag(raw: string) {
    const t = raw.trim().toUpperCase().replace(/\s+/g, "_").slice(0, 50)
    if (!t) return
    setTags((prev) => (prev.includes(t) ? prev : [...prev, t]))
    setTagDraft("")
  }

  function removeTag(t: string) {
    setTags((prev) => prev.filter((x) => x !== t))
  }

  // Players (sistemas)
  const [players, setPlayers] = useState<WorkspacePlayer[]>([])
  const [playersLoading, setPlayersLoading] = useState(false)
  const [selectedPlayerId, setSelectedPlayerId] = useState<string | null>(null)

  // Focus name field when modal opens + load players
  useEffect(() => {
    if (open) {
      setTimeout(() => nameRef.current?.focus(), 80)
      if (selectedWorkspace?.id) {
        setPlayersLoading(true)
        listWorkspacePlayers(selectedWorkspace.id)
          .then(setPlayers)
          .catch(() => setPlayers([]))
          .finally(() => setPlayersLoading(false))
      }
    } else {
      setSelectedType("data-migration")
      setName("")
      setDescription("")
      setTags([])
      setTagDraft("")
      setSelectedPlayerId(null)
      setPlayers([])
    }
  }, [open, selectedWorkspace?.id])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onOpenChange(false)
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [open, onOpenChange])

  // Lock scroll
  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleCreate() {
    if (!name.trim()) {
      nameRef.current?.focus()
      return
    }
    setCreating(true)
    setError(null)
    try {
      const workflow = await createWorkflow({
        name: name.trim(),
        description: description.trim() || null,
        workspace_id: selectedWorkspace?.id ?? undefined,
        tags,
        definition: {
          nodes: [],
          edges: [],
          meta: {
            workflow_type: selectedType,
            player_id: selectedPlayerId ?? undefined,
          },
        },
      })
      router.push(`/workflow/${workflow.id}`)
      onOpenChange(false)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Erro ao criar fluxo"
      setError(msg)
    } finally {
      setCreating(false)
    }
  }

  if (!open) return null

  const isMigration = selectedType === "data-migration"
  const playerRequired = isMigration
  const canCreate =
    name.trim().length > 0 && (!playerRequired || selectedPlayerId !== null)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-[2px]"
      onClick={() => onOpenChange(false)}
    >
      <div
        className="flex max-h-[90vh] w-[min(580px,96vw)] flex-col rounded-2xl border border-border bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-border px-6 py-5">
          <div>
            <h2 className="text-base font-semibold text-foreground">Criar Novo Fluxo</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Configure o tipo e as informações básicas do fluxo
            </p>
          </div>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">

          {/* Type selector */}
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Tipo do Fluxo
            </p>
            <div className="grid grid-cols-2 gap-3">
              {WORKFLOW_TYPES.map((opt) => {
                const isSelected = selectedType === opt.type
                return (
                  <button
                    key={opt.type}
                    type="button"
                    onClick={() => {
                      setSelectedType(opt.type)
                      setSelectedPlayerId(null)
                    }}
                    className={cn(
                      "group relative flex flex-col items-start gap-2.5 rounded-xl border-2 p-4 text-left transition-all",
                      isSelected
                        ? "border-primary bg-primary/5"
                        : "border-border bg-background hover:border-primary/30 hover:bg-muted/30"
                    )}
                  >
                    {isSelected && (
                      <span className="absolute right-3 top-3 flex size-4 items-center justify-center rounded-full bg-primary">
                        <span className="size-1.5 rounded-full bg-primary-foreground" />
                      </span>
                    )}
                    <div
                      className={cn(
                        "flex size-9 items-center justify-center rounded-lg transition-colors",
                        isSelected
                          ? "bg-primary/10 text-primary"
                          : "bg-muted text-muted-foreground group-hover:bg-primary/10 group-hover:text-primary"
                      )}
                    >
                      {opt.icon}
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-foreground">{opt.label}</p>
                      <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                        {opt.description}
                      </p>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          {/* ── Sistema de origem (apenas para Migração) ── */}
          {isMigration && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Sistema de Origem
                </p>
                <span className="text-[10px] text-destructive/80 font-medium">obrigatório</span>
              </div>

              {playersLoading ? (
                <div className="flex h-16 items-center justify-center gap-2 rounded-xl border border-dashed border-border text-xs text-muted-foreground">
                  <MorphLoader className="size-3.5" />
                  Carregando sistemas...
                </div>
              ) : players.length === 0 ? (
                <div className="flex items-start gap-3 rounded-xl border border-dashed border-border bg-muted/20 p-4">
                  <AlertCircle className="mt-0.5 size-4 shrink-0 text-amber-500" />
                  <div>
                    <p className="text-xs font-medium text-foreground">
                      Nenhum sistema cadastrado neste workspace
                    </p>
                    <p className="mt-0.5 text-[11px] text-muted-foreground">
                      Acesse{" "}
                      <span className="font-medium text-foreground">
                        Espaço → Grupo Econômico
                      </span>{" "}
                      para adicionar os sistemas antes de criar este fluxo.
                    </p>
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-2">
                  {players.map((player) => {
                    const isSelected = selectedPlayerId === player.id
                    return (
                      <button
                        key={player.id}
                        type="button"
                        onClick={() => setSelectedPlayerId(isSelected ? null : player.id)}
                        className={cn(
                          "group relative flex items-center gap-3 rounded-lg border-2 px-3 py-2.5 text-left transition-all",
                          isSelected
                            ? "border-primary bg-primary/5"
                            : "border-border bg-background hover:border-primary/30 hover:bg-muted/30"
                        )}
                      >
                        {isSelected && (
                          <span className="absolute right-2 top-2 flex size-3.5 items-center justify-center rounded-full bg-primary">
                            <span className="size-1 rounded-full bg-primary-foreground" />
                          </span>
                        )}
                        {/* DB type avatar */}
                        <div
                          className={cn(
                            "flex size-8 shrink-0 items-center justify-center rounded-md text-[10px] font-bold tracking-tight transition-colors",
                            isSelected
                              ? "bg-primary/10 text-primary"
                              : "bg-muted text-muted-foreground group-hover:bg-primary/10 group-hover:text-primary"
                          )}
                        >
                          {player.database_type.slice(0, 2)}
                        </div>
                        <div className="min-w-0">
                          <p className="truncate text-xs font-semibold text-foreground">
                            {player.name}
                          </p>
                          <p className="text-[10px] text-muted-foreground">
                            {DB_LABELS[player.database_type] ?? player.database_type}
                          </p>
                        </div>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          )}

          {/* Name */}
          <div className="space-y-1.5">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Nome do Fluxo
            </label>
            <input
              ref={nameRef}
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && canCreate && handleCreate()}
              placeholder={
                isMigration
                  ? `Ex: Migração Clientes ${players.find((p) => p.id === selectedPlayerId)?.name ?? "Construshow"}`
                  : "Ex: Configuração de Parâmetros Fiscais"
              }
              maxLength={255}
              className="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm text-foreground outline-none placeholder:text-muted-foreground/50 focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all"
            />
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Descrição{" "}
              <span className="normal-case font-normal text-muted-foreground/60">(opcional)</span>
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Descreva o objetivo deste fluxo..."
              rows={2}
              maxLength={1024}
              className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2.5 text-sm text-foreground outline-none placeholder:text-muted-foreground/50 focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all"
            />
          </div>

          {/* Tags */}
          <div className="space-y-1.5">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Tags{" "}
              <span className="normal-case font-normal text-muted-foreground/60">
                (opcional — Enter ou vírgula para adicionar)
              </span>
            </label>
            <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-input bg-background px-2 py-1.5 focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20 transition-all">
              {tags.map((t) => (
                <span
                  key={t}
                  className="inline-flex items-center gap-1 rounded-md bg-primary/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-primary"
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
                value={tagDraft}
                onChange={(e) => {
                  const v = e.target.value
                  if (v.endsWith(",") || v.endsWith(";")) {
                    addTag(v.slice(0, -1))
                  } else {
                    setTagDraft(v.toUpperCase())
                  }
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault()
                    if (tagDraft.trim()) addTag(tagDraft)
                  } else if (e.key === "Backspace" && !tagDraft && tags.length > 0) {
                    removeTag(tags[tags.length - 1])
                  }
                }}
                onBlur={() => tagDraft.trim() && addTag(tagDraft)}
                placeholder={tags.length === 0 ? "Ex: FISCAL, CLIENTES, SAP" : ""}
                className="min-w-[120px] flex-1 bg-transparent py-0.5 text-sm uppercase text-foreground outline-none placeholder:text-muted-foreground/50 placeholder:normal-case"
              />
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="shrink-0 border-t border-border px-6 py-4">
          {error && (
            <p className="mb-3 text-xs text-destructive">{error}</p>
          )}
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              disabled={creating}
              className="h-9 rounded-lg border border-border bg-transparent px-4 text-sm font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-50"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={handleCreate}
              disabled={!canCreate || creating}
              className={cn(
                "inline-flex h-9 items-center gap-1.5 rounded-lg px-5 text-sm font-semibold transition-all",
                canCreate && !creating
                  ? "bg-primary text-primary-foreground hover:opacity-90 active:scale-[0.98]"
                  : "cursor-not-allowed bg-muted text-muted-foreground"
              )}
            >
              {creating && <MorphLoader className="size-3.5" />}
              Criar
              {!creating && <ArrowRight className="size-3.5" />}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
