"use client"

import { useEffect, useState } from "react"
import { AlertTriangle, Rocket, X } from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import {
  listWorkflowVersions,
  publishWorkflowVersion,
  type WorkflowIOSchema,
  type WorkflowVersionResponse,
} from "@/lib/api/workflow-versions"

interface PublishVersionModalProps {
  workflowId: string
  ioSchema: WorkflowIOSchema
  hasUnsavedChanges: boolean
  onSaveBeforePublish: () => Promise<void>
  onClose: () => void
  onPublished: (version: WorkflowVersionResponse) => void
}

export function PublishVersionModal({
  workflowId,
  ioSchema,
  hasUnsavedChanges,
  onSaveBeforePublish,
  onClose,
  onPublished,
}: PublishVersionModalProps) {
  const [nextVersion, setNextVersion] = useState<number | null>(null)
  const [loadingVersion, setLoadingVersion] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [notes, setNotes] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoadingVersion(true)
    setLoadError(null)
    listWorkflowVersions(workflowId)
      .then((rows) => {
        if (cancelled) return
        const max = rows.reduce((acc, r) => Math.max(acc, r.version), 0)
        setNextVersion(max + 1)
      })
      .catch((err) => {
        if (cancelled) return
        setLoadError(
          err instanceof Error
            ? err.message
            : "Falha ao carregar versões existentes.",
        )
      })
      .finally(() => {
        if (!cancelled) setLoadingVersion(false)
      })
    return () => {
      cancelled = true
    }
  }, [workflowId])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !submitting) onClose()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [onClose, submitting])

  async function handlePublish() {
    setSubmitting(true)
    setError(null)
    try {
      if (hasUnsavedChanges) {
        await onSaveBeforePublish()
      }
      const published = await publishWorkflowVersion(workflowId, {
        io_schema: ioSchema,
        definition: null,
      })
      onPublished(published)
      onClose()
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Falha ao publicar versão.",
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-[2px]"
      onClick={() => !submitting && onClose()}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-border bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex h-12 items-center justify-between border-b border-border px-4">
          <div className="flex items-center gap-2">
            <div className="flex size-8 items-center justify-center rounded-lg bg-emerald-100 dark:bg-emerald-500/20">
              <Rocket className="size-4 text-emerald-600 dark:text-emerald-400" />
            </div>
            <span className="text-sm font-semibold text-foreground">
              Publicar versão
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            aria-label="Fechar"
            className="flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
          >
            <X className="size-4" />
          </button>
        </header>

        <div className="space-y-4 p-4">
          <div className="rounded-md border border-border bg-muted/30 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Próxima versão
            </p>
            <div className="mt-1 flex items-baseline gap-2">
              {loadingVersion ? (
                <span className="flex items-center gap-2 text-sm text-muted-foreground">
                  <MorphLoader className="size-3.5" /> Carregando…
                </span>
              ) : loadError ? (
                <span className="text-xs text-destructive">{loadError}</span>
              ) : (
                <span className="font-mono text-xl font-bold text-emerald-600 dark:text-emerald-400">
                  v{nextVersion}
                </span>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <SchemaCount
              label="Inputs"
              count={ioSchema.inputs.length}
              requiredCount={
                ioSchema.inputs.filter((p) => p.required ?? true).length
              }
            />
            <SchemaCount
              label="Outputs"
              count={ioSchema.outputs.length}
              requiredCount={null}
            />
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="publish-notes"
              className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground"
            >
              Notas da versão (opcional)
            </label>
            <textarea
              id="publish-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="O que mudou nesta versão? (informativo apenas)"
              rows={3}
              className="w-full rounded-md border border-input bg-background px-2.5 py-2 text-xs outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          {hasUnsavedChanges && (
            <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 p-2.5">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-amber-500" />
              <p className="text-[11px] text-amber-700 dark:text-amber-300">
                Há alterações não salvas. Elas serão persistidas antes da
                publicação.
              </p>
            </div>
          )}

          <div className="flex items-start gap-2 rounded-md border border-destructive/20 bg-destructive/5 p-2.5">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-destructive" />
            <p className="text-[11px] text-destructive">
              Versões publicadas são <strong>imutáveis</strong>. Para ajustar,
              publique uma nova versão.
            </p>
          </div>

          {error && (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-2 text-[11px] text-destructive">
              {error}
            </div>
          )}
        </div>

        <footer className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="inline-flex h-8 items-center rounded-md border border-border bg-background px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-50"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={handlePublish}
            disabled={submitting || loadingVersion || !!loadError}
            className="inline-flex h-8 items-center gap-1.5 rounded-md bg-emerald-600 px-3 text-xs font-semibold text-white transition-colors hover:bg-emerald-700 disabled:opacity-50"
          >
            {submitting ? (
              <>
                <MorphLoader className="size-3.5" /> Publicando…
              </>
            ) : (
              <>
                <Rocket className="size-3.5" /> Publicar v{nextVersion ?? "?"}
              </>
            )}
          </button>
        </footer>
      </div>
    </div>
  )
}

function SchemaCount({
  label,
  count,
  requiredCount,
}: {
  label: string
  count: number
  requiredCount: number | null
}) {
  return (
    <div className="rounded-md border border-border bg-muted/30 p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 font-mono text-xl font-bold text-foreground">{count}</p>
      {requiredCount !== null && count > 0 && (
        <p className="mt-0.5 text-[10px] text-muted-foreground">
          {requiredCount} obrigatório{requiredCount === 1 ? "" : "s"}
        </p>
      )}
    </div>
  )
}
