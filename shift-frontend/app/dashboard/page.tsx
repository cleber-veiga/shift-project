"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useToast } from "@/lib/context/toast-context"
import { useRouter } from "next/navigation"
import {
  ArrowRight,
  Building2,
  LogOut,
  Plus,
  X,
} from "lucide-react"
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
import { cn } from "@/lib/utils"
import { MorphLoader } from "@/components/ui/morph-loader"

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

  const canCreateOrg = useMemo(() => {
    return orgName.trim().length >= 2
  }, [orgName])

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

      if (currentId && orgsWithRoles.some((organization) => organization.id === currentId)) {
        return currentId
      }

      if (storedOrganizationId && orgsWithRoles.some((organization) => organization.id === storedOrganizationId)) {
        return storedOrganizationId
      }

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
        setError(err instanceof Error ? err.message : "Falha ao carregar organizacoes.")
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

    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && !isCreatingOrg) {
        setIsCreateModalOpen(false)
      }
    }

    window.addEventListener("keydown", handleEscape)
    return () => window.removeEventListener("keydown", handleEscape)
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
      const createdOrganization = await createOrganization({ name: orgName.trim() })

      setOrgName("")
      setSelectedOrganizationId(createdOrganization.id)
      setIsCreateModalOpen(false)
      await loadOrganizations()
      toast.success("Organização criada", `"${createdOrganization.name}" foi cadastrada com sucesso.`)
    } catch (err) {
      toast.error("Erro ao criar organização", err instanceof Error ? err.message : "Falha ao criar organização.")
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
        setError("Esta organizacao ainda nao possui workspace. Crie um para continuar.")
        return
      }

      persistSelectedOrganizationId(organization.id)
      setSelectedWorkspaceId(workspaces[0].id)
      router.push("/home")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar workspaces da organizacao.")
    } finally {
      setIsRoutingHome(false)
    }
  }

  return (
    <>
      <main className="dark auth-shell min-h-screen" style={{ colorScheme: "dark" }}>
        <div className="auth-grid pointer-events-none absolute inset-0 opacity-30" />

        <div className="relative mx-auto flex min-h-screen w-full max-w-3xl items-center px-4 py-8 sm:px-6">
          <section className="w-full rounded-3xl border border-border/70 bg-[linear-gradient(160deg,rgba(16,16,16,0.96),rgba(10,10,10,0.94))] p-4 shadow-[0_35px_90px_rgba(0,0,0,0.55)] backdrop-blur sm:p-5">
            <div className="mb-6 text-center">
              <h1 className="text-3xl font-bold tracking-tight text-foreground sm:text-4xl">
                Bem-vindo de volta!
              </h1>
              <p className="mt-2 text-sm text-muted-foreground">
                Selecione uma organizacao para acessar o painel.
              </p>
            </div>

            <div className="rounded-2xl border border-border/70 bg-background/45 p-3.5 sm:p-4">
              <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border/60 pb-4">
                <div className="flex items-center gap-3">
                  <span className="inline-flex size-8 items-center justify-center rounded-xl border border-border/70 bg-muted/45 text-foreground">
                    <Building2 className="size-3.5" />
                  </span>
                  <div>
                    <p className="text-base font-semibold leading-none text-foreground">
                      Minhas Organizacoes
                    </p>
                    <p className="mt-1 text-[10px] text-muted-foreground">
                      {organizations.length > 0
                        ? `${organizations.length} organizacao${organizations.length > 1 ? "oes" : ""}`
                        : "Nenhuma organizacao"}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={openCreateModal}
                    disabled={isRoutingHome}
                    className="inline-flex h-8 items-center gap-1.5 rounded-xl border border-white/20 bg-primary px-3 text-xs font-bold text-primary-foreground shadow-[0_0_15px_rgba(255,255,255,0.12)] transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <Plus className="size-3" />
                    Nova
                  </button>
                  <button
                    type="button"
                    onClick={handleLogout}
                    disabled={isLoggingOut || isRoutingHome}
                    className="inline-flex h-8 items-center gap-1.5 rounded-xl border border-border/80 bg-card/70 px-3 text-xs font-medium text-foreground transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {isLoggingOut ? (
                      <MorphLoader className="size-3" />
                    ) : (
                      <LogOut className="size-3" />
                    )}
                    Sair
                  </button>
                </div>
              </div>

              <div className="mt-4">
                {state === "loading" ? (
                  <div className="rounded-xl border border-border/70 bg-background/50 px-3 py-2 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-2">
                      <MorphLoader className="size-3.5 morph-muted" />
                      Carregando organizacoes...
                    </span>
                  </div>
                ) : null}

                {isRoutingHome ? (
                  <div className="mb-2 rounded-xl border border-border/70 bg-background/50 px-3 py-2 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-2">
                      <MorphLoader className="size-3.5 morph-muted" />
                      Abrindo workspace...
                    </span>
                  </div>
                ) : null}

                {state === "error" ? (
                  <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                    {error}
                  </div>
                ) : null}

                {state === "ready" && organizations.length > 0 ? (
                  <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                    {organizations.map((organization) => {
                      const isSelected = organization.id === selectedOrganizationId

                      return (
                        <button
                          key={organization.id}
                          type="button"
                          onClick={() => handleSelectOrganization(organization)}
                          disabled={isRoutingHome}
                          className={cn(
                            "group flex w-full flex-col justify-between gap-3 rounded-2xl border px-3.5 py-3 text-left transition-all duration-300 hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0",
                            isSelected
                              ? "border-foreground/40 bg-foreground/10 shadow-[0_0_20px_rgba(255,255,255,0.06)]"
                              : "border-border/60 bg-background/20 hover:border-foreground/20 hover:bg-background/40 hover:shadow-[0_8px_30px_rgba(0,0,0,0.4)]"
                          )}
                        >
                          <div className="flex items-start justify-between">
                            <div className="min-w-0 flex-1">
                              <p className="truncate text-sm font-bold text-foreground">
                                {organization.name}
                              </p>
                              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                                <span className="rounded-md bg-muted/80 px-1.5 py-0.5 text-[9px] font-bold tracking-tight text-foreground uppercase">
                                  {getRoleLabel(organization.role)}
                                </span>
                              </div>
                            </div>
                            <span className={cn(
                              "flex size-7 shrink-0 items-center justify-center rounded-full border transition-all duration-200",
                              isSelected 
                                ? "border-foreground/30 bg-foreground/10 text-foreground" 
                                : "border-border/60 bg-muted/30 text-muted-foreground group-hover:border-border group-hover:bg-muted/50"
                            )}>
                              <ArrowRight className="size-3.5" />
                            </span>
                          </div>

                        </button>
                      )
                    })}
                  </div>
                ) : null}

                {state === "ready" && organizations.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-border bg-background/45 px-4 py-6 text-center">
                    <p className="mb-3 text-sm text-muted-foreground">
                      Nenhuma organização encontrada.
                    </p>
                    <button
                      type="button"
                      onClick={() => router.push("/onboarding")}
                      className="inline-flex h-8 items-center gap-1.5 rounded-xl border border-white/20 bg-primary px-3 text-xs font-bold text-primary-foreground shadow-[0_0_15px_rgba(255,255,255,0.12)] transition hover:opacity-90"
                    >
                      <Plus className="size-3" /> Configurar agora
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
          </section>
        </div>
      </main>

      {isCreateModalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-6 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-[1.25rem] border border-border bg-card p-4 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">
                  Nova organizacao
                </p>
                <h2 className="mt-0.5 text-base font-bold text-foreground">Criar workspace</h2>
              </div>
              <button
                type="button"
                onClick={closeCreateModal}
                disabled={isCreatingOrg}
                className="inline-flex size-7 items-center justify-center rounded-full border border-border text-muted-foreground transition hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
                aria-label="Fechar modal"
              >
                <X className="size-3" />
              </button>
            </div>

            <form onSubmit={handleCreateOrganization} className="mt-4 space-y-3">
              <div>
                <label className="mb-1 block text-[10px] font-semibold text-foreground uppercase tracking-wider">
                  Nome da organizacao
                </label>
                <input
                  type="text"
                  value={orgName}
                  onChange={(event) => setOrgName(event.target.value)}
                  placeholder="Ex: Minha Empresa"
                  className="h-9 w-full rounded-xl border border-input bg-background/70 px-3 text-sm text-foreground placeholder:text-muted-foreground outline-none transition focus:border-ring focus:ring-2 focus:ring-ring/20"
                  minLength={2}
                  required
                />
              </div>


              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={closeCreateModal}
                  disabled={isCreatingOrg}
                  className="inline-flex h-8 items-center justify-center rounded-xl border border-border bg-card px-4 text-xs font-medium text-foreground transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={isCreatingOrg || !canCreateOrg}
                  className="inline-flex h-8 items-center justify-center gap-2 rounded-xl bg-primary px-4 text-xs font-bold text-primary-foreground transition hover:opacity-90 shadow-[0_0_15px_rgba(255,255,255,0.1)] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isCreatingOrg ? <MorphLoader className="size-3" /> : <Plus className="size-3" />}
                  Criar workspace
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </>
  )
}
