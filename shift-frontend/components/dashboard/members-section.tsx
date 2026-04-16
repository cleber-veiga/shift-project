"use client"

import { useCallback, useEffect, useState } from "react"
import {
  Clock,
  Loader2,
  MailPlus,
  MoreHorizontal,
  RefreshCw,
  Search,
  Shield,
  Trash2,
  UserPlus,
  Users,
  X,
} from "lucide-react"
import { useDashboard } from "@/lib/context/dashboard-context"
import { useToast } from "@/lib/context/toast-context"
import {
  type DashboardScope,
} from "@/lib/dashboard-navigation"
import {
  type Invitation,
  type Member,
  cancelInvitation,
  createProjectInvitation,
  createWorkspaceInvitation,
  listProjectInvitations,
  listProjectMembers,
  listWorkspaceInvitations,
  listWorkspaceMembers,
  removeProjectMember,
  removeWorkspaceMember,
  resendInvitation,
  updateProjectMemberRole,
  updateWorkspaceMemberRole,
} from "@/lib/auth"
import { hasWorkspacePermission } from "@/lib/permissions"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { InviteMemberModal } from "@/components/dashboard/invite-member-modal"

type RoleOption = { value: string; label: string }

const WS_ROLES: RoleOption[] = [
  { value: "VIEWER", label: "Visualizador" },
  { value: "CONSULTANT", label: "Consultor" },
  { value: "MANAGER", label: "Gerente" },
]

const PROJ_ROLES: RoleOption[] = [
  { value: "CLIENT", label: "Cliente" },
  { value: "EDITOR", label: "Editor" },
]

const ROLE_LABELS: Record<string, string> = {
  OWNER: "Dono",
  MANAGER: "Gerente",
  MEMBER: "Membro",
  GUEST: "Convidado",
  CONSULTANT: "Consultor",
  VIEWER: "Visualizador",
  EDITOR: "Editor",
  CLIENT: "Cliente",
}

const STATUS_LABELS: Record<string, string> = {
  PENDING: "Pendente",
  ACCEPTED: "Aceito",
  CANCELLED: "Cancelado",
  EXPIRED: "Expirado",
}

