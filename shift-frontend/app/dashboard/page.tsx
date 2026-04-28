"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { Building2, LogOut, Plus, X } from "lucide-react"
import { useToast } from "@/lib/context/toast-context"
import {
  createOrganization,
  getSelectedOrganizationId,
  getValidSession,
  listOrganizations,
  listOrganizationWorkspaces,
  logout,
  setSelectedOrganizationId as persistSelectedOrganizationId,
  setSelectedWorkspaceId,
  type Organization,
  type OrganizationRole,
} from "@/lib/auth"
import { MorphLoader } from "@/components/ui/morph-loader"
import {
  ArrowRight,
  AUTH_TOKENS,
  AuthShell,
  PaperCard,
  PaperField,
  PrimaryCta,
} from "@/components/auth/auth-shell"

const { ACCENT, BORDER_PAPER, INK, PAPER_INSET } = AUTH_TOKENS

type LoadState = "loading" | "ready" | "error"

type OrganizationWithRole = Organization & {
  role: OrganizationRole | "MEMBER"
}

function getRoleLabel(role: OrganizationWithRole["role"]) {
  switch (role) {
    case "OWNER":
      return "Dono"
    case "MANAGER":
      return "Gerente"
    case "GUEST":
      return "Convidado"
    default:
      return "Membro"
  }
}

