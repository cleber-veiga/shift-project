"use client"

import { use, useCallback, useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { ArrowLeft, Boxes, Edit2, Plus, Trash2, Users, X } from "lucide-react"
import {
  createWorkspacePlayer,
  deleteWorkspacePlayer,
  listWorkspacePlayers,
  updateWorkspace,
  updateWorkspacePlayer,
  type WorkspacePlayer,
  type WorkspacePlayerDatabaseType,
} from "@/lib/auth"
import { useDashboard } from "@/lib/context/dashboard-context"
import { MorphLoader } from "@/components/ui/morph-loader"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

interface PageProps {
  params: Promise<{ id: string }>
}

const databaseOptions: Array<{ value: WorkspacePlayerDatabaseType; label: string }> = [
  { value: "POSTGRESQL", label: "PostgreSQL" },
  { value: "MYSQL", label: "MySQL" },
  { value: "SQLSERVER", label: "SQL Server" },
  { value: "ORACLE", label: "Oracle" },
  { value: "FIREBIRD", label: "Firebird" },
  { value: "SQLITE", label: "SQLite" },
  { value: "SNOWFLAKE", label: "Snowflake" },
]

function WorkspaceEditor({
  workspaceId,
  organizationId,
  workspaceName,
  organizationName,
  onWorkspaceNameSaved,
  refreshWorkspaces,
}: {
  workspaceId: string
  organizationId: string
  workspaceName: string
  organizationName: string
  onWorkspaceNameSaved: (nextName: string) => Promise<void>
  refreshWorkspaces: () => Promise<void>
}) {
  const router = useRouter()
  const [name, setName] = useState(workspaceName)
  const [lastSavedName, setLastSavedName] = useState(workspaceName.trim())
  const [autoSaving, setAutoSaving] = useState(false)
  const [saveError, setSaveError] = useState("")

  const [players, setPlayers] = useState<WorkspacePlayer[]>([])
  const [playersLoading, setPlayersLoading] = useState(true)
  const [playersError, setPlayersError] = useState("")
  const [savingPlayer, setSavingPlayer] = useState(false)
  const [deletingPlayer, setDeletingPlayer] = useState(false)

  const [isPlayerModalOpen, setIsPlayerModalOpen] = useState(false)
  const [editingPlayerId, setEditingPlayerId] = useState<string | null>(null)
  const [playerName, setPlayerName] = useState("")
  const [playerDatabaseType, setPlayerDatabaseType] = useState<WorkspacePlayerDatabaseType>("POSTGRESQL")
  const [playerFormError, setPlayerFormError] = useState("")

  const [deletePlayerId, setDeletePlayerId] = useState<string | null>(null)
  const [deletePlayerName, setDeletePlayerName] = useState("")
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)

  const isEditingPlayer = !!editingPlayerId

  const loadPlayers = useCallback(async () => {
    setPlayersLoading(true)
    setPlayersError("")
    try {
      const items = await listWorkspacePlayers(workspaceId)
      setPlayers(items)
    } catch (err) {
      setPlayersError(err instanceof Error ? err.message : "Falha ao carregar sistemas do workspace.")
    } finally {
      setPlayersLoading(false)
    }
  }, [workspaceId])

  useEffect(() => {
    setName(workspaceName)
    setLastSavedName(workspaceName.trim())
  }, [workspaceId, workspaceName, organizationId])

  useEffect(() => {
    loadPlayers()
  }, [loadPlayers])

  useEffect(() => {
    const normalizedName = name.trim()
    if (normalizedName.length < 2 || normalizedName === lastSavedName) return

    const timer = window.setTimeout(async () => {
      setAutoSaving(true)
      setSaveError("")
      try {
        await onWorkspaceNameSaved(normalizedName)
        setLastSavedName(normalizedName)
      } catch (err) {
        setSaveError(err instanceof Error ? err.message : "Falha ao salvar nome do workspace.")
      } finally {
        setAutoSaving(false)
      }
    }, 700)

    return () => window.clearTimeout(timer)
  }, [name, lastSavedName, onWorkspaceNameSaved])

  const openNewPlayerModal = () => {
    setEditingPlayerId(null)
    setPlayerName("")
    setPlayerDatabaseType("POSTGRESQL")
    setPlayerFormError("")
    setIsPlayerModalOpen(true)
  }

  const openEditPlayerModal = (player: WorkspacePlayer) => {
    setEditingPlayerId(player.id)
    setPlayerName(player.name)
    setPlayerDatabaseType(player.database_type)
    setPlayerFormError("")
    setIsPlayerModalOpen(true)
  }

  const closePlayerModal = () => {
    if (savingPlayer) return
    setIsPlayerModalOpen(false)
    setEditingPlayerId(null)
    setPlayerName("")
    setPlayerDatabaseType("POSTGRESQL")
    setPlayerFormError("")
  }

  const handleSavePlayer = async (event: React.FormEvent) => {
    event.preventDefault()
    const normalizedName = playerName.trim()
    if (normalizedName.length < 2) {
      setPlayerFormError("Informe um nome de sistema com pelo menos 2 caracteres.")
      return
    }

    setSavingPlayer(true)
    setPlayerFormError("")
    setPlayersError("")

    try {
      if (editingPlayerId) {
        await updateWorkspacePlayer(workspaceId, editingPlayerId, {
          name: normalizedName,
          database_type: playerDatabaseType,
        })
      } else {
        await createWorkspacePlayer(workspaceId, {
          name: normalizedName,
          database_type: playerDatabaseType,
        })
      }
      closePlayerModal()
      await loadPlayers()
    } catch (err) {
      setPlayerFormError(err instanceof Error ? err.message : "Falha ao salvar sistema.")
    } finally {
      setSavingPlayer(false)
    }
  }

  const handleOpenDeletePlayer = (player: WorkspacePlayer) => {
    setDeletePlayerId(player.id)
    setDeletePlayerName(player.name)
    setDeleteDialogOpen(true)
  }

  const handleConfirmDeletePlayer = async () => {
    if (!deletePlayerId) return
    setDeletingPlayer(true)
    setPlayersError("")
    try {
      await deleteWorkspacePlayer(workspaceId, deletePlayerId)
      setDeleteDialogOpen(false)
      setDeletePlayerId(null)
      setDeletePlayerName("")
      await loadPlayers()
      await refreshWorkspaces()
    } catch (err) {
      setPlayersError(err instanceof Error ? err.message : "Falha ao remover sistema.")
    } finally {
      setDeletingPlayer(false)
    }
  }

  return (
    <div className="flex flex-col space-y-4">
      <ConfirmDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        title="Remover sistema"
        description={
          deletePlayerName
            ? `Tem certeza que deseja remover o sistema "${deletePlayerName}" deste workspace?`
            : "Tem certeza que deseja remover este sistema deste workspace?"
        }
        confirmText="Remover"
        confirmVariant="destructive"
        loading={deletingPlayer}
        onConfirm={handleConfirmDeletePlayer}
      />

      <div className="flex items-center justify-between rounded-lg border border-border bg-card/50 p-2.5">
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.back()}
            className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted"
          >
            <ArrowLeft className="size-4" />
          </button>
          <div className="flex items-center gap-2">
            <div className="flex size-8 items-center justify-center rounded bg-primary/10">
              <Boxes className="size-4.5 text-primary" />
            </div>
            <h1 className="text-[15px] font-bold tracking-tight text-foreground">{workspaceName}</h1>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {saveError ? (
            <span className="rounded bg-destructive/10 px-2 py-1 text-[11px] font-semibold text-destructive">
              {saveError}
            </span>
          ) : null}
          <span className="px-2 py-1 text-[11px] font-medium text-muted-foreground">
            {autoSaving ? "Salvando..." : "Salvo automaticamente"}
          </span>
        </div>
      </div>

      <div className="grid gap-4">
        <section className="rounded-lg border border-border bg-card p-4.5 shadow-sm">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                Nome do Workspace
              </label>
              <input
                type="text"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Ex.: Construshow"
                className="h-9 w-full rounded-md border border-input bg-background/50 px-3 text-[13px] outline-none transition-all focus:ring-1 focus:ring-primary/20"
              />
            </div>

            <div>
              <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                Organizacao
              </label>
              <input
                type="text"
                value={organizationName}
                readOnly
                disabled
                className="h-9 w-full rounded-md border border-input bg-muted/30 px-3 text-[13px] text-foreground/80 outline-none"
              />
              <p className="mt-1 text-[10px] text-muted-foreground">Somente visualizacao apos cadastro.</p>
            </div>
          </div>
        </section>

        <div className="flex items-center gap-2 px-1">
          <div className="h-px flex-1 bg-border/50" />
          <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/60">
            Sistemas
          </span>
          <div className="h-px flex-1 bg-border/50" />
        </div>

        <section className="flex flex-col space-y-3">
          <div className="flex items-center justify-between px-1">
            <div className="flex items-center gap-2 text-muted-foreground">
              <Users className="size-4" />
              <span className="text-[13px] font-medium">{players.length} sistemas vinculados</span>
            </div>
            <button
              type="button"
              onClick={openNewPlayerModal}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-3 text-[13px] font-bold transition-all hover:bg-accent"
            >
              <Plus className="size-3.5" />
              Novo Sistema
            </button>
          </div>

          {playersError ? (
            <div className="rounded-md border border-destructive/20 bg-destructive/10 px-3 py-2 text-[13px] text-destructive">
              {playersError}
            </div>
          ) : null}

          {playersLoading ? (
            <div className="flex items-center justify-center rounded-lg border border-border bg-card py-10">
              <MorphLoader className="size-5 morph-muted" />
            </div>
          ) : players.length > 0 ? (
            <div className="overflow-auto rounded-lg border border-border bg-card shadow-sm">
              <div className="grid grid-cols-[1fr_180px_96px] items-center border-b border-border bg-muted/20 px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                <span>Nome do Sistema</span>
                <span className="text-center">Tipo de Banco</span>
                <span className="text-right">Acoes</span>
              </div>
              <div className="divide-y divide-border">
                {players.map((player) => (
                  <div
                    key={player.id}
                    className="grid grid-cols-[1fr_180px_96px] items-center px-4 py-2.5 transition-colors hover:bg-muted/10"
                  >
                    <p className="truncate text-[13px] font-semibold text-foreground">{player.name}</p>
                    <p className="text-center text-[11px] font-medium text-muted-foreground">
                      {databaseOptions.find((item) => item.value === player.database_type)?.label ?? player.database_type}
                    </p>
                    <div className="flex items-center justify-end gap-0.5">
                      <button
                        type="button"
                        onClick={() => openEditPlayerModal(player)}
                        className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                      >
                        <Edit2 className="size-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleOpenDeletePlayer(player)}
                        className="rounded p-2 text-destructive/60 transition-colors hover:bg-muted hover:text-destructive"
                      >
                        <Trash2 className="size-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-border bg-card/30 py-12">
              <div className="mb-3 flex size-11 items-center justify-center rounded-full bg-muted">
                <Users className="size-5.5 text-muted-foreground" />
              </div>
              <p className="text-[13px] font-semibold text-foreground">Nenhum sistema</p>
              <p className="mb-4 text-[11px] text-muted-foreground">
                Este workspace ainda nao possui sistemas.
              </p>
              <button
                type="button"
                onClick={openNewPlayerModal}
                className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-4 text-[13px] font-bold text-primary-foreground transition-all hover:opacity-90"
              >
                <Plus className="size-3.5" />
                Adicionar Primeiro
              </button>
            </div>
          )}

        </section>
      </div>

      {isPlayerModalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4 backdrop-blur-[2px]">
          <div className="w-full max-w-lg rounded-xl border border-border bg-card p-4.5 shadow-2xl">
            <div className="mb-5 flex items-start justify-between">
              <div className="flex items-center gap-2">
                <div className="flex size-7 items-center justify-center rounded bg-muted">
                  <Users className="size-4 text-muted-foreground" />
                </div>
                <h2 className="text-[13px] font-bold uppercase tracking-tight text-foreground">
                  {isEditingPlayer ? "Editar Sistema" : "Novo Sistema"}
                </h2>
              </div>
              <button
                type="button"
                onClick={closePlayerModal}
                disabled={savingPlayer}
                className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
              >
                <X className="size-3.5" />
              </button>
            </div>

            <form onSubmit={handleSavePlayer} className="space-y-4">
              <div>
                <label className="mb-1 block text-[10px] font-bold uppercase text-muted-foreground">
                  Nome do Sistema *
                </label>
                <input
                  type="text"
                  value={playerName}
                  onChange={(event) => setPlayerName(event.target.value)}
                  placeholder="Ex.: ERP Legado"
                  className="h-9 w-full rounded-md border border-input bg-background px-3 text-[13px] outline-none focus:ring-1 focus:ring-primary/20"
                  required
                />
              </div>

              <div>
                <label className="mb-1 block text-[10px] font-bold uppercase text-muted-foreground">
                  Tipo do Banco de Dados *
                </label>
                <Select
                  value={playerDatabaseType}
                  onValueChange={(value) => setPlayerDatabaseType(value as WorkspacePlayerDatabaseType)}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {databaseOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {playerFormError ? (
                <p className="rounded-md border border-destructive/20 bg-destructive/10 px-2.5 py-2 text-[11px] text-destructive">
                  {playerFormError}
                </p>
              ) : null}

              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={closePlayerModal}
                  disabled={savingPlayer}
                  className="inline-flex h-8 items-center justify-center rounded-md border border-border bg-card px-4 text-[13px] font-semibold text-foreground transition-colors hover:bg-accent disabled:opacity-50"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={savingPlayer}
                  className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md bg-primary px-4 text-[13px] font-bold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  {savingPlayer ? <MorphLoader className="size-3" /> : <Plus className="size-3" />}
                  {isEditingPlayer ? "Salvar" : "Cadastrar"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  )
}

export default function WorkspaceFormPage({ params }: PageProps) {
  const { id } = use(params)
  const router = useRouter()
  const { selectedOrgId, organizations, workspacesByOrg, loadWorkspacesForOrganization } = useDashboard()

  const workspace = useMemo(() => {
    if (selectedOrgId) {
      const selectedOrgWorkspace =
        (workspacesByOrg[selectedOrgId] ?? []).find((item) => item.id === id) ?? null
      if (selectedOrgWorkspace) return selectedOrgWorkspace
    }
    return Object.values(workspacesByOrg)
      .flat()
      .find((item) => item.id === id) ?? null
  }, [id, selectedOrgId, workspacesByOrg])

  const organizationName = useMemo(() => {
    if (!workspace) return "-"
    return organizations.find((org) => org.id === workspace.organization_id)?.name ?? workspace.organization_id
  }, [organizations, workspace])

  const loading = !workspace && Object.keys(workspacesByOrg).length === 0

  const handleWorkspaceNameSaved = useCallback(
    async (nextName: string) => {
      if (!workspace) return
      await updateWorkspace(workspace.id, { name: nextName })
      await loadWorkspacesForOrganization(workspace.organization_id, workspace.id)
    },
    [workspace, loadWorkspacesForOrganization]
  )

  const refreshWorkspaces = useCallback(async () => {
    if (!workspace) return
    await loadWorkspacesForOrganization(workspace.organization_id, workspace.id)
  }, [workspace, loadWorkspacesForOrganization])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <MorphLoader className="size-6 morph-muted" />
      </div>
    )
  }

  if (!workspace) {
    return (
      <div className="rounded-lg border border-border bg-card p-5">
        <p className="text-sm font-semibold text-foreground">Workspace nao encontrado</p>
        <p className="mt-1 text-xs text-muted-foreground">
          O workspace selecionado nao esta disponivel na organizacao atual.
        </p>
        <button
          type="button"
          onClick={() => router.push("/home")}
          className="mt-4 inline-flex h-8 items-center justify-center rounded-md border border-border bg-background px-3 text-xs font-semibold hover:bg-accent"
        >
          Voltar
        </button>
      </div>
    )
  }

  return (
    <WorkspaceEditor
      key={workspace.id}
      workspaceId={workspace.id}
      organizationId={workspace.organization_id}
      workspaceName={workspace.name}
      organizationName={organizationName}
      onWorkspaceNameSaved={handleWorkspaceNameSaved}
      refreshWorkspaces={refreshWorkspaces}
    />
  )
}
