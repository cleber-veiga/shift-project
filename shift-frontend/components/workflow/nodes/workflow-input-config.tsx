"use client"

import { LogIn } from "lucide-react"

import type { WorkflowIOSchema, WorkflowParam } from "@/lib/api/workflow-versions"

const IDENTIFIER_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/

interface WorkflowInputConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
  ioSchema?: WorkflowIOSchema
}

export function WorkflowInputConfig({ data, onUpdate, ioSchema }: WorkflowInputConfigProps) {
  const outputField = (data.output_field as string) ?? "data"
  const isValid = IDENTIFIER_PATTERN.test(outputField)
  const mockInputs = (data.mock_inputs as Record<string, unknown> | undefined) ?? {}
  const inputs = ioSchema?.inputs ?? []

  function update(patch: Record<string, unknown>) {
    onUpdate({ ...data, ...patch })
  }

  function updateMock(name: string, value: unknown) {
    const next = { ...mockInputs, [name]: value }
    update({ mock_inputs: next })
  }

  function clearMock(name: string) {
    const next = { ...mockInputs }
    delete next[name]
    update({ mock_inputs: next })
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-dashed border-emerald-500/30 bg-emerald-500/5 p-3">
        <div className="mb-1.5 flex items-center gap-2">
          <LogIn className="size-3.5 text-emerald-600 dark:text-emerald-400" />
          <p className="text-xs font-medium text-emerald-700 dark:text-emerald-300">
            Entrada do Workflow
          </p>
        </div>
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          Este nó expõe os dados recebidos pelo workflow quando chamado via{" "}
          <code className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]">
            call_workflow
          </code>
          . Os inputs declarados no <span className="font-semibold">io_schema</span>{" "}
          do workflow ficam disponíveis no campo{" "}
          <code className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]">
            {outputField || "…"}
          </code>
          .
        </p>
      </div>

      <div className="space-y-1.5">
        <label
          htmlFor="workflow-input-output-field"
          className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground"
        >
          Campo de saída
        </label>
        <input
          id="workflow-input-output-field"
          type="text"
          value={outputField}
          onChange={(e) => update({ output_field: e.target.value })}
          placeholder="data"
          aria-invalid={!isValid}
          className={`h-8 w-full rounded-md border bg-background px-2.5 font-mono text-xs outline-none focus:ring-1 ${
            isValid
              ? "border-input focus:ring-primary"
              : "border-destructive focus:ring-destructive"
          }`}
        />
        {!isValid && (
          <p className="text-[10px] text-destructive">
            Nome inválido. Use apenas letras, números e underscore (não pode começar
            com número).
          </p>
        )}
        <p className="text-[10px] text-muted-foreground">
          Nome do campo exposto downstream com o payload completo recebido do
          workflow pai.
        </p>
      </div>

      <div className="space-y-2 rounded-lg border border-border bg-muted/30 p-3">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Mock inputs (teste)
          </p>
          <p className="text-[10px] leading-relaxed text-muted-foreground">
            Valores enviados apenas ao executar este workflow isoladamente pelo
            botão de teste. Quando chamado via{" "}
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]">
              call_workflow
            </code>
            , o pai sobrescreve estes valores.
          </p>
        </div>

        {inputs.length === 0 ? (
          <p className="text-[10px] italic text-muted-foreground">
            Declare inputs no Schema de I/O do workflow para preencher valores de
            teste aqui.
          </p>
        ) : (
          <div className="space-y-2">
            {inputs.map((param) => (
              <MockInputRow
                key={param.name}
                param={param}
                value={mockInputs[param.name]}
                onChange={(v) => updateMock(param.name, v)}
                onClear={() => clearMock(param.name)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

interface MockInputRowProps {
  param: WorkflowParam
  value: unknown
  onChange: (value: unknown) => void
  onClear: () => void
}

function MockInputRow({ param, value, onChange, onClear }: MockInputRowProps) {
  const isSet = value !== undefined
  const stringValue = toStringValue(value, param.type)

  function handleChange(raw: string) {
    if (raw === "" && !param.required) {
      onClear()
      return
    }
    onChange(parseValue(raw, param.type))
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <label className="font-mono text-[11px] text-foreground">
          {param.name}
          {param.required && <span className="ml-1 text-destructive">*</span>}
          <span className="ml-1.5 text-[10px] text-muted-foreground">
            ({param.type})
          </span>
        </label>
        {isSet && (
          <button
            type="button"
            onClick={onClear}
            className="text-[10px] text-muted-foreground hover:text-foreground"
          >
            limpar
          </button>
        )}
      </div>
      {param.type === "boolean" ? (
        <select
          value={stringValue}
          onChange={(e) => handleChange(e.target.value)}
          className="h-7 w-full rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary"
        >
          <option value="">—</option>
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      ) : param.type === "object" || param.type === "array" ? (
        <textarea
          value={stringValue}
          onChange={(e) => handleChange(e.target.value)}
          placeholder={param.type === "array" ? "[]" : "{}"}
          rows={3}
          className="w-full resize-y rounded-md border border-input bg-background px-2 py-1 font-mono text-[11px] outline-none focus:ring-1 focus:ring-primary"
        />
      ) : (
        <input
          type={param.type === "integer" || param.type === "number" ? "number" : "text"}
          value={stringValue}
          onChange={(e) => handleChange(e.target.value)}
          placeholder={param.description ?? ""}
          className="h-7 w-full rounded-md border border-input bg-background px-2 font-mono text-xs outline-none focus:ring-1 focus:ring-primary"
        />
      )}
      {param.description && (
        <p className="text-[10px] text-muted-foreground">{param.description}</p>
      )}
    </div>
  )
}

function toStringValue(value: unknown, type: WorkflowParam["type"]): string {
  if (value === undefined || value === null) return ""
  if (type === "object" || type === "array") {
    try {
      return JSON.stringify(value, null, 2)
    } catch {
      return String(value)
    }
  }
  return String(value)
}

function parseValue(raw: string, type: WorkflowParam["type"]): unknown {
  if (type === "integer") {
    const n = parseInt(raw, 10)
    return Number.isNaN(n) ? raw : n
  }
  if (type === "number") {
    const n = Number(raw)
    return Number.isNaN(n) ? raw : n
  }
  if (type === "boolean") {
    return raw === "true"
  }
  if (type === "object" || type === "array") {
    try {
      return JSON.parse(raw)
    } catch {
      return raw
    }
  }
  return raw
}
