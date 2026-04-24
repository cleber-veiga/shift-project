"use client"

import { useMemo } from "react"
import { Plus, Trash2 } from "lucide-react"
import {
  WORKFLOW_PARAM_TYPES,
  type WorkflowIOSchema,
  type WorkflowParam,
  type WorkflowParamType,
} from "@/lib/api/workflow-versions"

const IDENTIFIER_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/

interface IoSchemaEditorProps {
  value: WorkflowIOSchema
  onChange: (value: WorkflowIOSchema) => void
}

type ParamSection = "inputs" | "outputs"

function emptyParam(): WorkflowParam {
  return {
    name: "",
    type: "string",
    required: true,
    default: undefined,
    description: null,
  }
}

function parseDefault(raw: string, type: WorkflowParamType): unknown {
  if (raw === "") return undefined
  if (type === "object" || type === "array") {
    try {
      return JSON.parse(raw)
    } catch {
      return raw
    }
  }
  if (type === "integer") {
    const n = parseInt(raw, 10)
    return Number.isNaN(n) ? raw : n
  }
  if (type === "number") {
    const n = Number(raw)
    return Number.isNaN(n) ? raw : n
  }
  if (type === "boolean") {
    if (raw === "true") return true
    if (raw === "false") return false
    return raw
  }
  return raw
}

function defaultToString(value: unknown): string {
  if (value === undefined || value === null) return ""
  if (typeof value === "string") return value
  if (typeof value === "object") return JSON.stringify(value)
  return String(value)
}

export function IoSchemaEditor({ value, onChange }: IoSchemaEditorProps) {
  function updateSection(section: ParamSection, rows: WorkflowParam[]) {
    onChange({ ...value, [section]: rows })
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-y-auto p-4 md:grid-cols-2">
        <ParamSectionEditor
          label="Inputs"
          description="Parâmetros que este workflow recebe quando chamado via call_workflow."
          params={value.inputs}
          onChange={(rows) => updateSection("inputs", rows)}
        />
        <ParamSectionEditor
          label="Outputs"
          description="Valores que este workflow devolve ao workflow pai."
          params={value.outputs}
          onChange={(rows) => updateSection("outputs", rows)}
        />
      </div>
    </div>
  )
}

function ParamSectionEditor({
  label,
  description,
  params,
  onChange,
}: {
  label: string
  description: string
  params: WorkflowParam[]
  onChange: (params: WorkflowParam[]) => void
}) {
  const names = useMemo(() => params.map((p) => p.name.trim()), [params])
  const duplicates = useMemo(
    () => new Set(names.filter((n, i) => n && names.indexOf(n) !== i)),
    [names],
  )

  function addRow() {
    onChange([...params, emptyParam()])
  }

  function updateRow(index: number, patch: Partial<WorkflowParam>) {
    onChange(params.map((p, i) => (i === index ? { ...p, ...patch } : p)))
  }

  function removeRow(index: number) {
    onChange(params.filter((_, i) => i !== index))
  }

  return (
    <section className="flex min-h-0 flex-col rounded-lg border border-border bg-card">
      <header className="flex items-center justify-between border-b border-border px-3 py-2">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-foreground">
            {label}
          </h3>
          <p className="mt-0.5 text-[10px] text-muted-foreground">{description}</p>
        </div>
        <button
          type="button"
          onClick={addRow}
          className="flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-[10px] font-medium text-foreground transition-colors hover:bg-muted"
        >
          <Plus className="size-3" />
          Adicionar {label === "Inputs" ? "input" : "output"}
        </button>
      </header>

      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {params.length === 0 ? (
          <p className="rounded-md border border-dashed border-border bg-muted/30 px-3 py-6 text-center text-[11px] text-muted-foreground">
            Nenhum {label.toLowerCase()} declarado.
          </p>
        ) : (
          params.map((param, i) => {
            const trimmedName = param.name.trim()
            const nameInvalid =
              !!trimmedName && !IDENTIFIER_PATTERN.test(trimmedName)
            const nameDuplicate = duplicates.has(trimmedName)
            const nameError = nameInvalid || nameDuplicate

            return (
              <div
                key={i}
                className="space-y-2 rounded-md border border-border bg-background p-2.5"
              >
                <div className="flex items-start gap-2">
                  <div className="flex-1 space-y-1">
                    <label className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      Nome
                    </label>
                    <input
                      type="text"
                      value={param.name}
                      onChange={(e) => updateRow(i, { name: e.target.value })}
                      placeholder="nome_parametro"
                      aria-invalid={nameError}
                      className={`h-7 w-full rounded-md border bg-background px-2 font-mono text-xs outline-none focus:ring-1 ${
                        nameError
                          ? "border-destructive focus:ring-destructive"
                          : "border-input focus:ring-primary"
                      }`}
                    />
                  </div>
                  <div className="w-32 space-y-1">
                    <label className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      Tipo
                    </label>
                    <select
                      value={param.type}
                      onChange={(e) =>
                        updateRow(i, {
                          type: e.target.value as WorkflowParamType,
                        })
                      }
                      className="h-7 w-full rounded-md border border-input bg-background px-1.5 text-xs outline-none focus:ring-1 focus:ring-primary"
                    >
                      {WORKFLOW_PARAM_TYPES.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </div>
                  <button
                    type="button"
                    aria-label="Remover"
                    onClick={() => removeRow(i)}
                    className="mt-5 flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2 className="size-3" />
                  </button>
                </div>

                <div className="flex items-center gap-4">
                  <label className="flex items-center gap-1.5 text-[11px] text-foreground">
                    <input
                      type="checkbox"
                      checked={param.required ?? true}
                      onChange={(e) =>
                        updateRow(i, { required: e.target.checked })
                      }
                      className="size-3.5 rounded border-input accent-primary"
                    />
                    Obrigatório
                  </label>
                  <div className="flex-1 space-y-1">
                    <label className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      Default
                    </label>
                    <input
                      type="text"
                      value={defaultToString(param.default)}
                      onChange={(e) =>
                        updateRow(i, {
                          default: parseDefault(e.target.value, param.type),
                        })
                      }
                      placeholder={
                        param.type === "object"
                          ? '{"chave": "valor"}'
                          : param.type === "array"
                            ? "[1, 2, 3]"
                            : "(opcional)"
                      }
                      className="h-7 w-full rounded-md border border-input bg-background px-2 font-mono text-xs outline-none focus:ring-1 focus:ring-primary"
                    />
                  </div>
                </div>

                <div className="space-y-1">
                  <label className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                    Descrição
                  </label>
                  <textarea
                    value={param.description ?? ""}
                    onChange={(e) =>
                      updateRow(i, {
                        description: e.target.value === "" ? null : e.target.value,
                      })
                    }
                    placeholder="Descrição curta do parâmetro…"
                    rows={2}
                    className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>

                {nameInvalid && (
                  <p className="text-[10px] text-destructive">
                    Nome inválido. Use apenas letras, números e underscore (não
                    pode começar com número).
                  </p>
                )}
                {nameDuplicate && !nameInvalid && (
                  <p className="text-[10px] text-destructive">
                    Nome duplicado nesta seção.
                  </p>
                )}
              </div>
            )
          })
        )}
      </div>
    </section>
  )
}

