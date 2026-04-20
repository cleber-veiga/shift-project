"use client"

import { useState } from "react"
import { AlertTriangle, Check, Copy, KeyRound, ShieldAlert, X } from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { AgentApiKeyCreatePayload } from "@/lib/auth"

type WorkspaceRole = "VIEWER" | "CONSULTANT" | "MANAGER"
type ProjectRole = "CLIENT" | "EDITOR"

type ToolCatalogEntry = {
  name: string
  description: string
  destructive: boolean
}

export const AGENT_TOOL_CATALOG: ToolCatalogEntry[] = [
  { name: "list_workflows", description: "Lista fluxos do workspace/projeto", destructive: false },
  { name: "get_workflow", description: "Detalha um fluxo", destructive: false },
  { name: "execute_workflow", description: "Dispara execução de fluxo", destructive: true },
  { name: "get_execution_status", description: "Consulta status de execução", destructive: false },
  { name: "list_recent_executions", description: "Lista execuções recentes", destructive: false },
  { name: "cancel_execution", description: "Cancela execução em andamento", destructive: true },
  { name: "list_projects", description: "Lista projetos do workspace", destructive: false },
  { name: "get_project", description: "Detalha um projeto", destructive: false },
  { name: "create_project", description: "Cria um novo projeto", destructive: true },
  { name: "list_project_members", description: "Lista membros de um projeto", destructive: false },
  { name: "list_connections", description: "Lista conexões do escopo", destructive: false },
  { name: "get_connection", description: "Detalha uma conexão", destructive: false },
  { name: "test_connection", description: "Testa uma conexão", destructive: false },
  { name: "list_webhooks", description: "Lista webhooks do workspace", destructive: false },
  { name: "trigger_webhook_manually", description: "Dispara webhook manualmente", destructive: true },
]

const WORKSPACE_ROLES: { value: WorkspaceRole; label: string }[] = [
  { value: "VIEWER", label: "Visualizador" },
  { value: "CONSULTANT", label: "Consultor" },
  { value: "MANAGER", label: "Gerente" },
]

const PROJECT_ROLES: { value: ProjectRole; label: string; description: string }[] = [
  { value: "CLIENT", label: "Cliente", description: "Leitura de um projeto específico" },
  { value: "EDITOR", label: "Editor", description: "Pode editar um projeto específico" },
]

interface CreateAgentKeyModalProps {
  open: boolean
  onClose: () => void
  workspaceId: string
  projectId?: string | null
  onCreate: (payload: AgentApiKeyCreatePayload) => Promise<{ api_key: string }>
}

