"use client"

import React, { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { ArrowRight, Briefcase, Building2, CheckCircle2, FolderOpen, SkipForward } from "lucide-react"
import {
  createOrganization,
  createWorkspace,
  createWorkspaceProject,
  getValidSession,
  setSelectedOrganizationId,
  setSelectedWorkspaceId,
  setSelectedProjectId,
} from "@/lib/auth"
import { cn } from "@/lib/utils"
import { MorphLoader } from "@/components/ui/morph-loader"
import { ShiftBrand } from "@/components/ui/shift-brand"

type Step = "org" | "workspace" | "project" | "done"

const STEPS = [
  { key: "org" as const, label: "Organização" },
  { key: "workspace" as const, label: "Workspace" },
  { key: "projeto" as const, label: "Projeto" },
]

export default function OnboardingPage() {
  const router = useRouter()
  const [step, setStep] = useState<Step>("org")
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState("")

  const [orgName, setOrgName] = useState("")
  const [orgId, setOrgId] = useState("")

  const [workspaceName, setWorkspaceName] = useState("")
  const [erpId, setErpId] = useState("")
  const [workspaceId, setWorkspaceId] = useState("")

  const [projectName, setProjectName] = useState("")

  useEffect(() => {
    async function checkSession() {
      const session = await getValidSession()
      if (!session) router.replace("/login")
    }
    checkSession()
  }, [router])

  const currentIndex = STEPS.findIndex((s) => s.key === step || (step === "done" && s.key === "projeto"))

  async function handleCreateOrg(e: React.FormEvent) {
    e.preventDefault()
    if (orgName.trim().length < 2) return
    setIsLoading(true)
    setError("")
    try {
      const org = await createOrganization({ name: orgName.trim() })
      setOrgId(org.id)
      setSelectedOrganizationId(org.id)
      setStep("workspace")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao criar organização.")
    } finally {
      setIsLoading(false)
    }
  }

  async function handleCreateWorkspace(e: React.FormEvent) {
    e.preventDefault()
    if (!workspaceName.trim()) return
    setIsLoading(true)
    setError("")
    try {
      const ws = await createWorkspace({
        organization_id: orgId,
        name: workspaceName.trim(),
        erp_id: erpId.trim() || null,
      })
      setWorkspaceId(ws.id)
      setSelectedWorkspaceId(ws.id)
      setStep("project")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao criar workspace.")
    } finally {
      setIsLoading(false)
    }
  }

  async function handleCreateProject(e: React.FormEvent) {
    e.preventDefault()
    if (!projectName.trim()) return
    setIsLoading(true)
    setError("")
    try {
      const proj = await createWorkspaceProject(workspaceId, { name: projectName.trim() })
      setSelectedProjectId(proj.id)
      setStep("done")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao criar projeto.")
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-[#0a0a0a]">
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage: `
            linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)
          `,
          backgroundSize: "64px 64px",
        }}
      />
      <div className="pointer-events-none absolute left-1/2 top-0 h-[300px] w-[600px] -translate-x-1/2 rounded-full bg-white/[0.03] blur-3xl" />

      <div className="relative z-10 w-full max-w-md px-4">
        <div className="mb-8 flex justify-center">
          <ShiftBrand size={48} showWordmark={false} />
        </div>

        {step !== "done" ? (
          <>
            {/* Progress indicator */}
            <div className="mb-8 flex items-center">
              {STEPS.map((s, i) => (
                <React.Fragment key={s.key}>
                  <div className="flex flex-col items-center">
                    <div
                      className={cn(
                        "flex size-8 items-center justify-center rounded-full border text-xs font-bold transition-all",
                        i < currentIndex
                          ? "border-emerald-500 bg-emerald-500/20 text-emerald-400"
                          : i === currentIndex
                          ? "border-white bg-white text-neutral-900"
                          : "border-white/20 bg-white/5 text-neutral-600"
                      )}
                    >
                      {i < currentIndex ? "✓" : i + 1}
                    </div>
                    <span
                      className={cn(
                        "mt-1.5 text-[10px] font-medium",
                        i === currentIndex
                          ? "text-white"
                          : i < currentIndex
                          ? "text-emerald-400"
                          : "text-neutral-600"
                      )}
                    >
                      {s.label}
                    </span>
                  </div>
                  {i < STEPS.length - 1 ? (
                    <div
                      className={cn(
                        "mb-4 h-px flex-1 mx-2 transition-all",
                        i < currentIndex ? "bg-emerald-500/50" : "bg-white/10"
                      )}
                    />
                  ) : null}
                </React.Fragment>
              ))}
            </div>

            {/* Step 1: Organização */}
            {step === "org" ? (
              <div>
                <div className="mb-6 text-center">
                  <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-full border border-white/10 bg-white/5">
                    <Building2 className="size-5 text-neutral-300" />
                  </div>
                  <h1 className="text-xl font-semibold text-white">Configure sua organização</h1>
                  <p className="mt-2 text-sm text-neutral-500">
                    Uma organização agrupa seus workspaces e projetos.
                  </p>
                </div>
                <form onSubmit={handleCreateOrg} className="space-y-4">
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-neutral-400">
                      Nome da organização
                    </label>
                    <input
                      type="text"
                      value={orgName}
                      onChange={(e) => setOrgName(e.target.value)}
                      placeholder="Ex: Minha Empresa"
                      className="w-full rounded-lg border border-white/10 bg-white/5 px-3.5 py-2.5 text-sm text-white placeholder-neutral-600 outline-none transition-all focus:border-white/30 focus:ring-2 focus:ring-white/10"
                      required
                      minLength={2}
                    />
                  </div>
                  {error ? <p className="text-sm text-red-400">{error}</p> : null}
                  <button
                    type="submit"
                    disabled={isLoading || orgName.trim().length < 2}
                    className={cn(
                      "flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-all",
                      "bg-white text-neutral-900 hover:bg-neutral-100",
                      "disabled:cursor-not-allowed disabled:opacity-60"
                    )}
                  >
                    {isLoading ? (
                      <MorphLoader className="size-4" />
                    ) : (
                      <>Continuar <ArrowRight className="size-4" /></>
                    )}
                  </button>
                </form>
              </div>
            ) : null}

            {/* Step 2: Workspace */}
            {step === "workspace" ? (
              <div>
                <div className="mb-6 text-center">
                  <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-full border border-white/10 bg-white/5">
                    <Briefcase className="size-5 text-neutral-300" />
                  </div>
                  <h1 className="text-xl font-semibold text-white">Crie seu workspace</h1>
                  <p className="mt-2 text-sm text-neutral-500">
                    Workspaces organizam seus projetos e configurações de integração.
                  </p>
                </div>
                <form onSubmit={handleCreateWorkspace} className="space-y-4">
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-neutral-400">
                      Nome do workspace
                    </label>
                    <input
                      type="text"
                      value={workspaceName}
                      onChange={(e) => setWorkspaceName(e.target.value)}
                      placeholder="Ex: Produção"
                      className="w-full rounded-lg border border-white/10 bg-white/5 px-3.5 py-2.5 text-sm text-white placeholder-neutral-600 outline-none transition-all focus:border-white/30 focus:ring-2 focus:ring-white/10"
                      required
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-neutral-400">
                      ERP ID{" "}
                      <span className="font-normal text-neutral-600">(opcional)</span>
                    </label>
                    <input
                      type="text"
                      value={erpId}
                      onChange={(e) => setErpId(e.target.value)}
                      placeholder="Identificador do ERP"
                      className="w-full rounded-lg border border-white/10 bg-white/5 px-3.5 py-2.5 text-sm text-white placeholder-neutral-600 outline-none transition-all focus:border-white/30 focus:ring-2 focus:ring-white/10"
                    />
                  </div>
                  {error ? <p className="text-sm text-red-400">{error}</p> : null}
                  <button
                    type="submit"
                    disabled={isLoading || !workspaceName.trim()}
                    className={cn(
                      "flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-all",
                      "bg-white text-neutral-900 hover:bg-neutral-100",
                      "disabled:cursor-not-allowed disabled:opacity-60"
                    )}
                  >
                    {isLoading ? (
                      <MorphLoader className="size-4" />
                    ) : (
                      <>Continuar <ArrowRight className="size-4" /></>
                    )}
                  </button>
                </form>
              </div>
            ) : null}

            {/* Step 3: Projeto (opcional) */}
            {step === "project" ? (
              <div>
                <div className="mb-6 text-center">
                  <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-full border border-white/10 bg-white/5">
                    <FolderOpen className="size-5 text-neutral-300" />
                  </div>
                  <h1 className="text-xl font-semibold text-white">Adicione um projeto</h1>
                  <p className="mt-2 text-sm text-neutral-500">
                    Opcional — você pode criar projetos a qualquer momento no painel.
                  </p>
                </div>
                <form onSubmit={handleCreateProject} className="space-y-4">
                  <div>
                    <label className="mb-1.5 block text-xs font-medium text-neutral-400">
                      Nome do projeto
                    </label>
                    <input
                      type="text"
                      value={projectName}
                      onChange={(e) => setProjectName(e.target.value)}
                      placeholder="Ex: Migração Q1"
                      className="w-full rounded-lg border border-white/10 bg-white/5 px-3.5 py-2.5 text-sm text-white placeholder-neutral-600 outline-none transition-all focus:border-white/30 focus:ring-2 focus:ring-white/10"
                    />
                  </div>
                  {error ? <p className="text-sm text-red-400">{error}</p> : null}
                  <div className="flex gap-3">
                    <button
                      type="button"
                      onClick={() => setStep("done")}
                      disabled={isLoading}
                      className="flex flex-1 items-center justify-center gap-2 rounded-lg border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium text-neutral-400 transition-all hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <SkipForward className="size-4" /> Pular
                    </button>
                    <button
                      type="submit"
                      disabled={isLoading || !projectName.trim()}
                      className={cn(
                        "flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-all",
                        "bg-white text-neutral-900 hover:bg-neutral-100",
                        "disabled:cursor-not-allowed disabled:opacity-60"
                      )}
                    >
                      {isLoading ? (
                        <MorphLoader className="size-4" />
                      ) : (
                        <>Criar <ArrowRight className="size-4" /></>
                      )}
                    </button>
                  </div>
                </form>
              </div>
            ) : null}
          </>
        ) : (
          /* Done */
          <div className="text-center">
            <div className="mx-auto mb-6 flex size-16 items-center justify-center rounded-full border border-emerald-500/30 bg-emerald-500/10">
              <CheckCircle2 className="size-7 text-emerald-400" />
            </div>
            <h1 className="text-2xl font-bold text-white">Tudo pronto!</h1>
            <p className="mt-2 text-sm text-neutral-500">
              Sua estrutura está configurada. Você pode criar mais workspaces e projetos a qualquer
              momento.
            </p>

            <div className="mt-6 space-y-2 rounded-xl border border-white/10 bg-white/5 p-4 text-left text-sm">
              <div className="flex items-center gap-2 text-neutral-300">
                <Building2 className="size-4 shrink-0 text-neutral-500" />
                <span className="font-medium">{orgName}</span>
              </div>
              <div className="ml-6 flex items-center gap-2 text-neutral-400">
                <Briefcase className="size-3.5 shrink-0 text-neutral-600" />
                <span>{workspaceName}</span>
              </div>
              {projectName ? (
                <div className="ml-10 flex items-center gap-2 text-neutral-500">
                  <FolderOpen className="size-3.5 shrink-0 text-neutral-700" />
                  <span>{projectName}</span>
                </div>
              ) : null}
            </div>

            <button
              type="button"
              onClick={() => router.push("/home")}
              className="mt-6 flex w-full items-center justify-center gap-2 rounded-lg bg-white px-4 py-2.5 text-sm font-semibold text-neutral-900 transition-all hover:bg-neutral-100"
            >
              Acessar o painel <ArrowRight className="size-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