export default function DashboardPage() {
  const router = useRouter()
  const toast = useToast()
  const [state, setState] = useState<LoadState>("loading")
  const [error, setError] = useState("")
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [isRoutingHome, setIsRoutingHome] = useState(false)
  const [organizations, setOrganizations] = useState<OrganizationWithRole[]>([])
  const [selectedOrganizationId, setSelectedOrganizationId] = useState<string | null>(null)

  const [orgName, setOrgName] = useState("")
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false)
  const [isCreatingOrg, setIsCreatingOrg] = useState(false)

  const canCreateOrg = useMemo(() => orgName.trim().length >= 2, [orgName])

  const loadOrganizations = useCallback(async () => {
    const session = await getValidSession()
    if (!session) {
      router.replace("/login")
      return
    }

    const orgs = await listOrganizations()
    const orgsWithRoles = orgs.map((org) => ({
      ...org,
      role: (org.my_role ?? "MEMBER") as OrganizationRole | "MEMBER",
    } satisfies OrganizationWithRole))

    setOrganizations(orgsWithRoles)
    setSelectedOrganizationId((currentId) => {
      const storedOrganizationId = getSelectedOrganizationId()
      if (currentId && orgsWithRoles.some((o) => o.id === currentId)) return currentId
      if (storedOrganizationId && orgsWithRoles.some((o) => o.id === storedOrganizationId))
        return storedOrganizationId
      return orgsWithRoles[0]?.id ?? null
    })
  }, [router])

  useEffect(() => {
    let active = true
    async function load() {
      try {
        await loadOrganizations()
        if (!active) return
        setState("ready")
      } catch (err) {
        if (!active) return
        setError(err instanceof Error ? err.message : "Falha ao carregar organizações.")
        setState("error")
      }
    }
    load()
    return () => {
      active = false
    }
  }, [loadOrganizations])

  useEffect(() => {
    if (!isCreateModalOpen) return
    function onKeydown(event: KeyboardEvent) {
      if (event.key === "Escape" && !isCreatingOrg) setIsCreateModalOpen(false)
    }
    window.addEventListener("keydown", onKeydown)
    return () => window.removeEventListener("keydown", onKeydown)
  }, [isCreateModalOpen, isCreatingOrg])

  useEffect(() => {
    if (!isCreateModalOpen) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [isCreateModalOpen])

  function openCreateModal() {
    setIsCreateModalOpen(true)
  }

  function closeCreateModal() {
    if (isCreatingOrg) return
    setIsCreateModalOpen(false)
  }

  async function handleLogout() {
    setIsLoggingOut(true)
    await logout()
    router.replace("/login")
  }

  async function handleCreateOrganization(event: React.FormEvent) {
    event.preventDefault()
    if (!canCreateOrg) return

    setIsCreatingOrg(true)
    try {
      const created = await createOrganization({ name: orgName.trim() })
      setOrgName("")
      setSelectedOrganizationId(created.id)
      setIsCreateModalOpen(false)
      await loadOrganizations()
      toast.success("Organização criada", `"${created.name}" foi cadastrada com sucesso.`)
    } catch (err) {
      toast.error(
        "Erro ao criar organização",
        err instanceof Error ? err.message : "Falha ao criar organização.",
      )
    } finally {
      setIsCreatingOrg(false)
    }
  }

  async function handleSelectOrganization(organization: OrganizationWithRole) {
    setSelectedOrganizationId(organization.id)
    setIsRoutingHome(true)
    setError("")
    try {
      const workspaces = await listOrganizationWorkspaces(organization.id)
      if (workspaces.length === 0) {
        setError("Esta organização ainda não possui workspace. Crie um para continuar.")
        return
      }
      persistSelectedOrganizationId(organization.id)
      setSelectedWorkspaceId(workspaces[0].id)
      router.push("/home")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar workspaces da organização.")
    } finally {
      setIsRoutingHome(false)
    }
  }

  return (
    <AuthShell
      heroEyebrow="Bem-vindo de volta"
      heroTitle={
        <>
          Selecione sua{" "}
          <em style={{ fontStyle: "italic", fontWeight: 500, color: ACCENT }}>organização</em>.
        </>
      }
      heroBody="Cada organização tem seus próprios workspaces, conexões e fluxos de ETL. Escolha onde você quer continuar agora."
    >
      <PaperCard
        eyebrow={
          organizations.length > 0
            ? `${organizations.length} ${organizations.length === 1 ? "organização" : "organizações"}`
            : "Nenhuma organização"
        }
      >
        {state === "loading" ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: 16,
              fontSize: 14,
              color: "#6b7280",
            }}
          >
            <MorphLoader className="size-4" /> Carregando organizações...
          </div>
        ) : null}

        {state === "error" ? (
          <p
            style={{
              margin: 0,
              padding: 12,
              borderRadius: 8,
              background: "rgba(239,68,68,0.06)",
              border: "1px solid rgba(239,68,68,0.18)",
              fontSize: 13,
              color: "#dc2626",
            }}
          >
            {error}
          </p>
        ) : null}

        {state === "ready" && organizations.length > 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {organizations.map((organization) => {
              const isSelected = organization.id === selectedOrganizationId
              return (
                <button
                  key={organization.id}
                  type="button"
                  onClick={() => handleSelectOrganization(organization)}
                  disabled={isRoutingHome}
                  style={{
                    width: "100%",
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "12px 14px",
                    background: PAPER_INSET,
                    border: `1px solid ${isSelected ? ACCENT : "transparent"}`,
                    borderRadius: 8,
                    cursor: isRoutingHome ? "not-allowed" : "pointer",
                    opacity: isRoutingHome ? 0.6 : 1,
                    textAlign: "left",
                    fontFamily: "inherit",
                  }}
                >
                  <span
                    style={{
                      width: 32,
                      height: 32,
                      borderRadius: 8,
                      background: "white",
                      border: `1px solid ${BORDER_PAPER}`,
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flex: "0 0 auto",
                      color: "#4b5563",
                    }}
                  >
                    <Building2 className="size-4" />
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p
                      style={{
                        margin: 0,
                        fontSize: 14,
                        fontWeight: 600,
                        color: INK,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {organization.name}
                    </p>
                    <span
                      style={{
                        marginTop: 2,
                        display: "inline-flex",
                        alignItems: "center",
                        padding: "1px 6px",
                        borderRadius: 999,
                        background: "rgba(99,102,241,0.12)",
                        color: ACCENT,
                        fontSize: 10,
                        fontWeight: 600,
                        letterSpacing: "0.04em",
                        textTransform: "uppercase",
                      }}
                    >
                      {getRoleLabel(organization.role)}
                    </span>
                  </div>
                  <span style={{ color: "#9ca3af", display: "inline-flex" }}>
                    {isRoutingHome && isSelected ? (
                      <MorphLoader className="size-4" />
                    ) : (
                      <ArrowRight />
                    )}
                  </span>
                </button>
              )
            })}
          </div>
        ) : null}

        {state === "ready" && organizations.length === 0 ? (
          <div
            style={{
              padding: 24,
              borderRadius: 8,
              background: PAPER_INSET,
              textAlign: "center",
              fontSize: 13,
              color: "#6b7280",
            }}
          >
            Nenhuma organização encontrada.
            <button
              type="button"
              onClick={() => router.push("/onboarding")}
              style={{
                display: "block",
                margin: "12px auto 0",
                background: "none",
                border: "none",
                color: ACCENT,
                fontWeight: 600,
                fontSize: 13,
                cursor: "pointer",
                fontFamily: "inherit",
              }}
            >
              Configurar agora →
            </button>
          </div>
        ) : null}

        <div
          style={{
            marginTop: 24,
            paddingTop: 20,
            borderTop: `1px solid ${BORDER_PAPER}`,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 12,
          }}
        >
          <button
            type="button"
            onClick={openCreateModal}
            disabled={isRoutingHome}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              background: "none",
              border: "none",
              color: ACCENT,
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              padding: 0,
              fontFamily: "inherit",
            }}
          >
            <Plus className="size-4" /> Nova organização
          </button>

          <button
            type="button"
            onClick={handleLogout}
            disabled={isLoggingOut || isRoutingHome}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              background: "none",
              border: "none",
              color: "#6b7280",
              fontSize: 13,
              fontWeight: 500,
              cursor: "pointer",
              padding: 0,
              fontFamily: "inherit",
            }}
          >
            {isLoggingOut ? <MorphLoader className="size-3.5" /> : <LogOut className="size-3.5" />}
            Sair
          </button>
        </div>
      </PaperCard>

      {isCreateModalOpen ? (
        <CreateOrgModal
          orgName={orgName}
          setOrgName={setOrgName}
          isCreating={isCreatingOrg}
          canSubmit={canCreateOrg}
          onClose={closeCreateModal}
          onSubmit={handleCreateOrganization}
        />
      ) : null}
    </AuthShell>
  )
}