export function CreateAgentKeyModal({
  open,
  onClose,
  workspaceId,
  projectId,
  onCreate,
}: CreateAgentKeyModalProps) {
  const [name, setName] = useState("")
  const [maxWorkspaceRole, setMaxWorkspaceRole] = useState<WorkspaceRole>("CONSULTANT")
  const [maxProjectRole, setMaxProjectRole] = useState<ProjectRole | "none">("none")
  const [allowedTools, setAllowedTools] = useState<Set<string>>(new Set())
  const [wildcard, setWildcard] = useState(false)
  const [requireApproval, setRequireApproval] = useState(true)
  const [expiresAt, setExpiresAt] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const [plaintext, setPlaintext] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const reset = () => {
    setName("")
    setMaxWorkspaceRole("CONSULTANT")
    setMaxProjectRole("none")
    setAllowedTools(new Set())
    setWildcard(false)
    setRequireApproval(true)
    setExpiresAt("")
    setError("")
    setPlaintext(null)
    setCopied(false)
  }

  const handleClose = () => {
    if (loading) return
    reset()
    onClose()
  }

  const toggleTool = (toolName: string) => {
    setAllowedTools((prev) => {
      const next = new Set(prev)
      if (next.has(toolName)) next.delete(toolName)
      else next.add(toolName)
      return next
    })
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    const tools = wildcard ? ["*"] : Array.from(allowedTools)
    if (tools.length === 0) {
      setError("Selecione pelo menos uma tool ou marque 'Liberar todas'.")
      return
    }

    setLoading(true)
    setError("")
    try {
      const payload: AgentApiKeyCreatePayload = {
        workspace_id: workspaceId,
        project_id: projectId ?? null,
        name: name.trim(),
        max_workspace_role: maxWorkspaceRole,
        max_project_role: maxProjectRole === "none" ? null : maxProjectRole,
        allowed_tools: tools,
        require_human_approval: requireApproval,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      }
      const result = await onCreate(payload)
      setPlaintext(result.api_key)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao criar chave.")
    } finally {
      setLoading(false)
    }
  }

  const handleCopy = async () => {
    if (!plaintext) return
    try {
      await navigator.clipboard.writeText(plaintext)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // navigator.clipboard may fail in insecure contexts — ignore
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={handleClose} />

      <div
        role="dialog"
        aria-modal="true"
        className="relative z-10 max-h-[92vh] w-full max-w-2xl overflow-auto rounded-2xl border border-border bg-card p-6 shadow-2xl"
      >
        <div className="mb-5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10">
              <KeyRound className="size-4 text-primary" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-foreground">
                {plaintext ? "Chave criada com sucesso" : "Nova Chave de API"}
              </h2>
              <p className="text-xs text-muted-foreground">
                {plaintext
                  ? "Copie e guarde — a chave não será exibida novamente."
                  : "Será usada por clientes MCP externos (Claude Desktop, n8n etc.)."}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </div>

        {plaintext ? (
          <div className="space-y-4">
            <div className="flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3">
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
              <div className="text-xs text-amber-900 dark:text-amber-200">
                Esta é a única vez que o valor será mostrado. Depois disso, só um novo registro permite recuperar o acesso.
              </div>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                Chave (plaintext)
              </label>
              <div className="flex items-stretch gap-2">
                <code className="flex-1 overflow-x-auto rounded-lg border border-input bg-background px-3 py-2.5 font-mono text-xs text-foreground">
                  {plaintext}
                </code>
                <button
                  type="button"
                  onClick={handleCopy}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-input bg-background px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-accent"
                >
                  {copied ? (
                    <>
                      <Check className="size-3.5 text-emerald-500" /> Copiado
                    </>
                  ) : (
                    <>
                      <Copy className="size-3.5" /> Copiar
                    </>
                  )}
                </button>
              </div>
            </div>

            <div className="flex items-center justify-end pt-2">
              <button
                type="button"
                onClick={handleClose}
                className="inline-flex items-center gap-2 rounded-lg bg-foreground px-4 py-2 text-sm font-semibold text-background transition-opacity hover:opacity-90"
              >
                Fechar
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                Nome
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="ex.: Claude Desktop do time de dados"
                className="w-full rounded-lg border border-input bg-background px-3.5 py-2.5 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-2 focus:ring-ring/20"
                required
                maxLength={255}
              />
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  Papel máximo (workspace)
                </label>
                <Select
                  value={maxWorkspaceRole}
                  onValueChange={(v) => setMaxWorkspaceRole(v as WorkspaceRole)}
                >
                  <SelectTrigger className="w-full bg-background">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {WORKSPACE_ROLES.map((r) => (
                      <SelectItem key={r.value} value={r.value}>
                        {r.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  Papel máximo (projeto)
                </label>
                <Select
                  value={maxProjectRole}
                  onValueChange={(v) => setMaxProjectRole(v as ProjectRole | "none")}
                >
                  <SelectTrigger className="w-full bg-background">
                    <SelectValue placeholder="Sem restrição" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">Sem restrição</SelectItem>
                    {PROJECT_ROLES.map((r) => (
                      <SelectItem key={r.value} value={r.value}>
                        {r.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                Expiração (opcional)
              </label>
              <input
                type="datetime-local"
                value={expiresAt}
                onChange={(e) => setExpiresAt(e.target.value)}
                className="w-full rounded-lg border border-input bg-background px-3.5 py-2.5 text-sm text-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20"
              />
              <p className="mt-1 text-[11px] text-muted-foreground">
                Deixe em branco para não expirar. Após a data, o MCP server retorna 401.
              </p>
            </div>

            <div>
              <div className="mb-2 flex items-center justify-between">
                <label className="text-xs font-medium text-muted-foreground">
                  Tools liberadas
                </label>
                <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-foreground">
                  <input
                    type="checkbox"
                    checked={wildcard}
                    onChange={(e) => setWildcard(e.target.checked)}
                    className="size-3.5 accent-primary"
                  />
                  Liberar todas (<code className="text-[10px]">*</code>)
                </label>
              </div>

              <div
                className={`max-h-64 overflow-auto rounded-lg border border-input bg-background p-2 ${
                  wildcard ? "pointer-events-none opacity-50" : ""
                }`}
              >
                <div className="grid gap-1 sm:grid-cols-2">
                  {AGENT_TOOL_CATALOG.map((tool) => {
                    const checked = allowedTools.has(tool.name)
                    return (
                      <label
                        key={tool.name}
                        className="flex cursor-pointer items-start gap-2 rounded px-2 py-1.5 text-xs transition-colors hover:bg-muted/40"
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleTool(tool.name)}
                          className="mt-0.5 size-3.5 accent-primary"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-1">
                            <code className="font-mono text-[11px] text-foreground">
                              {tool.name}
                            </code>
                            {tool.destructive ? (
                              <ShieldAlert className="size-3 text-amber-500" aria-label="Destrutiva" />
                            ) : null}
                          </span>
                          <span className="block text-[10px] text-muted-foreground">
                            {tool.description}
                          </span>
                        </span>
                      </label>
                    )
                  })}
                </div>
              </div>
            </div>

            <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-input bg-background px-3 py-2.5">
              <input
                type="checkbox"
                checked={requireApproval}
                onChange={(e) => setRequireApproval(e.target.checked)}
                className="mt-0.5 size-3.5 accent-primary"
              />
              <span className="text-xs">
                <span className="font-medium text-foreground">Exigir aprovação humana</span>
                <span className="block text-[11px] text-muted-foreground">
                  Tools destrutivas criam um pedido de aprovação que precisa ser confirmado na UI antes de executar. Desligue apenas para automações confiáveis.
                </span>
              </span>
            </label>

            {error ? <p className="text-sm text-destructive">{error}</p> : null}

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={handleClose}
                className="rounded-lg px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={loading || !name.trim()}
                className="inline-flex items-center gap-2 rounded-lg bg-foreground px-4 py-2 text-sm font-semibold text-background transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? (
                  <MorphLoader className="size-4" />
                ) : (
                  <>
                    <KeyRound className="size-3.5" />
                    Criar Chave
                  </>
                )}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
