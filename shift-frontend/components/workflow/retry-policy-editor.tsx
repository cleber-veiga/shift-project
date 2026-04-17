"use client"

import { useState } from "react"
import { ChevronDown, ChevronRight, Clock, RefreshCw, X } from "lucide-react"

export interface RetryPolicyValue {
  max_attempts: number
  backoff_strategy: "none" | "fixed" | "exponential"
  backoff_seconds: number
  retry_on: string[]
}

interface RetryPolicyEditorProps {
  value: RetryPolicyValue | null
  onChange: (value: RetryPolicyValue | null) => void
  disabled?: boolean
}

const DEFAULT_POLICY: RetryPolicyValue = {
  max_attempts: 3,
  backoff_strategy: "exponential",
  backoff_seconds: 1.0,
  retry_on: [],
}

const STRATEGY_OPTIONS: { value: RetryPolicyValue["backoff_strategy"]; label: string }[] = [
  { value: "none", label: "Sem espera" },
  { value: "fixed", label: "Fixo" },
  { value: "exponential", label: "Exponencial" },
]

function computeDelays(policy: RetryPolicyValue): number[] {
  const delays: number[] = []
  const retries = Math.max(0, policy.max_attempts - 1)
  for (let i = 0; i < retries; i++) {
    if (policy.backoff_strategy === "none") {
      delays.push(0)
    } else if (policy.backoff_strategy === "fixed") {
      delays.push(policy.backoff_seconds)
    } else {
      delays.push(policy.backoff_seconds * Math.pow(2, i))
    }
  }
  return delays
}

function formatSeconds(v: number): string {
  if (v === 0) return "0s"
  if (v < 1) return `${v.toFixed(1)}s`
  if (Number.isInteger(v)) return `${v}s`
  return `${v.toFixed(1)}s`
}

