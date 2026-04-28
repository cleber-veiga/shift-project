"use client"

import React, { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { SkipForward } from "lucide-react"
import {
  createOrganization,
  createWorkspace,
  createWorkspaceProject,
  getValidSession,
  setSelectedOrganizationId,
  setSelectedWorkspaceId,
  setSelectedProjectId,
} from "@/lib/auth"
import { MorphLoader } from "@/components/ui/morph-loader"
import {
  ArrowRight,
  AUTH_TOKENS,
  AuthShell,
  CheckIcon,
  PaperCard,
  PaperField,
  PrimaryCta,
  ValueProps,
} from "@/components/auth/auth-shell"

const { ACCENT, BORDER_PAPER, INK } = AUTH_TOKENS

type Step = "org" | "workspace" | "project" | "done"

const STEPS = [
  { key: "org", label: "Organização" },
  { key: "workspace", label: "Workspace" },
  { key: "project", label: "Projeto" },
] as const

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

  const currentIndex = STEPS.findIndex((s) => s.key === step)

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

  const heroByStep = (() => {
    switch (step) {
      case "org":
        return {
          eyebrow: "Onboarding · 1 de 3",
          title: (
            <>
              Comece pela{" "}
              <em style={{ fontStyle: "italic", fontWeight: 500, color: ACCENT }}>organização</em>.
            </>
          ),
          body: "Uma organização agrupa workspaces, projetos e membros. Em geral, ela representa sua empresa.",
        }
      case "workspace":
        return {
          eyebrow: "Onboarding · 2 de 3",
          title: (
            <>
              Crie um{" "}
              <em style={{ fontStyle: "italic", fontWeight: 500, color: ACCENT }}>workspace</em>.
            </>
          ),
          body: "Workspaces guardam configurações de ERP, conexões e fluxos. Comece com um e depois evolua.",
        }
      case "project":
        return {
          eyebrow: "Onboarding · 3 de 3",
          title: (
            <>
              Adicione um{" "}
              <em style={{ fontStyle: "italic", fontWeight: 500, color: ACCENT }}>projeto</em>.
            </>
          ),
          body: "Projetos organizam fluxos por cliente, escopo ou contrato. É opcional — pode pular.",
        }
      case "done":
        return {
          eyebrow: "Tudo pronto",
          title: (
            <>
              Bem-vindo ao{" "}
              <em style={{ fontStyle: "italic", fontWeight: 500, color: ACCENT }}>Shift</em>.
            </>
          ),
          body: "Sua estrutura está configurada. Você pode adicionar mais workspaces e projetos a qualquer momento.",
          support: (
            <ValueProps
              items={[
                `Organização: ${orgName}`,
                `Workspace: ${workspaceName}`,
                projectName ? `Projeto: ${projectName}` : "Sem projeto inicial — você pode criar depois.",
              ]}
            />
          ),
        }
    }
  })()

  return (
    <AuthShell
      heroEyebrow={heroByStep.eyebrow}
      heroTitle={heroByStep.title}
      heroBody={heroByStep.body}
      heroSupport={heroByStep.support}
    >
      <PaperCard
        eyebrow={
          step === "done" ? "Estrutura criada" : `Passo ${currentIndex + 1} de ${STEPS.length}`
        }
      >
        {step !== "done" ? (
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 24 }}>
            {STEPS.map((s, i) => {
              const reached = i <= currentIndex
              return (
                <React.Fragment key={s.key}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span
                      style={{
                        width: 22,
                        height: 22,
                        borderRadius: "50%",
                        border: `1px solid ${reached ? ACCENT : "#d1d5db"}`,
                        background: reached ? ACCENT : "transparent",
                        color: reached ? "white" : "#9ca3af",
                        fontSize: 11,
                        fontWeight: 700,
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      {i < currentIndex ? <CheckIcon size={11} /> : i + 1}
                    </span>
                    <span
                      style={{
                        fontSize: 12,
                        color: i === currentIndex ? INK : "#9ca3af",
                        fontWeight: i === currentIndex ? 600 : 400,
                      }}
                    >
                      {s.label}
                    </span>
                  </div>
                  {i < STEPS.length - 1 ? (
                    <div
                      style={{
                        flex: 1,
                        height: 1,
                        background: i < currentIndex ? ACCENT : "#d1d5db",
                      }}
                    />
                  ) : null}
                </React.Fragment>
              )
            })}
          </div>
        ) : null}

        {step === "org" ? (
          <form onSubmit={handleCreateOrg} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <PaperField
              label="Nome da organização"
              placeholder="Ex: Minha Empresa"
              value={orgName}
              onChange={setOrgName}
              required
              minLength={2}
            />
            {error ? <p style={{ margin: 0, fontSize: 13, color: "#dc2626" }}>{error}</p> : null}
            <PrimaryCta type="submit" disabled={isLoading || orgName.trim().length < 2}>
              {isLoading ? <MorphLoader className="size-4" /> : <>Continuar <ArrowRight /></>}
            </PrimaryCta>
          </form>
        ) : null}

        {step === "workspace" ? (
          <form onSubmit={handleCreateWorkspace} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <PaperField
              label="Nome do workspace"
              placeholder="Ex: Produção"
              value={workspaceName}
              onChange={setWorkspaceName}
              required
            />
            <PaperField
              label="ERP ID (opcional)"
              placeholder="Identificador do ERP"
              value={erpId}
              onChange={setErpId}
            />
            {error ? <p style={{ margin: 0, fontSize: 13, color: "#dc2626" }}>{error}</p> : null}
            <PrimaryCta type="submit" disabled={isLoading || !workspaceName.trim()}>
              {isLoading ? <MorphLoader className="size-4" /> : <>Continuar <ArrowRight /></>}
            </PrimaryCta>
          </form>
        ) : null}

        {step === "project" ? (
          <form onSubmit={handleCreateProject} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <PaperField
              label="Nome do projeto"
              placeholder="Ex: Migração Q1"
              value={projectName}
              onChange={setProjectName}
            />
            {error ? <p style={{ margin: 0, fontSize: 13, color: "#dc2626" }}>{error}</p> : null}
            <div style={{ display: "flex", gap: 12 }}>
              <button
                type="button"
                onClick={() => setStep("done")}
                disabled={isLoading}
                style={{
                  flex: 1,
                  height: 48,
                  background: "transparent",
                  border: `1px solid ${BORDER_PAPER}`,
                  borderRadius: 8,
                  fontSize: 14,
                  fontWeight: 500,
                  color: "#4b5563",
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 8,
                  cursor: "pointer",
                  fontFamily: "inherit",
                }}
              >
                <SkipForward size={14} /> Pular
              </button>
              <div style={{ flex: 1 }}>
                <PrimaryCta type="submit" disabled={isLoading || !projectName.trim()}>
                  {isLoading ? <MorphLoader className="size-4" /> : <>Criar <ArrowRight /></>}
                </PrimaryCta>
              </div>
            </div>
          </form>
        ) : null}

        {step === "done" ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: 16,
                background: "rgba(99,102,241,0.06)",
                border: "1px solid rgba(99,102,241,0.18)",
                borderRadius: 8,
                fontSize: 14,
                color: INK,
              }}
            >
              <span
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: "50%",
                  background: ACCENT,
                  color: "white",
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flex: "0 0 auto",
                }}
              >
                <CheckIcon size={14} />
              </span>
              Estrutura criada com sucesso.
            </div>
            <PrimaryCta type="button" onClick={() => router.push("/home")}>
              Acessar o painel <ArrowRight />
            </PrimaryCta>
          </div>
        ) : null}
      </PaperCard>
    </AuthShell>
  )
}
