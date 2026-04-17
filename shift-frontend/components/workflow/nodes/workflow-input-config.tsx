"use client"

import { LogIn } from "lucide-react"

const IDENTIFIER_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/

interface WorkflowInputConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

export function WorkflowInputConfig({ data, onUpdate }: WorkflowInputConfigProps) {
  const outputField = (data.output_field as string) ?? "data"
  const isValid = IDENTIFIER_PATTERN.test(outputField)

  function update(patch: Record<string, unknown>) {
    onUpdate({ ...data, ...patch })
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
    </div>
  )
}