export function RetryPolicyEditor({ value, onChange, disabled }: RetryPolicyEditorProps) {
  const [expanded, setExpanded] = useState(false)
  const enabled = value !== null
  const effective = value ?? DEFAULT_POLICY

  function patch(update: Partial<RetryPolicyValue>) {
    onChange({ ...effective, ...update })
  }

  function toggle() {
    if (disabled) return
    if (enabled) {
      onChange(null)
    } else {
      onChange({ ...DEFAULT_POLICY })
      setExpanded(true)
    }
  }

  function addRetryOn(raw: string) {
    const v = raw.trim()
    if (!v) return
    if (effective.retry_on.includes(v)) return
    patch({ retry_on: [...effective.retry_on, v] })
  }

  function removeRetryOn(idx: number) {
    patch({ retry_on: effective.retry_on.filter((_, i) => i !== idx) })
  }

  const delays = enabled ? computeDelays(effective) : []
  const totalDelay = delays.reduce((s, d) => s + d, 0)
  const slowWarning = totalDelay > 30

  return (
    <div className="rounded-md border border-border bg-card">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left transition-colors hover:bg-muted/40"
      >
        <div className="flex items-center gap-2">
          {expanded ? (
            <ChevronDown className="size-3.5 text-muted-foreground" />
          ) : (
            <ChevronRight className="size-3.5 text-muted-foreground" />
          )}
          <RefreshCw className="size-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold text-foreground">Retry em falha</span>
        </div>
        <span
          className={`rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${
            enabled
              ? "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-400"
              : "border-border bg-muted/40 text-muted-foreground"
          }`}
        >
          {enabled
            ? `${effective.max_attempts} tentativa${effective.max_attempts === 1 ? "" : "s"}`
            : "Desativado"}
        </span>
      </button>

      {expanded && (
        <div className="space-y-3 border-t border-border p-3">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={enabled}
              onChange={toggle}
              disabled={disabled}
              className="size-3.5 rounded border-input accent-primary"
            />
            <span className="text-xs text-foreground">Habilitar retry em falha</span>
          </label>

          {enabled && (
            <>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <label className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                    Tentativas (1-10)
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={effective.max_attempts}
                    onChange={(e) => {
                      const n = parseInt(e.target.value, 10)
                      if (Number.isNaN(n)) return
                      patch({ max_attempts: Math.min(10, Math.max(1, n)) })
                    }}
                    className="h-7 w-full rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                    Estratégia
                  </label>
                  <select
                    value={effective.backoff_strategy}
                    onChange={(e) =>
                      patch({
                        backoff_strategy: e.target.value as RetryPolicyValue["backoff_strategy"],
                      })
                    }
                    className="h-7 w-full rounded-md border border-input bg-background px-1.5 text-xs outline-none focus:ring-1 focus:ring-primary"
                  >
                    {STRATEGY_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Backoff (segundos, 0.1-300)
                </label>
                <input
                  type="number"
                  min={0.1}
                  max={300}
                  step={0.1}
                  disabled={effective.backoff_strategy === "none"}
                  value={effective.backoff_seconds}
                  onChange={(e) => {
                    const n = Number(e.target.value)
                    if (Number.isNaN(n)) return
                    patch({ backoff_seconds: Math.min(300, Math.max(0.1, n)) })
                  }}
                  className="h-7 w-full rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
                />
                <p className="text-[10px] text-muted-foreground">
                  {effective.backoff_strategy === "exponential"
                    ? "Base multiplicada por 2 a cada tentativa."
                    : effective.backoff_strategy === "fixed"
                      ? "Mesma espera entre todas as tentativas."
                      : "Sem espera entre tentativas."}
                </p>
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Filtrar erros (opcional)
                </label>
                <RetryOnInput
                  values={effective.retry_on}
                  onAdd={addRetryOn}
                  onRemove={removeRetryOn}
                />
                <p className="text-[10px] text-muted-foreground">
                  Só tenta de novo se a mensagem de erro conter uma destas substrings.
                  Vazio = tenta em qualquer erro.
                </p>
              </div>

              {delays.length > 0 && (
                <div
                  className={`rounded-md border p-2 ${
                    slowWarning
                      ? "border-amber-500/30 bg-amber-500/5"
                      : "border-border bg-muted/30"
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <Clock
                      className={`size-3 ${
                        slowWarning ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"
                      }`}
                    />
                    <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      Preview de tempo
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-[11px] text-foreground">
                    {delays.map((d, i) => (
                      <span key={i}>
                        {i > 0 ? " → " : ""}
                        tentativa {i + 2}: +{formatSeconds(d)}
                      </span>
                    ))}
                  </p>
                  <p className="mt-1 text-[10px] text-muted-foreground">
                    Atraso total acumulado:{" "}
                    <span
                      className={
                        slowWarning
                          ? "font-semibold text-amber-700 dark:text-amber-400"
                          : "font-semibold text-foreground"
                      }
                    >
                      {formatSeconds(totalDelay)}
                    </span>
                    {slowWarning ? " (pode atrasar o fluxo)" : ""}
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

function RetryOnInput({
  values,
  onAdd,
  onRemove,
}: {
  values: string[]
  onAdd: (raw: string) => void
  onRemove: (idx: number) => void
}) {
  const [draft, setDraft] = useState("")

  function commit() {
    if (!draft.trim()) return
    onAdd(draft)
    setDraft("")
  }

  return (
    <div className="flex flex-wrap items-center gap-1 rounded-md border border-input bg-background p-1">
      {values.map((v, i) => (
        <span
          key={`${v}-${i}`}
          className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-foreground"
        >
          {v}
          <button
            type="button"
            onClick={() => onRemove(i)}
            aria-label={`Remover ${v}`}
            className="text-muted-foreground transition-colors hover:text-destructive"
          >
            <X className="size-2.5" />
          </button>
        </span>
      ))}
      <input
        type="text"
        value={draft}
        onChange={(e) => {
          const next = e.target.value
          if (next.endsWith(",")) {
            onAdd(next.slice(0, -1))
            setDraft("")
          } else {
            setDraft(next)
          }
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault()
            commit()
          } else if (e.key === "Backspace" && !draft && values.length > 0) {
            onRemove(values.length - 1)
          }
        }}
        onBlur={commit}
        placeholder={values.length === 0 ? "timeout, connection reset..." : ""}
        className="min-w-[100px] flex-1 bg-transparent px-1 py-0.5 text-xs outline-none placeholder:text-muted-foreground"
      />
    </div>
  )
}