function CreateOrgModal({
  orgName,
  setOrgName,
  isCreating,
  canSubmit,
  onClose,
  onSubmit,
}: {
  orgName: string
  setOrgName: (value: string) => void
  isCreating: boolean
  canSubmit: boolean
  onClose: () => void
  onSubmit: (event: React.FormEvent) => Promise<void>
}) {
  return (
    <div
      role="presentation"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 50,
        background: "rgba(14,18,32,0.4)",
        backdropFilter: "blur(2px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Criar organização"
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "min(480px, 96vw)",
          background: AUTH_TOKENS.PAPER,
          borderRadius: 12,
          padding: 32,
          boxShadow:
            "0 1px 0 rgba(14,18,32,0.04), 0 24px 48px -16px rgba(14,18,32,0.18), 0 2px 6px rgba(14,18,32,0.04)",
          color: INK,
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            paddingBottom: 16,
            marginBottom: 20,
            borderBottom: `1px solid ${BORDER_PAPER}`,
          }}
        >
          <div>
            <p
              style={{
                margin: 0,
                fontSize: 11,
                fontFamily: AUTH_TOKENS.monoFamily,
                color: "#6b7280",
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                fontWeight: 500,
              }}
            >
              Nova organização
            </p>
            <p style={{ margin: "4px 0 0", fontSize: 16, fontWeight: 600 }}>Cadastrar organização</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isCreating}
            aria-label="Fechar"
            style={{
              width: 32,
              height: 32,
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              background: "transparent",
              border: "none",
              color: "#6b7280",
              cursor: isCreating ? "not-allowed" : "pointer",
              borderRadius: 6,
            }}
          >
            <X className="size-4" />
          </button>
        </div>

        <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <PaperField
            label="Nome da organização"
            placeholder="Ex: Minha Empresa"
            value={orgName}
            onChange={setOrgName}
            required
            minLength={2}
          />
          <div style={{ display: "flex", gap: 12, justifyContent: "flex-end" }}>
            <button
              type="button"
              onClick={onClose}
              disabled={isCreating}
              style={{
                height: 40,
                padding: "0 16px",
                background: "transparent",
                border: `1px solid ${BORDER_PAPER}`,
                borderRadius: 8,
                fontSize: 13,
                fontWeight: 500,
                color: "#4b5563",
                cursor: isCreating ? "not-allowed" : "pointer",
                fontFamily: "inherit",
              }}
            >
              Cancelar
            </button>
            <div style={{ width: 200 }}>
              <PrimaryCta type="submit" disabled={isCreating || !canSubmit}>
                {isCreating ? <MorphLoader className="size-4" /> : <>Criar <ArrowRight /></>}
              </PrimaryCta>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}
