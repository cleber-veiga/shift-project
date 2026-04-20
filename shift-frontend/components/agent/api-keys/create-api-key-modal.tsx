"use client"

import { useState } from "react"
import { KeyRound, ShieldAlert, X } from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { CreateApiKeyInput } from "@/lib/types/agent-api-key"

type ToolEntry = {
  name: string
  description: string
  destructive: boolean
}

type ToolCategory = {
  label: string
  tools: ToolEntry[]
}

const TOOL_CATEGORIES: ToolCategory[] = [
  {
    label: "Fluxos",
    tools: [
      { name: "list_workflows", description: "Lista fluxos do workspace/projeto", destructive: false },
      { name: "get_workflow", description: "Detalha um fluxo", destructive: false },
      { name: "execute_workflow", description: "Dispara execução de fluxo", destructive: true },
      { name: "get_execution_status", description: "Consulta status de execução", destructive: false },
      { name: "list_recent_executions", description: "Lista execuções recentes", destructive: false },
      { name: "cancel_execution", description: "Cancela execução em andamento", destructive: true },
    ],
  },
  {
    label: "Projetos",
    tools: [
      { name: "list_projects", description: "Lista projetos do workspace", destructive: false },
      { name: "get_project", description: "Detalha um projeto", destructive: false },
      { name: "create_project", description: "Cria um novo projeto", destructive: true },
      { name: "list_project_members", description: "Lista membros de um projeto", destructive: false },
    ],
  },
  {
    label: "Conexões",
    tools: [
      { name: "list_connections", description: "Lista conexões do escopo", destructive: false },
      { name: "get_connection", description: "Detalha uma conexão", destructive: false },
      { name: "test_connection", description: "Testa uma conexão", destructive: false },
    ],
  },
  {
    label: "Webhooks",
    tools: [
      { name: "list_webhooks", description: "Lista webhooks do workspace", destructive: false },
      { name: "trigger_webhook_manually", description: "Dispara webhook manualmente", destructive: true },
    ],
  },
]

const ALL_TOOL_NAMES = TOOL_CATEGORIES.flatMap((c) => c.tools.map((t) => t.name))

const EXPIRES_OPTIONS = [
  { value: "30", label: "30 dias" },
  { value: "60", label: "60 dias" },
  { value: "90", label: "90 dias" },
  { value: "never", label: "Nunca expira" },
]

interface CreateApiKeyModalProps {
  open: boolean
  onClose: () => void
  onCreate: (input: CreateApiKeyInput) => Promise<void>
}

export function CreateApiKeyModal({ open, onClose, onCreate }: CreateApiKeyModalProps) {
  const [name, setName] = useState("")
  const [expiresOption, setExpiresOption] = useState("90")
  const [allowedTools, setAllowedTools] = useState<Set<string>>(new Set())
  const [wildcard, setWildcard] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const reset = () => {
    setName("")
    setExpiresOption("90")
    setAllowedTools(new Set())
    setWildcard(false)
    setError("")
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

  const toggleCategory = (category: ToolCategory) => {
    const categoryToolNames = category.tools.map((t) => t.name)
    const allSelected = categoryToolNames.every((n) => allowedTools.has(n))
    setAllowedTools((prev) => {
      const next = new Set(prev)
      if (allSelected) {
        categoryToolNames.forEach((n) => next.delete(n))
      } else {
        categoryToolNames.forEach((n) => next.add(n))
      }
      return next
    })
  }

  const toggleAll = (checked: boolean) => {
    setWildcard(checked)
    if (checked) {
      setAllowedTools(new Set(ALL_TOOL_NAMES))
    }
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
      const expiresInDays = expiresOption === "never" ? null : Number(expiresOption)
      await onCreate({ name: name.trim(), expiresInDays, allowedTools: tools })
      reset()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao criar chave.")
    } finally {
      setLoading(false)
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
              <h2 className="text-base font-semibold text-foreground">Nova Chave de API</h2>
              <p className="text-xs text-muted-foreground">
                Acesso programático ao Shift Agent para este projeto.
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

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              Nome <span className="text-destructive">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="ex.: Claude Desktop — Time de Dados"
              className="w-full rounded-lg border border-input bg-background px-3.5 py-2.5 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-2 focus:ring-ring/20"
              required
              maxLength={255}
              autoFocus
            />
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              Expiração
            </label>
            <Select value={expiresOption} onValueChange={setExpiresOption}>
              <SelectTrigger className="w-full bg-background">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {EXPIRES_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="mt-1 text-[11px] text-muted-foreground">
              Após a data, o agente recebe 401 e perde acesso automaticamente.
            </p>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <label className="text-xs font-medium text-muted-foreground">
                Tools permitidas
              </label>
              <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-foreground">
                <input
                  type="checkbox"
                  checked={wildcard}
                  onChange={(e) => toggleAll(e.target.checked)}
                  className="size-3.5 accent-primary"
                />
                Liberar todas (<code className="text-[10px]">*</code>)
              </label>
            </div>

            <div
              className={`max-h-72 overflow-auto rounded-lg border border-input bg-background p-3 ${
                wildcard ? "pointer-events-none opacity-50" : ""
              }`}
            >
              <div className="space-y-4">
                {TOOL_CATEGORIES.map((category) => {
                  const categoryToolNames = category.tools.map((t) => t.name)
                  const selectedCount = categoryToolNames.filter((n) => allowedTools.has(n)).length
                  const allSelected = selectedCount === categoryToolNames.length

                  return (
                    <div key={category.label}>
                      <div className="mb-1.5 flex items-center gap-2">
                        <label className="inline-flex cursor-pointer items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                          <input
                            type="checkbox"
                            checked={allSelected}
                            onChange={() => toggleCategory(category)}
                            className="size-3 accent-primary"
                          />
                          {category.label}
                        </label>
                        {selectedCount > 0 && !allSelected && (
                          <span className="text-[10px] text-muted-foreground">
                            ({selectedCount}/{categoryToolNames.length})
                          </span>
                        )}
                      </div>

                      <div className="grid gap-0.5 sm:grid-cols-2">
                        {category.tools.map((tool) => (
                          <label
                            key={tool.name}
                            className="flex cursor-pointer items-start gap-2 rounded px-2 py-1.5 text-xs transition-colors hover:bg-muted/40"
                          >
                            <input
                              type="checkbox"
                              checked={allowedTools.has(tool.name)}
                              onChange={() => toggleTool(tool.name)}
                              className="mt-0.5 size-3.5 accent-primary"
                            />
                            <span className="min-w-0 flex-1">
                              <span className="flex items-center gap-1">
                                <code className="font-mono text-[11px] text-foreground">
                                  {tool.name}
                                </code>
                                {tool.destructive ? (
                                  <ShieldAlert
                                    className="size-3 text-amber-500"
                                    aria-label="Tool destrutiva"
                                  />
                                ) : null}
                              </span>
                              <span className="block text-[10px] text-muted-foreground">
                                {tool.description}
                              </span>
                            </span>
                          </label>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground">
              <ShieldAlert className="mr-0.5 inline size-3 text-amber-500" />
              Tools com este ícone podem modificar dados — use com cuidado.
            </p>
          </div>

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
      </div>
    </div>
  )
}
