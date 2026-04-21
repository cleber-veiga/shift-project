"use client"

import { useMemo, useState } from "react"
import { ChevronDown, SlidersHorizontal, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { useWorkflowVariablesContext } from "@/lib/workflow/workflow-variables-context"
import type { WorkflowVariableType } from "@/lib/workflow/types"

const VAR_RE = /^\{\{\s*vars\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$/

interface VariableRefInputProps {
  value: string
  onChange: (value: string) => void
  acceptedTypes: readonly WorkflowVariableType[]
  children: React.ReactNode
  label?: string
}

export function VariableRefInput({
  value,
  onChange,
  acceptedTypes,
  children,
  label,
}: VariableRefInputProps) {
  const { variables } = useWorkflowVariablesContext()

  const compatibleVars = useMemo(
    () => variables.filter((v) => acceptedTypes.includes(v.type)),
    [variables, acceptedTypes],
  )

  const isVarMode = VAR_RE.test(value ?? "")
  const [mode, setMode] = useState<"direct" | "variable">(isVarMode ? "variable" : "direct")
  const [showDropdown, setShowDropdown] = useState(false)

  const currentVarName = isVarMode ? VAR_RE.exec(value ?? "")?.[1] ?? null : null
  const currentVar = compatibleVars.find((v) => v.name === currentVarName) ?? null

  if (compatibleVars.length === 0) {
    return (
      <div className="space-y-1.5">
        {label && (
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            {label}
          </label>
        )}
        {children}
      </div>
    )
  }

  function switchToVariable() {
    setMode("variable")
    setShowDropdown(true)
  }

  function switchToDirect() {
    setMode("direct")
    setShowDropdown(false)
    if (isVarMode) onChange("")
  }

  function selectVar(name: string) {
    onChange(`{{vars.${name}}}`)
    setShowDropdown(false)
  }

  return (
    <div className="space-y-1.5">
      {/* Mode toggle strip */}
      <div className="flex items-center gap-1">
        {label && (
          <span className="flex-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            {label}
          </span>
        )}
        <div className="ml-auto flex rounded border border-border bg-background">
          <button
            type="button"
            onClick={switchToDirect}
            className={cn(
              "px-2 py-0.5 text-[10px] font-medium transition-colors",
              mode === "direct"
                ? "bg-accent text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            Valor direto
          </button>
          <button
            type="button"
            onClick={switchToVariable}
            className={cn(
              "flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium transition-colors",
              mode === "variable"
                ? "bg-accent text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <SlidersHorizontal className="size-2.5" />
            Variável
          </button>
        </div>
      </div>

      {mode === "variable" ? (
        <div className="relative">
          <button
            type="button"
            onClick={() => setShowDropdown((v) => !v)}
            className={cn(
              "flex h-9 w-full items-center gap-2 rounded-md border px-2.5 text-left text-xs transition-colors",
              currentVar ? "pr-8" : "",
              currentVar
                ? "border-violet-500/40 bg-violet-500/5 text-foreground"
                : "border-dashed border-border bg-muted/20 text-muted-foreground",
            )}
          >
            <SlidersHorizontal className="size-3.5 shrink-0 text-violet-500" />
            {currentVar ? (
              <>
                <span className="font-mono font-medium text-violet-700 dark:text-violet-400">
                  {`{{vars.${currentVar.name}}}`}
                </span>
                {currentVar.description && (
                  <span className="ml-1 truncate text-[10px] text-muted-foreground">
                    — {currentVar.description}
                  </span>
                )}
              </>
            ) : (
              <>
                <span>Selecionar variável...</span>
                <ChevronDown
                  className={cn(
                    "ml-auto size-3 shrink-0 transition-transform",
                    showDropdown && "rotate-180",
                  )}
                />
              </>
            )}
          </button>
          {currentVar && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                switchToDirect()
              }}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="Remover variável"
            >
              <X className="size-3" />
            </button>
          )}

          {showDropdown && (
            <div className="absolute left-0 right-0 top-10 z-30 overflow-hidden rounded-lg border border-border bg-card shadow-lg">
              <div className="max-h-48 overflow-y-auto p-1">
                {compatibleVars.map((v) => (
                  <button
                    key={v.name}
                    type="button"
                    onClick={() => selectVar(v.name)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-muted/60",
                      v.name === currentVarName && "bg-primary/5",
                    )}
                  >
                    <span className="rounded bg-violet-500/10 px-1.5 py-0.5 font-mono text-[10px] font-medium text-violet-700 dark:text-violet-400">
                      {`{{vars.${v.name}}}`}
                    </span>
                    {v.description && (
                      <span className="truncate text-[10px] text-muted-foreground">
                        {v.description}
                      </span>
                    )}
                    {v.required && (
                      <span className="ml-auto text-[9px] text-amber-600">obrigatória</span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        children
      )}
    </div>
  )
}
