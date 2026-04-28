"use client"

import { useState, useEffect } from "react"
import {
  ChevronDown,
  ChevronUp,
  Eye,
  Link2,
  Pencil,
  Plus,
  Trash2,
  X,
} from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import type { WorkflowVariable, WorkflowVariableType } from "@/lib/workflow/types"
import type { InheritedVariable } from "@/lib/api/workflow-variables"

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const VARIABLE_TYPES: { value: WorkflowVariableType; label: string }[] = [
  { value: "string", label: "Texto (string)" },
  { value: "integer", label: "Inteiro (integer)" },
  { value: "number", label: "Número (number)" },
  { value: "boolean", label: "Booleano (boolean)" },
  { value: "object", label: "Objeto (object)" },
  { value: "array", label: "Lista (array)" },
  { value: "connection", label: "Conexão (connection)" },
  { value: "file_upload", label: "Arquivo (file_upload)" },
  { value: "secret", label: "Segredo (secret)" },
]

const CONNECTION_TYPES = [
  { value: "postgres", label: "PostgreSQL" },
  { value: "mysql", label: "MySQL" },
  { value: "sqlserver", label: "SQL Server" },
  { value: "oracle", label: "Oracle" },
  { value: "mongodb", label: "MongoDB" },
]

const TYPE_BADGE: Record<WorkflowVariableType, string> = {
  string: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  integer: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  number: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  boolean: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  object: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300",
  array: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300",
  connection: "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300",
  file_upload: "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300",
  secret: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
}

const IDENTIFIER_RE = /^[A-Za-z_][A-Za-z0-9_]*$/

// ---------------------------------------------------------------------------
// Empty variable factory
// ---------------------------------------------------------------------------

function emptyVariable(): WorkflowVariable {
  return {
    name: "",
    type: "string",
    required: true,
    default: undefined,
    description: "",
    connection_type: undefined,
    accepted_extensions: undefined,
    ui_order: 0,
  }
}

// ---------------------------------------------------------------------------
// Variable form dialog
// ---------------------------------------------------------------------------

interface VariableFormProps {
  initial: WorkflowVariable
  existingNames: string[]
  onSave: (v: WorkflowVariable) => void
  onCancel: () => void
}

