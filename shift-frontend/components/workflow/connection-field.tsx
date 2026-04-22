"use client"

import { useState } from "react"
import { SlidersHorizontal } from "lucide-react"
import { cn } from "@/lib/utils"
import { useWorkflowVariablesContext } from "@/lib/workflow/workflow-variables-context"
import { migrateLegacySqlParameter } from "@/lib/workflow/parameter-value"
import { ValueInput } from "@/components/workflow/value-input/ValueInput"

// ─── ConnectionField ───────────────────────────────────────────────────────────
//
// Substitui VariableRefInput para campos connection_id.
// Modo direto  → renderiza children (o picker visual com badge de DB).
// Modo variável → renderiza ValueInput com suporte a {{vars.X}}.
// O toggle aparece somente quando há variáveis do tipo "connection" no workflow.
// O valor salvo em data.connection_id permanece string (UUID ou "{{vars.X}}").

interface ConnectionFieldProps {
  value: string
  onChange: (v: string) => void
  label?: string
  children: React.ReactNode
}

export function ConnectionField({
  value,
  onChange,
  label,
  children,
}: ConnectionFieldProps) {
  const { variables } = useWorkflowVariablesContext()
  const connVars = variables.filter((v) => v.type === "connection")

  const [varMode, setVarMode] = useState(() => value.startsWith("{{"))

  function switchToDirect() {
    setVarMode(false)
    if (value.startsWith("{{")) onChange("")
  }

  function switchToVar() {
    setVarMode(true)
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1">
        {label && (
          <span className="flex-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            {label}
          </span>
        )}
        {connVars.length > 0 && (
          <div className="ml-auto flex rounded border border-border bg-background">
            <button
              type="button"
              onClick={switchToDirect}
              className={cn(
                "px-2 py-0.5 text-[10px] font-medium transition-colors",
                !varMode
                  ? "bg-accent text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              Direto
            </button>
            <button
              type="button"
              onClick={switchToVar}
              className={cn(
                "flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium transition-colors",
                varMode
                  ? "bg-accent text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <SlidersHorizontal className="size-2.5" />
              Variável
            </button>
          </div>
        )}
      </div>

      {varMode ? (
        <ValueInput
          value={migrateLegacySqlParameter(value)}
          onChange={(pv) =>
            onChange(pv.mode === "fixed" ? pv.value : pv.template)
          }
          upstreamFields={[]}
          allowTransforms={false}
          allowVariables={true}
          placeholder="{{vars.conexao}}"
          size="sm"
        />
      ) : (
        children
      )}
    </div>
  )
}
