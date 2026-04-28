"use client"

import { useEffect, useState } from "react"
import { CheckCircle2, ChevronDown, Copy, Info, X } from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import { cn } from "@/lib/utils"
import {
  cloneWorkflowTemplate,
  listWorkspaceProjects,
  listWorkspaceConnections,
  type Workflow,
  type Project,
  type Connection,
} from "@/lib/auth"

interface CloneTemplateModalProps {
  template: Workflow
  workspaceId: string
  onClose: () => void
  onCloned: (workflow: Workflow) => void
}

const VAR_REF_RE = /^\{\{\s*vars\.[A-Za-z_][A-Za-z0-9_]*\s*\}\}$/

function hasConnectionVariables(definition: Record<string, unknown>): boolean {
  const vars = definition.variables as Array<{ type: string }> | undefined
  return vars?.some((v) => v.type === "connection") ?? false
}

function collectLiteralConnectionIds(definition: Record<string, unknown>): string[] {
  const ids = new Set<string>()

  function walk(node: unknown): void {
    if (Array.isArray(node)) {
      for (const item of node) walk(item)
    } else if (node !== null && typeof node === "object") {
      const obj = node as Record<string, unknown>
      for (const [key, val] of Object.entries(obj)) {
        if (
          key === "connection_id" &&
          typeof val === "string" &&
          val.length > 0 &&
          !VAR_REF_RE.test(val)
        ) {
          ids.add(val)
        } else {
          walk(val)
        }
      }
    }
  }

  walk(definition)
  return Array.from(ids)
}

export function CloneTemplateModal({
  template,
  workspaceId,
  onClose,
  onCloned,
}: CloneTemplateModalProps) {
  const [projects, setProjects] = useState<Project[]>([])
  const [connections, setConnections] = useState<Connection[]>([])
  const [loadingData, setLoadingData] = useState(true)
  const [targetProjectId, setTargetProjectId] = useState<string>("")
  const [connectionMapping, setConnectionMapping] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cloned, setCloned] = useState(false)

  const hasConnVars = hasConnectionVariables(template.definition)
  const literalConnIds = collectLiteralConnectionIds(template.definition)
  const hasLiteralConns = literalConnIds.length > 0

  useEffect(() => {
    let cancelled = false
    setLoadingData(true)
    Promise.all([
      listWorkspaceProjects(workspaceId),
      listWorkspaceConnections(workspaceId, { size: 200 }),
    ])
      .then(([projs, conns]) => {
        if (cancelled) return
        setProjects(projs)
        setConnections(conns.items)
        if (projs.length === 1) setTargetProjectId(projs[0].id)
      })
      .catch(() => {
        if (!cancelled) setError("Falha ao carregar projetos e conexões.")
      })
      .finally(() => {
        if (!cancelled) setLoadingData(false)
      })
    return () => { cancelled = true }
  }, [workspaceId])

  const handleSubmit = async () => {
    if (!targetProjectId) return
    setSubmitting(true)
    setError(null)
    try {
      const workflow = await cloneWorkflowTemplate(template.id, {
        target_project_id: targetProjectId,
        connection_mapping: hasLiteralConns ? connectionMapping : undefined,
      })
      setCloned(true)
      onCloned(workflow)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao clonar template.")
    } finally {
      setSubmitting(false)
    }
  }

  const selectCls =
    "h-9 w-full appearance-none rounded-md border border-input bg-background px-2.5 pr-8 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="flex w-full max-w-lg flex-col rounded-xl border border-border bg-card shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-2">
            <Copy className="size-4 text-muted-foreground" />
            <span className="text-sm font-semibold text-foreground">Clonar template</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* Body */}
        <div className="space-y-4 p-5">
          {/* Template name */}
          <div className="rounded-lg border border-border bg-muted/30 px-3 py-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Template
            </p>
            <p className="mt-0.5 text-sm font-medium text-foreground">{template.name}</p>
            {template.description && (
              <p className="mt-0.5 text-xs text-muted-foreground">{template.description}</p>
            )}
          </div>

          {/* Connection variables info */}
          {hasConnVars && (
            <div className="flex items-start gap-2.5 rounded-lg border border-violet-500/30 bg-violet-500/8 p-3 text-xs text-violet-700 dark:text-violet-400">
              <Info className="mt-0.5 size-3.5 shrink-0" />
              <p>
                Este template usa <strong>variáveis de conexão</strong> — você escolherá as
                conexões ao executar o fluxo clonado, não agora.
              </p>
            </div>
          )}

          {/* Cloned success */}
          {cloned ? (
            <div className="flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-700 dark:text-emerald-400">
              <CheckCircle2 className="size-4 shrink-0" />
              <p>
                Fluxo clonado com sucesso para o projeto selecionado!
              </p>
            </div>
          ) : loadingData ? (
            <div className="flex items-center justify-center py-6 text-xs text-muted-foreground">
              <MorphLoader className="mr-2 size-4" />
              Carregando…
            </div>
          ) : (
            <>
              {/* Target project selector */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-foreground">
                  Projeto destino <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <select
                    value={targetProjectId}
                    onChange={(e) => setTargetProjectId(e.target.value)}
                    className={selectCls}
                  >
                    <option value="">Selecione um projeto…</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                </div>
              </div>

              {/* Connection mapping (only when literal UUIDs exist in template) */}
              {hasLiteralConns && (
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <div className="h-px flex-1 bg-border" />
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Mapeamento de conexões
                    </span>
                    <div className="h-px flex-1 bg-border" />
                  </div>
                  <p className="text-[11px] text-muted-foreground">
                    O template referencia conexões fixas. Mapeie cada uma para uma conexão do seu workspace.
                  </p>
                  {literalConnIds.map((connId) => (
                    <div key={connId} className="space-y-1">
                      <label className="truncate text-[11px] font-mono text-muted-foreground">
                        {connId.slice(0, 8)}…
                      </label>
                      <div className="relative">
                        <select
                          value={connectionMapping[connId] ?? ""}
                          onChange={(e) =>
                            setConnectionMapping((prev) => ({
                              ...prev,
                              [connId]: e.target.value,
                            }))
                          }
                          className={cn(selectCls, "font-normal")}
                        >
                          <option value="">Selecione uma conexão…</option>
                          {connections.map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.name}
                            </option>
                          ))}
                        </select>
                        <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {error && (
            <p className="rounded border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-600">
              {error}
            </p>
          )}
        </div>

        {/* Footer */}
        {!cloned && !loadingData && (
          <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
            <button
              type="button"
              onClick={onClose}
              className="h-8 rounded-md border border-border bg-background px-3 text-xs font-medium text-foreground transition hover:bg-muted"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!targetProjectId || submitting}
              className="flex h-8 items-center gap-1.5 rounded-md bg-foreground px-3 text-xs font-semibold text-background transition hover:opacity-90 disabled:opacity-50"
            >
              {submitting ? (
                <MorphLoader className="size-3.5" />
              ) : (
                <Copy className="size-3.5" />
              )}
              Clonar
            </button>
          </div>
        )}
        {cloned && (
          <div className="flex justify-end border-t border-border px-5 py-3">
            <button
              type="button"
              onClick={onClose}
              className="h-8 rounded-md border border-border bg-background px-3 text-xs font-medium text-foreground transition hover:bg-muted"
            >
              Fechar
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
