"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import {
  Boxes,
  Copy,
  Eye,
  EyeOff,
  Globe,
  Lock,
  Pencil,
  Plus,
  Search,
  Trash2,
} from "lucide-react"
import { Tooltip } from "@/components/ui/tooltip"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { MorphLoader } from "@/components/ui/morph-loader"
import { useDashboard } from "@/lib/context/dashboard-context"
import { useToast } from "@/lib/context/toast-context"
import {
  type CreateCustomNodeDefinitionPayload,
  type CustomNodeDefinition,
  type UpdateCustomNodeDefinitionPayload,
  createCustomNodeDefinition,
  deleteCustomNodeDefinition,
  duplicateCustomNodeDefinition,
  listProjectCustomNodeDefinitions,
  listWorkspaceCustomNodeDefinitions,
  updateCustomNodeDefinition,
} from "@/lib/auth"
import type { DashboardScope } from "@/lib/dashboard-navigation"
import { hasWorkspacePermission } from "@/lib/permissions"
import { CustomNodeDefinitionFormModal } from "@/components/dashboard/custom-node-definition-form-modal"

interface CustomNodeDefinitionsSectionProps {
  scope: DashboardScope
}

export function CustomNodeDefinitionsSection({
  scope,
}: CustomNodeDefinitionsSectionProps) {
  const { selectedWorkspace, selectedProject } = useDashboard()
  const toast = useToast()

  const wsRole = selectedWorkspace?.my_role ?? null
  const canCreate =
    scope === "space" ? hasWorkspacePermission(wsRole, "MANAGER") : true

  const [definitions, setDefinitions] = useState<CustomNodeDefinition[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [search, setSearch] = useState("")

  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<CustomNodeDefinition | null>(null)

  const [deleteTarget, setDeleteTarget] = useState<CustomNodeDefinition | null>(
    null
  )
  const [deleting, setDeleting] = useState(false)
  const [duplicatingId, setDuplicatingId] = useState<string | null>(null)

  const loadDefinitions = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const data =
        scope === "space" && selectedWorkspace
          ? await listWorkspaceCustomNodeDefinitions(selectedWorkspace.id)
          : scope === "project" && selectedProject
            ? await listProjectCustomNodeDefinitions(selectedProject.id)
            : []
      setDefinitions(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar nós.")
    } finally {
      setLoading(false)
    }
  }, [scope, selectedWorkspace, selectedProject])

  useEffect(() => {
    void loadDefinitions()
  }, [loadDefinitions])

  const filtered = useMemo(() => {
    if (!search.trim()) return definitions
    const term = search.toLowerCase()
    return definitions.filter(
      (d) =>
        d.name.toLowerCase().includes(term) ||
        (d.description?.toLowerCase().includes(term) ?? false) ||
        d.category.toLowerCase().includes(term)
    )
  }, [definitions, search])

  function isInherited(def: CustomNodeDefinition) {
    return scope === "project" && def.workspace_id !== null
  }

  function canEdit(def: CustomNodeDefinition) {
    return !isInherited(def) && canCreate
  }

  function handleOpenCreate() {
    setEditing(null)
    setFormOpen(true)
  }

  function handleOpenEdit(def: CustomNodeDefinition) {
    setEditing(def)
    setFormOpen(true)
  }

  async function handleFormSubmit(
    payload:
      | CreateCustomNodeDefinitionPayload
      | UpdateCustomNodeDefinitionPayload
  ) {
    if (editing) {
      await updateCustomNodeDefinition(
        editing.id,
        payload as UpdateCustomNodeDefinitionPayload
      )
      toast.success("Nó atualizado", "As alterações foram salvas.")
    } else {
      await createCustomNodeDefinition(
        payload as CreateCustomNodeDefinitionPayload
      )
      toast.success("Nó criado", "A definição foi cadastrada com sucesso.")
    }
    setFormOpen(false)
    setEditing(null)
    await loadDefinitions()
  }

  async function handleDuplicate(def: CustomNodeDefinition) {
    setDuplicatingId(def.id)
    try {
      const clone = await duplicateCustomNodeDefinition(def.id)
      await loadDefinitions()
      toast.success(
        "Nó duplicado",
        `Nova versão v${clone.version} criada como rascunho.`
      )
    } catch (err) {
      toast.error(
        "Erro ao duplicar",
        err instanceof Error ? err.message : "Erro ao duplicar nó."
      )
    } finally {
      setDuplicatingId(null)
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteCustomNodeDefinition(deleteTarget.id)
      setDeleteTarget(null)
      await loadDefinitions()
      toast.success("Nó excluído", "A definição foi removida com sucesso.")
    } catch (err) {
      toast.error(
        "Erro ao excluir",
        err instanceof Error ? err.message : "Erro ao excluir nó."
      )
    } finally {
      setDeleting(false)
    }
  }

  const scopeIds =
    scope === "space" && selectedWorkspace
      ? { workspace_id: selectedWorkspace.id, project_id: null }
      : scope === "project" && selectedProject
        ? { workspace_id: null, project_id: selectedProject.id }
        : { workspace_id: null, project_id: null }

  if (loading) {
    return (
      <section className="flex items-center justify-center py-20">
        <MorphLoader className="size-5" />
      </section>
    )
  }

  return (
    <section className="space-y-3">
      <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-xs text-muted-foreground">
          Defina nós compostos reutilizáveis que aparecem na paleta do editor de
          fluxos.
        </div>

        <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center">
          <label className="flex h-8 w-full items-center gap-1.5 rounded-md border border-input bg-background px-2.5 sm:w-[180px]">
            <Search className="size-3 text-muted-foreground" />
            <input
              type="text"
              placeholder="Buscar..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground"
            />
          </label>

          {canCreate ? (
            <button
              type="button"
              onClick={handleOpenCreate}
              className="inline-flex h-8 items-center justify-center gap-1 rounded-md bg-foreground px-3 text-xs font-semibold text-background transition-opacity hover:opacity-90"
            >
              <Plus className="size-3.5" />
              Novo Nó
            </button>
          ) : null}
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}

      {filtered.length === 0 && !error ? (
        <div className="rounded-2xl border border-dashed border-border bg-card/60 p-8 text-center">
          <Boxes className="mx-auto size-10 text-muted-foreground/40" />
          <p className="mt-3 text-base font-semibold text-foreground">
            Nenhum nó personalizado encontrado
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {search
              ? "Nenhum resultado para o filtro aplicado."
              : "Cadastre seu primeiro nó composto reutilizável."}
          </p>
          {!search && canCreate && (
            <button
              type="button"
              onClick={handleOpenCreate}
              className="mt-4 inline-flex h-9 items-center justify-center gap-1.5 rounded-md bg-foreground px-4 text-sm font-semibold text-background transition-opacity hover:opacity-90"
            >
              <Plus className="size-4" />
              Novo Nó
            </button>
          )}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-sm">
          <div className="grid min-w-[820px] grid-cols-[1fr_120px_100px_90px_120px_110px] items-center border-b border-border px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            <span>Nó</span>
            <span className="text-left">Categoria</span>
            <span className="text-left">Tabelas</span>
            <span className="text-left">Versão</span>
            <span className="text-left">Status</span>
            <span className="text-right">Ações</span>
          </div>

          <div className="divide-y divide-border">
            {filtered.map((def) => {
              const inherited = isInherited(def)
              const editable = canEdit(def)
              return (
                <div
                  key={def.id}
                  className="grid min-w-[820px] grid-cols-[1fr_120px_100px_90px_120px_110px] items-center px-4 py-4 transition-colors hover:bg-muted/10"
                >
                  <div className="flex items-center gap-3">
                    <div
                      className="flex size-8 items-center justify-center rounded-md bg-primary/10 text-primary"
                      style={def.color ? { color: def.color } : undefined}
                    >
                      <Boxes className="size-4" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="truncate text-[13px] font-semibold text-foreground">
                          {def.name}
                        </p>
                        {inherited && (
                          <span className="inline-flex items-center gap-1 rounded bg-violet-500/10 px-1.5 py-0.5 text-[10px] font-medium text-violet-500">
                            <Globe className="size-3" />
                            Herdada
                          </span>
                        )}
                      </div>
                      {def.description && (
                        <p className="truncate text-[11px] text-muted-foreground">
                          {def.description}
                        </p>
                      )}
                    </div>
                  </div>

                  <div>
                    <span className="inline-flex rounded bg-muted px-2 py-0.5 text-[10px] font-medium text-foreground">
                      {def.category}
                    </span>
                  </div>

                  <p className="text-[12px] text-foreground">
                    {def.blueprint?.tables?.length ?? 0}
                  </p>

                  <p className="text-[12px] text-foreground">v{def.version}</p>

                  <div>
                    {def.is_published ? (
                      <span className="inline-flex items-center gap-1 rounded bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
                        <Eye className="size-3" />
                        Publicado
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400">
                        <EyeOff className="size-3" />
                        Rascunho
                      </span>
                    )}
                  </div>

                  <div className="flex items-center justify-end gap-1">
                    {editable ? (
                      <>
                        <Tooltip text="Editar">
                          <button
                            type="button"
                            onClick={() => handleOpenEdit(def)}
                            className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                            aria-label="Editar nó"
                          >
                            <Pencil className="size-4" />
                          </button>
                        </Tooltip>
                        <Tooltip text="Duplicar como nova versão">
                          <button
                            type="button"
                            onClick={() => handleDuplicate(def)}
                            disabled={duplicatingId === def.id}
                            className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
                            aria-label="Duplicar nó"
                          >
                            <Copy className="size-4" />
                          </button>
                        </Tooltip>
                        <Tooltip text="Excluir">
                          <button
                            type="button"
                            onClick={() => setDeleteTarget(def)}
                            className="rounded p-2 text-destructive/70 transition-colors hover:bg-muted hover:text-destructive"
                            aria-label="Excluir nó"
                          >
                            <Trash2 className="size-4" />
                          </button>
                        </Tooltip>
                      </>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded px-2 py-1 text-[10px] text-muted-foreground">
                        <Lock className="size-3" />
                        {inherited ? "Herdada" : "Sem permissão"}
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null)
        }}
        title="Excluir nó personalizado"
        description={`Tem certeza que deseja excluir "${deleteTarget?.name}"? Esta ação não pode ser desfeita.`}
        confirmText="Excluir"
        confirmVariant="destructive"
        loading={deleting}
        onConfirm={handleDelete}
      />

      <CustomNodeDefinitionFormModal
        open={formOpen}
        onOpenChange={(open) => {
          setFormOpen(open)
          if (!open) setEditing(null)
        }}
        definition={editing}
        scopeIds={scopeIds}
        onSubmit={handleFormSubmit}
      />
    </section>
  )
}