function VariableForm({ initial, existingNames, onSave, onCancel }: VariableFormProps) {
  const [draft, setDraft] = useState<WorkflowVariable>({ ...initial })
  const [nameError, setNameError] = useState<string | null>(null)
  const [extInput, setExtInput] = useState(
    (initial.accepted_extensions ?? []).join(", "),
  )

  function set<K extends keyof WorkflowVariable>(key: K, value: WorkflowVariable[K]) {
    setDraft((prev) => ({ ...prev, [key]: value }))
  }

  function handleTypeChange(newType: WorkflowVariableType) {
    setDraft((prev) => ({
      ...prev,
      type: newType,
      connection_type: newType === "connection" ? (prev.connection_type ?? undefined) : undefined,
      accepted_extensions: newType === "file_upload" ? (prev.accepted_extensions ?? []) : undefined,
    }))
  }

  function validate(): boolean {
    const name = draft.name.trim()
    if (!name) {
      setNameError("Nome obrigatório.")
      return false
    }
    if (!IDENTIFIER_RE.test(name)) {
      setNameError("Apenas letras, números e _ (não pode começar com número).")
      return false
    }
    if (existingNames.includes(name) && name !== initial.name) {
      setNameError("Já existe uma variável com esse nome.")
      return false
    }
    setNameError(null)
    return true
  }

  function handleSubmit() {
    if (!validate()) return
    const exts =
      draft.type === "file_upload"
        ? extInput
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean)
        : undefined
    onSave({ ...draft, name: draft.name.trim(), accepted_extensions: exts })
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-[2px]"
      onClick={onCancel}
    >
      <div
        className="w-[min(480px,96vw)] rounded-2xl border border-border bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <h3 className="text-sm font-semibold text-foreground">
            {initial.name ? "Editar variável" : "Nova variável"}
          </h3>
          <button
            type="button"
            onClick={onCancel}
            className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex flex-col gap-4 px-5 py-4">
          {/* Name */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-foreground">
              Nome <span className="text-destructive">*</span>
            </label>
            <input
              autoFocus
              value={draft.name}
              onChange={(e) => {
                set("name", e.target.value)
                setNameError(null)
              }}
              placeholder="ex: minha_conexao"
              className="h-8 rounded-md border border-input bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
            {nameError && (
              <p className="text-[11px] text-destructive">{nameError}</p>
            )}
            <p className="text-[11px] text-muted-foreground">
              Referenciado nos nós como{" "}
              <code className="rounded bg-muted px-1 font-mono">
                {"{{vars."}
                {draft.name || "nome"}
                {"}}"}
              </code>
            </p>
          </div>

          {/* Type */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-foreground">Tipo</label>
            <select
              value={draft.type}
              onChange={(e) => handleTypeChange(e.target.value as WorkflowVariableType)}
              className="h-8 rounded-md border border-input bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
            >
              {VARIABLE_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>

          {/* Conditional: connection_type */}
          {draft.type === "connection" && (
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-foreground">
                Tipo de conexão
              </label>
              <select
                value={draft.connection_type ?? ""}
                onChange={(e) =>
                  set(
                    "connection_type",
                    (e.target.value || undefined) as WorkflowVariable["connection_type"],
                  )
                }
                className="h-8 rounded-md border border-input bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
              >
                <option value="">Qualquer tipo</option>
                {CONNECTION_TYPES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Conditional: accepted_extensions */}
          {draft.type === "file_upload" && (
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-foreground">
                Extensões aceitas
              </label>
              <input
                value={extInput}
                onChange={(e) => setExtInput(e.target.value)}
                placeholder=".csv, .xlsx, .json"
                className="h-8 rounded-md border border-input bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
              <p className="text-[11px] text-muted-foreground">
                Separadas por vírgula. Vazio = sem restrição.
              </p>
            </div>
          )}

          {/* Required */}
          <label className="flex cursor-pointer items-center gap-2.5">
            <input
              type="checkbox"
              checked={draft.required}
              onChange={(e) => set("required", e.target.checked)}
              className="size-4 rounded accent-primary"
            />
            <span className="text-sm text-foreground">Obrigatória</span>
          </label>

          {/* Default (hidden for secret) */}
          {draft.type !== "secret" && (
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-foreground">
                Valor padrão
              </label>
              <input
                value={
                  draft.default === undefined || draft.default === null
                    ? ""
                    : String(draft.default)
                }
                onChange={(e) =>
                  set("default", e.target.value === "" ? undefined : e.target.value)
                }
                placeholder="Opcional"
                className="h-8 rounded-md border border-input bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
            </div>
          )}

          {/* Description */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-foreground">
              Descrição
            </label>
            <textarea
              value={draft.description ?? ""}
              onChange={(e) => set("description", e.target.value)}
              placeholder="Opcional — ajuda o usuário ao executar o workflow"
              rows={2}
              className="resize-none rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
          <button
            type="button"
            onClick={onCancel}
            className="inline-flex h-8 items-center rounded-md border border-border bg-background px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            className="inline-flex h-8 items-center rounded-md bg-primary px-3 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
          >
            {initial.name ? "Salvar" : "Adicionar"}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Variables panel
// ---------------------------------------------------------------------------

interface VariablesPanelProps {
  workflowId: string
  variables: WorkflowVariable[]
  inheritedVariables?: InheritedVariable[]
  isSaving: boolean
  error: string | null
  onClose: () => void
  onChange: (vars: WorkflowVariable[]) => void
  onSave: (vars: WorkflowVariable[]) => void
  onPreview?: () => void
}

export function VariablesPanel({
  workflowId: _workflowId,
  variables,
  inheritedVariables = [],
  isSaving,
  error,
  onClose,
  onChange,
  onSave,
  onPreview,
}: VariablesPanelProps) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [addingNew, setAddingNew] = useState(false)
  const [saved, setSaved] = useState(false)

  // Clear "Salvo!" feedback after 2 s
  useEffect(() => {
    if (!saved) return
    const t = setTimeout(() => setSaved(false), 2000)
    return () => clearTimeout(t)
  }, [saved])

  function handleAdd(v: WorkflowVariable) {
    const updated = [
      ...variables,
      { ...v, ui_order: variables.length },
    ]
    onChange(updated)
    setAddingNew(false)
  }

  function handleEdit(index: number, v: WorkflowVariable) {
    const updated = variables.map((existing, i) =>
      i === index ? { ...v, ui_order: i } : existing,
    )
    onChange(updated)
    setEditingIndex(null)
  }

  function handleDelete(index: number) {
    const updated = variables
      .filter((_, i) => i !== index)
      .map((v, i) => ({ ...v, ui_order: i }))
    onChange(updated)
  }

  function handleMove(index: number, dir: -1 | 1) {
    const next = index + dir
    if (next < 0 || next >= variables.length) return
    const updated = [...variables]
    ;[updated[index], updated[next]] = [updated[next], updated[index]]
    onChange(updated.map((v, i) => ({ ...v, ui_order: i })))
  }

  async function handleSave() {
    const ok = await new Promise<boolean>((resolve) => {
      onSave(variables)
      // resolve via the parent's isSaving → false transition
      resolve(true)
    })
    if (ok) setSaved(true)
  }

  const editingVar =
    editingIndex !== null ? variables[editingIndex] : null
  const existingNames = variables.map((v) => v.name)

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 flex items-stretch justify-end bg-black/30 backdrop-blur-[2px]"
        onClick={onClose}
      >
        {/* Panel */}
        <div
          className="flex h-full w-full max-w-md flex-col border-l border-border bg-background shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <header className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
            <div>
              <h2 className="text-sm font-semibold text-foreground">
                Variáveis do Workflow
              </h2>
              <p className="text-[10px] text-muted-foreground">
                Valores injetados em tempo de execução via{" "}
                <code className="font-mono">{"{{vars.nome}}"}</code>
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Fechar"
              className="flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          </header>

          {/* Variable list */}
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
            {variables.length === 0 ? (
              <div className="flex flex-1 flex-col items-center justify-center gap-2 py-12 text-center">
                <p className="text-sm text-muted-foreground">
                  Nenhuma variável declarada.
                </p>
                <p className="max-w-[240px] text-[11px] text-muted-foreground/70">
                  Adicione variáveis para parametrizar conexões, arquivos e
                  segredos sem alterar a definição do workflow.
                </p>
              </div>
            ) : (
              <ul className="divide-y divide-border">
                {variables.map((v, i) => (
                  <li
                    key={v.name}
                    className="flex items-center gap-2 px-4 py-2.5"
                  >
                    {/* Move buttons */}
                    <div className="flex flex-col">
                      <button
                        type="button"
                        onClick={() => handleMove(i, -1)}
                        disabled={i === 0}
                        className="flex size-5 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-20"
                        aria-label="Mover para cima"
                      >
                        <ChevronUp className="size-3" />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleMove(i, 1)}
                        disabled={i === variables.length - 1}
                        className="flex size-5 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-20"
                        aria-label="Mover para baixo"
                      >
                        <ChevronDown className="size-3" />
                      </button>
                    </div>

                    {/* Info */}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-sm font-medium text-foreground">
                          {v.name}
                        </span>
                        {v.required && (
                          <span className="text-[10px] text-destructive">*</span>
                        )}
                        <span
                          className={`inline-flex rounded px-1.5 py-0.5 text-[10px] font-medium ${TYPE_BADGE[v.type]}`}
                        >
                          {v.type}
                        </span>
                      </div>
                      {v.description && (
                        <p className="truncate text-[11px] text-muted-foreground">
                          {v.description}
                        </p>
                      )}
                    </div>

                    {/* Actions */}
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        onClick={() => setEditingIndex(i)}
                        className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                        aria-label="Editar"
                      >
                        <Pencil className="size-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(i)}
                        className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
                        aria-label="Remover"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Inherited (read-only) from sub-workflows */}
          {inheritedVariables.length > 0 && (
            <div className="shrink-0 border-t border-border">
              <div className="flex items-center gap-1.5 bg-muted/30 px-4 py-1.5">
                <Link2 className="size-3 text-muted-foreground" />
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Herdadas de sub-fluxos
                </span>
                <span className="ml-auto text-[10px] text-muted-foreground">
                  somente leitura
                </span>
              </div>
              <ul className="divide-y divide-border">
                {inheritedVariables.map((iv) => (
                  <li
                    key={`${iv.sub_workflow_id}::${iv.variable.name}`}
                    className="flex items-center gap-2 px-4 py-2"
                    title={`Vem de: ${iv.sub_workflow_name} (v${iv.sub_workflow_version})`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-sm font-medium text-muted-foreground">
                          {iv.variable.name}
                        </span>
                        {iv.variable.required && (
                          <span className="text-[10px] text-destructive">*</span>
                        )}
                        <span
                          className={`inline-flex rounded px-1.5 py-0.5 text-[10px] font-medium ${TYPE_BADGE[iv.variable.type]}`}
                        >
                          {iv.variable.type}
                        </span>
                      </div>
                      <p className="truncate text-[10px] text-muted-foreground">
                        <span className="font-medium">{iv.sub_workflow_name}</span>
                        <span className="ml-1 opacity-70">v{iv.sub_workflow_version}</span>
                        {iv.variable.description && (
                          <>
                            <span className="mx-1">·</span>
                            {iv.variable.description}
                          </>
                        )}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Add button */}
          <div className="shrink-0 border-t border-border px-4 py-2">
            <button
              type="button"
              onClick={() => setAddingNew(true)}
              className="inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-md border border-dashed border-border text-xs font-medium text-muted-foreground transition-colors hover:border-primary/60 hover:bg-muted hover:text-foreground"
            >
              <Plus className="size-3.5" />
              Adicionar variável
            </button>
          </div>

          {/* Footer: error + preview + save */}
          <footer className="flex shrink-0 flex-col gap-1.5 border-t border-border px-4 py-3">
            {error && (
              <p className="text-[11px] text-destructive">{error}</p>
            )}
            {onPreview && variables.length > 0 && (
              <button
                type="button"
                onClick={onPreview}
                className="inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-md border border-border bg-background text-xs font-medium text-foreground transition-colors hover:bg-muted"
              >
                <Eye className="size-3.5" />
                Preview do formulário de execução
              </button>
            )}
            <button
              type="button"
              onClick={handleSave}
              disabled={isSaving}
              className="inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-md bg-primary text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
            >
              {isSaving ? (
                <MorphLoader className="size-3.5" />
              ) : saved ? (
                "Salvo!"
              ) : (
                "Salvar variáveis"
              )}
            </button>
          </footer>
        </div>
      </div>

      {/* Form dialog for editing */}
      {editingVar !== null && editingIndex !== null && (
        <VariableForm
          initial={editingVar}
          existingNames={existingNames.filter((_, i) => i !== editingIndex)}
          onSave={(v) => handleEdit(editingIndex, v)}
          onCancel={() => setEditingIndex(null)}
        />
      )}

      {/* Form dialog for adding */}
      {addingNew && (
        <VariableForm
          initial={emptyVariable()}
          existingNames={existingNames}
          onSave={handleAdd}
          onCancel={() => setAddingNew(false)}
        />
      )}
    </>
  )
}
