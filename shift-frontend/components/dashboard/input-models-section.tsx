"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import {
  Database,
  Download,
  FileSpreadsheet,
  Grid2X2,
  List,
  Loader2,
  Pencil,
  Plus,
  Search,
  Trash2,
} from "lucide-react"
import { useDashboard } from "@/lib/context/dashboard-context"
import {
  listWorkspaceInputModels,
  deleteInputModel,
  downloadInputModelTemplate,
  type InputModel,
} from "@/lib/auth"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { InputModelFormModal } from "@/components/dashboard/input-model-form-modal"
import { useToast } from "@/lib/context/toast-context"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tooltip } from "@/components/ui/tooltip"
import { MorphLoader } from "@/components/ui/morph-loader"

export function InputModelsSection() {
  const { selectedWorkspace } = useDashboard()
  const router = useRouter()
  const toast = useToast()

  const [models, setModels] = useState<InputModel[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [view, setView] = useState<"list" | "card">("list")
  const [typeFilter, setTypeFilter] = useState<"todos" | "excel" | "csv" | "data">("todos")

  // Modal state
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<InputModel | null>(null)

  // Delete state
  const [deleteTarget, setDeleteTarget] = useState<InputModel | null>(null)
  const [deleting, setDeleting] = useState(false)

  const loadModels = useCallback(async () => {
    if (!selectedWorkspace) return
    setLoading(true)
    setError(null)
    try {
      const data = await listWorkspaceInputModels(selectedWorkspace.id)
      setModels(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar modelos de entrada.")
    } finally {
      setLoading(false)
    }
  }, [selectedWorkspace])

  useEffect(() => {
    void loadModels()
  }, [loadModels])

  const filtered = useMemo(() => {
    let result = models
    if (typeFilter !== "todos") {
      result = result.filter((m) => m.file_type === typeFilter)
    }
    if (search.trim()) {
      const q = search.toLowerCase()
      result = result.filter(
        (m) => m.name.toLowerCase().includes(q) || m.description?.toLowerCase().includes(q),
      )
    }
    return result
  }, [models, search, typeFilter])

  function handleOpenCreate() {
    setEditing(null)
    setFormOpen(true)
  }

  function handleOpenEdit(model: InputModel) {
    setEditing(model)
    setFormOpen(true)
  }

  async function handleDelete() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteInputModel(deleteTarget.id)
      setDeleteTarget(null)
      await loadModels()
      toast.success("Modelo excluído", "O modelo de entrada foi removido com sucesso.")
    } catch (err) {
      toast.error("Erro ao excluir", err instanceof Error ? err.message : "Erro ao excluir modelo.")
    } finally {
      setDeleting(false)
    }
  }

  async function handleDownload(model: InputModel) {
    try {
      await downloadInputModelTemplate(model.id)
    } catch {
      toast.error("Erro ao baixar", "Não foi possível baixar o template.")
    }
  }

  function countColumns(model: InputModel): number {
    return model.schema_def?.sheets?.reduce((sum, s) => sum + (s.columns?.length ?? 0), 0) ?? 0
  }

  function fileTypeLabel(ft: string) {
    if (ft === "excel") return "Excel"
    if (ft === "csv") return "CSV"
    return "Dados"
  }

  function fileTypeBadge(ft: string) {
    if (ft === "excel") return "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
    if (ft === "csv") return "bg-blue-500/10 text-blue-600 dark:text-blue-400"
    return "bg-violet-500/10 text-violet-600 dark:text-violet-400"
  }

  function formatDate(iso: string) {
    try {
      return new Date(iso).toLocaleDateString("pt-BR")
    } catch {
      return iso
    }
  }

  if (!selectedWorkspace) {
    return <p className="text-sm text-muted-foreground">Selecione um espaço para ver os modelos de entrada.</p>
  }

  if (loading) {
    return (
      <section className="flex items-center justify-center py-20">
        <MorphLoader className="size-5" />
      </section>
    )
  }

  return (
    <section className="space-y-3">
      {/* Toolbar */}
      <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-3 sm:flex-row sm:items-center sm:justify-between">
        {/* Toggle Lista / Card */}
        <div className="inline-flex w-fit items-center rounded-md border border-border bg-background p-1">
          <button
            type="button"
            onClick={() => setView("list")}
            className={`inline-flex h-7 items-center gap-1.5 rounded px-2.5 text-xs font-medium transition-colors ${
              view === "list" ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <List className="size-3.5" />
            Lista
          </button>
          <button
            type="button"
            onClick={() => setView("card")}
            className={`inline-flex h-7 items-center gap-1.5 rounded px-2.5 text-xs font-medium transition-colors ${
              view === "card" ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Grid2X2 className="size-3.5" />
            Card
          </button>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          {/* Filtro por tipo */}
          <Select value={typeFilter} onValueChange={(v) => setTypeFilter(v as "todos" | "excel" | "csv" | "data")}>
            <SelectTrigger className="w-full min-w-40 bg-background sm:w-[160px]">
              <SelectValue placeholder="Todos os Tipos" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="todos">Todos os Tipos</SelectItem>
              <SelectItem value="excel">Excel</SelectItem>
              <SelectItem value="csv">CSV</SelectItem>
              <SelectItem value="data">Dados</SelectItem>
            </SelectContent>
          </Select>

          <label className="flex h-9 w-full items-center gap-2 rounded-md border border-input bg-background px-3 sm:w-[220px]">
            <Search className="size-4 text-muted-foreground" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar..."
              className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
            />
          </label>

          <button
            type="button"
            onClick={handleOpenCreate}
            className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md bg-foreground px-3.5 text-sm font-semibold text-background transition-opacity hover:opacity-90"
          >
            <Plus className="size-4" />
            Novo Modelo
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}

      {/* Empty state */}
      {filtered.length === 0 && !error ? (
        <div className="rounded-2xl border border-dashed border-border bg-card/60 p-8 text-center">
          <FileSpreadsheet className="mx-auto size-10 text-muted-foreground/40" />
          <p className="mt-3 text-base font-semibold text-foreground">
            Nenhum modelo de entrada
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {search || typeFilter !== "todos"
              ? "Nenhum resultado para os filtros aplicados."
              : "Crie um modelo para padronizar o formato dos arquivos que os consultores devem enviar."}
          </p>
          {!search && typeFilter === "todos" && (
            <button
              type="button"
              onClick={handleOpenCreate}
              className="mt-4 inline-flex h-9 items-center justify-center gap-1.5 rounded-md bg-foreground px-4 text-sm font-semibold text-background transition-opacity hover:opacity-90"
            >
              <Plus className="size-4" />
              Criar primeiro modelo
            </button>
          )}
        </div>
      ) : view === "list" ? (
        /* ── Vista lista ── */
        <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-sm">
          <div className="grid min-w-[700px] grid-cols-[1fr_90px_80px_80px_110px_120px] items-center border-b border-border px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            <span>Modelo</span>
            <span className="text-left">Tipo</span>
            <span className="text-center">Abas</span>
            <span className="text-center">Colunas</span>
            <span className="text-left">Criado em</span>
            <span className="text-right">Ações</span>
          </div>

          <div className="divide-y divide-border">
            {filtered.map((model) => (
              <div
                key={model.id}
                className="grid min-w-[700px] grid-cols-[1fr_90px_80px_80px_110px_120px] items-center px-4 py-4 transition-colors hover:bg-muted/10"
              >
                <div className="flex items-center gap-3">
                  <div className="flex size-8 items-center justify-center rounded-md bg-primary/10 text-primary">
                    <FileSpreadsheet className="size-4" />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-semibold text-foreground">{model.name}</p>
                    {model.description && (
                      <p className="truncate text-[11px] text-muted-foreground">{model.description}</p>
                    )}
                  </div>
                </div>

                <div>
                  <span className={`inline-flex rounded px-2 py-0.5 text-[10px] font-medium uppercase ${fileTypeBadge(model.file_type)}`}>
                    {fileTypeLabel(model.file_type)}
                  </span>
                </div>

                <p className="text-center text-[12px] text-foreground">{model.schema_def?.sheets?.length ?? 0}</p>

                <p className="text-center text-[12px] text-foreground">{countColumns(model)}</p>

                <p className="text-[12px] text-foreground">{formatDate(model.created_at)}</p>

                <div className="flex items-center justify-end gap-1">
                  <Tooltip text="Dados">
                    <button
                      type="button"
                      onClick={() => router.push(`/espaco/modelos-entrada/${model.id}`)}
                      className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                      aria-label="Ver dados"
                    >
                      <Database className="size-4" />
                    </button>
                  </Tooltip>
                  {model.file_type !== "data" && (
                    <Tooltip text="Baixar template">
                      <button
                        type="button"
                        onClick={() => void handleDownload(model)}
                        className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                        aria-label="Baixar template"
                      >
                        <Download className="size-4" />
                      </button>
                    </Tooltip>
                  )}
                  <Tooltip text="Editar">
                    <button
                      type="button"
                      onClick={() => handleOpenEdit(model)}
                      className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                      aria-label="Editar modelo"
                    >
                      <Pencil className="size-4" />
                    </button>
                  </Tooltip>
                  <Tooltip text="Excluir">
                    <button
                      type="button"
                      onClick={() => setDeleteTarget(model)}
                      className="rounded p-2 text-destructive/70 transition-colors hover:bg-muted hover:text-destructive"
                      aria-label="Excluir modelo"
                    >
                      <Trash2 className="size-4" />
                    </button>
                  </Tooltip>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        /* ── Vista card ── */
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((model) => (
            <article
              key={model.id}
              className="rounded-xl border border-border bg-card p-4 shadow-sm transition-colors hover:bg-muted/10"
            >
              {/* Header: ícone + nome + tipo badge */}
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3 min-w-0">
                  <div className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                    <FileSpreadsheet className="size-4" />
                  </div>
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold text-foreground">{model.name}</h3>
                    {model.description && (
                      <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{model.description}</p>
                    )}
                  </div>
                </div>
                <span className={`shrink-0 inline-flex rounded px-2 py-0.5 text-[10px] font-medium uppercase ${fileTypeBadge(model.file_type)}`}>
                  {fileTypeLabel(model.file_type)}
                </span>
              </div>

              {/* Badges: abas + colunas */}
              <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                <span>{model.schema_def?.sheets?.length ?? 0} aba(s)</span>
                <span className="text-border">·</span>
                <span>{countColumns(model)} coluna(s)</span>
                <span className="text-border">·</span>
                <span>{formatDate(model.created_at)}</span>
              </div>

              {/* Footer: ações */}
              <div className="mt-3 flex items-center justify-end gap-1 border-t border-border pt-3">
                <Tooltip text="Dados">
                  <button
                    type="button"
                    onClick={() => router.push(`/espaco/modelos-entrada/${model.id}`)}
                    className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    aria-label="Ver dados"
                  >
                    <Database className="size-4" />
                  </button>
                </Tooltip>
                {model.file_type !== "data" && (
                  <Tooltip text="Baixar template">
                    <button
                      type="button"
                      onClick={() => void handleDownload(model)}
                      className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                      aria-label="Baixar template"
                    >
                      <Download className="size-4" />
                    </button>
                  </Tooltip>
                )}
                <Tooltip text="Editar">
                  <button
                    type="button"
                    onClick={() => handleOpenEdit(model)}
                    className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    aria-label="Editar modelo"
                  >
                    <Pencil className="size-4" />
                  </button>
                </Tooltip>
                <Tooltip text="Excluir">
                  <button
                    type="button"
                    onClick={() => setDeleteTarget(model)}
                    className="rounded p-2 text-destructive/70 transition-colors hover:bg-muted hover:text-destructive"
                    aria-label="Excluir modelo"
                  >
                    <Trash2 className="size-4" />
                  </button>
                </Tooltip>
              </div>
            </article>
          ))}
        </div>
      )}

      {/* Form modal */}
      <InputModelFormModal
        open={formOpen}
        onOpenChange={setFormOpen}
        editing={editing}
        workspaceId={selectedWorkspace.id}
        onSaved={loadModels}
      />

      {/* Delete confirmation */}
      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}
        title="Excluir modelo de entrada"
        description={`Tem certeza que deseja excluir "${deleteTarget?.name}"? Esta ação não pode ser desfeita.`}
        confirmText="Excluir"
        confirmVariant="destructive"
        loading={deleting}
        onConfirm={handleDelete}
      />
    </section>
  )
}