function RoleBadge({ role }: { role: string }) {
  const colors: Record<string, string> = {
    OWNER: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
    MANAGER: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
    CONSULTANT: "bg-purple-500/10 text-purple-600 dark:text-purple-400",
    EDITOR: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
    VIEWER: "bg-muted text-muted-foreground",
    MEMBER: "bg-muted text-muted-foreground",
    GUEST: "bg-muted text-muted-foreground",
    CLIENT: "bg-muted text-muted-foreground",
  }
  return (
    <span className={`inline-flex rounded px-2 py-0.5 text-[10px] font-medium uppercase ${colors[role] ?? "bg-muted text-muted-foreground"}`}>
      {ROLE_LABELS[role] ?? role}
    </span>
  )
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    PENDING: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
    ACCEPTED: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
    CANCELLED: "bg-muted text-muted-foreground",
    EXPIRED: "bg-red-500/10 text-red-600 dark:text-red-400",
  }
  return (
    <span className={`inline-flex rounded px-2 py-0.5 text-[10px] font-medium uppercase ${colors[status] ?? "bg-muted text-muted-foreground"}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  )
}

function formatDate(iso: string) {
  try {
    return new Intl.DateTimeFormat("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    }).format(new Date(iso))
  } catch {
    return iso
  }
}

interface MembersSectionProps {
  scope: DashboardScope
}

export function MembersSection({ scope }: MembersSectionProps) {
  const { selectedWorkspace, selectedProject } = useDashboard()
  const toast = useToast()
  const wsRole = selectedWorkspace?.my_role ?? null
  const canManageMembers = scope === "space" ? hasWorkspacePermission(wsRole, "MANAGER") : true

  const [members, setMembers] = useState<Member[]>([])
  const [invitations, setInvitations] = useState<Invitation[]>([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState("")
  const [showInviteModal, setShowInviteModal] = useState(false)

  // Role change
  const [editingRole, setEditingRole] = useState<{ userId: string; role: string } | null>(null)
  const [savingRole, setSavingRole] = useState(false)

  // Delete member
  const [deleteTarget, setDeleteTarget] = useState<Member | null>(null)
  const [deleting, setDeleting] = useState(false)

  // Invitation actions
  const [actionInvId, setActionInvId] = useState<string | null>(null)

  const scopeId = scope === "space" ? selectedWorkspace?.id : selectedProject?.id
  const roles = scope === "space" ? WS_ROLES : PROJ_ROLES

  const loadData = useCallback(async () => {
    if (!scopeId) return
    setLoading(true)
    try {
      const [m, i] = await Promise.all(
        scope === "space"
          ? [listWorkspaceMembers(scopeId), listWorkspaceInvitations(scopeId)]
          : [listProjectMembers(scopeId), listProjectInvitations(scopeId)],
      )
      setMembers(m)
      setInvitations(i)
    } catch {
      toast.error("Erro", "Falha ao carregar membros.")
    } finally {
      setLoading(false)
    }
  }, [scopeId, scope, toast])

  useEffect(() => { loadData() }, [loadData])

  const handleInvite = async (email: string, role: string) => {
    if (!scopeId) return
    if (scope === "space") {
      await createWorkspaceInvitation(scopeId, { email, role })
    } else {
      await createProjectInvitation(scopeId, { email, role })
    }
    toast.success("Convite enviado", `Convite enviado para ${email}.`)
    await loadData()
  }

  const handleRoleChange = async (userId: string, newRole: string) => {
    if (!scopeId) return
    setSavingRole(true)
    try {
      if (scope === "space") {
        await updateWorkspaceMemberRole(scopeId, userId, newRole)
      } else {
        await updateProjectMemberRole(scopeId, userId, newRole)
      }
      toast.success("Papel alterado", "Papel do membro atualizado com sucesso.")
      setEditingRole(null)
      await loadData()
    } catch (err) {
      toast.error("Erro", err instanceof Error ? err.message : "Falha ao alterar papel.")
    } finally {
      setSavingRole(false)
    }
  }

  const handleRemoveMember = async () => {
    if (!scopeId || !deleteTarget) return
    setDeleting(true)
    try {
      if (scope === "space") {
        await removeWorkspaceMember(scopeId, deleteTarget.user_id)
      } else {
        await removeProjectMember(scopeId, deleteTarget.user_id)
      }
      toast.success("Membro removido", `${deleteTarget.email} foi removido.`)
      setDeleteTarget(null)
      await loadData()
    } catch (err) {
      toast.error("Erro", err instanceof Error ? err.message : "Falha ao remover membro.")
    } finally {
      setDeleting(false)
    }
  }

  const handleCancelInvitation = async (invId: string) => {
    setActionInvId(invId)
    try {
      await cancelInvitation(invId)
      toast.success("Convite cancelado", "O convite foi cancelado.")
      await loadData()
    } catch (err) {
      toast.error("Erro", err instanceof Error ? err.message : "Falha ao cancelar.")
    } finally {
      setActionInvId(null)
    }
  }

  const handleResendInvitation = async (invId: string) => {
    setActionInvId(invId)
    try {
      await resendInvitation(invId)
      toast.success("Convite reenviado", "O convite foi reenviado por email.")
      await loadData()
    } catch (err) {
      toast.error("Erro", err instanceof Error ? err.message : "Falha ao reenviar.")
    } finally {
      setActionInvId(null)
    }
  }

  const filteredMembers = members.filter(
    (m) =>
      !searchTerm ||
      m.email.toLowerCase().includes(searchTerm.toLowerCase()),
  )

  const pendingInvitations = invitations.filter((i) => i.status === "PENDING")

  if (!scopeId) {
    return (
      <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-border bg-card">
        <p className="text-sm text-muted-foreground">
          {scope === "space"
            ? "Selecione um workspace para gerenciar membros."
            : "Selecione um projeto para gerenciar membros."}
        </p>
      </div>
    )
  }

  return (
    <>
      <InviteMemberModal
        open={showInviteModal}
        onClose={() => setShowInviteModal(false)}
        onInvite={handleInvite}
        scope={scope}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title="Remover Membro"
        description={`Tem certeza que deseja remover "${deleteTarget?.email}" deste ${scope === "space" ? "workspace" : "projeto"}?`}
        confirmText="Remover"
        confirmVariant="destructive"
        loading={deleting}
        onConfirm={handleRemoveMember}
      />

      <section className="space-y-4">
        {/* Toolbar */}
        <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <Users className="size-4 text-muted-foreground" />
            <span className="text-sm font-medium text-foreground">
              {members.length} {members.length === 1 ? "membro" : "membros"}
            </span>
            {pendingInvitations.length > 0 ? (
              <span className="text-xs text-muted-foreground">
                + {pendingInvitations.length} pendente{pendingInvitations.length > 1 ? "s" : ""}
              </span>
            ) : null}
          </div>

          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <label className="flex h-9 w-full items-center gap-2 rounded-md border border-input bg-background px-3 sm:w-[220px]">
              <Search className="size-4 text-muted-foreground" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Buscar..."
                className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
              />
            </label>
            {canManageMembers ? (
              <button
                type="button"
                onClick={() => setShowInviteModal(true)}
                className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md bg-foreground px-3.5 text-sm font-semibold text-background transition-opacity hover:opacity-90"
              >
                <UserPlus className="size-4" />
                Convidar
              </button>
            ) : null}
          </div>
        </div>

        {loading ? (
          <div className="flex h-32 items-center justify-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Carregando membros...
          </div>
        ) : (
          <div className="space-y-4">
            {/* Active members */}
            <div className="overflow-auto rounded-xl border border-border bg-card shadow-sm">
              <div className="border-b border-border px-4 py-3">
                <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  Membros Ativos
                </h3>
              </div>

              {filteredMembers.length === 0 ? (
                <div className="px-4 py-6 text-center text-sm text-muted-foreground">
                  {searchTerm ? "Nenhum membro encontrado." : "Nenhum membro ainda."}
                </div>
              ) : (
                <div className="divide-y divide-border">
                  {filteredMembers.map((member) => (
                    <div
                      key={member.user_id}
                      className="flex items-center justify-between px-4 py-3 transition-colors hover:bg-muted/10"
                    >
                      <div className="flex items-center gap-3">
                        <div className="flex size-8 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
                          {member.email[0].toUpperCase()}
                        </div>
                        <div>
                          <p className="text-sm font-medium text-foreground">{member.email}</p>
                          <p className="text-[11px] text-muted-foreground">
                            Desde {formatDate(member.created_at)}
                          </p>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        {editingRole?.userId === member.user_id ? (
                          <div className="flex items-center gap-2">
                            <Select
                              value={editingRole.role}
                              onValueChange={(val) =>
                                setEditingRole({ ...editingRole, role: val })
                              }
                            >
                              <SelectTrigger className="h-8 w-[140px] bg-background text-xs">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {roles.map((r) => (
                                  <SelectItem key={r.value} value={r.value}>
                                    {r.label}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                            <button
                              type="button"
                              disabled={savingRole}
                              onClick={() =>
                                handleRoleChange(member.user_id, editingRole.role)
                              }
                              className="rounded p-1.5 text-emerald-500 transition-colors hover:bg-emerald-500/10 disabled:opacity-50"
                            >
                              {savingRole ? (
                                <Loader2 className="size-3.5 animate-spin" />
                              ) : (
                                <Shield className="size-3.5" />
                              )}
                            </button>
                            <button
                              type="button"
                              onClick={() => setEditingRole(null)}
                              className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-muted"
                            >
                              <X className="size-3.5" />
                            </button>
                          </div>
                        ) : (
                          <>
                            <RoleBadge role={member.role} />
                            {canManageMembers ? (
                              <>
                                <button
                                  type="button"
                                  onClick={() =>
                                    setEditingRole({
                                      userId: member.user_id,
                                      role: member.role,
                                    })
                                  }
                                  className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                                  title="Alterar papel"
                                >
                                  <Shield className="size-3.5" />
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setDeleteTarget(member)}
                                  className="rounded p-1.5 text-destructive/70 transition-colors hover:bg-muted hover:text-destructive"
                                  title="Remover membro"
                                >
                                  <Trash2 className="size-3.5" />
                                </button>
                              </>
                            ) : null}
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Pending invitations */}
            {pendingInvitations.length > 0 ? (
              <div className="overflow-auto rounded-xl border border-border bg-card shadow-sm">
                <div className="border-b border-border px-4 py-3">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                    Convites Pendentes
                  </h3>
                </div>

                <div className="divide-y divide-border">
                  {pendingInvitations.map((inv) => (
                    <div
                      key={inv.id}
                      className="flex items-center justify-between px-4 py-3 transition-colors hover:bg-muted/10"
                    >
                      <div className="flex items-center gap-3">
                        <div className="flex size-8 items-center justify-center rounded-full bg-amber-500/10">
                          <MailPlus className="size-4 text-amber-500" />
                        </div>
                        <div>
                          <p className="text-sm font-medium text-foreground">{inv.email}</p>
                          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                            <span>Enviado em {formatDate(inv.created_at)}</span>
                            <span className="text-border">|</span>
                            <Clock className="inline size-3" />
                            <span>Expira em {formatDate(inv.expires_at)}</span>
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        <RoleBadge role={inv.role} />
                        <StatusBadge status={inv.status} />

                        {canManageMembers ? (
                          <>
                            <button
                              type="button"
                              disabled={actionInvId === inv.id}
                              onClick={() => handleResendInvitation(inv.id)}
                              className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
                              title="Reenviar convite"
                            >
                              {actionInvId === inv.id ? (
                                <Loader2 className="size-3.5 animate-spin" />
                              ) : (
                                <RefreshCw className="size-3.5" />
                              )}
                            </button>
                            <button
                              type="button"
                              disabled={actionInvId === inv.id}
                              onClick={() => handleCancelInvitation(inv.id)}
                              className="rounded p-1.5 text-destructive/70 transition-colors hover:bg-muted hover:text-destructive disabled:opacity-50"
                              title="Cancelar convite"
                            >
                              <Trash2 className="size-3.5" />
                            </button>
                          </>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        )}
      </section>
    </>
  )
}
