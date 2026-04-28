"use client"

import { CircleCheck, CircleX, Loader2 } from "lucide-react"
import type { DiagnosticStep } from "@/lib/auth"

const STAGE_LABELS: Record<DiagnosticStep["stage"], string> = {
  dns: "DNS",
  tcp: "Conexão TCP",
  greeting: "Resposta Firebird",
  auth_query: "Autenticação + ping",
  test: "Teste de conexão",
}

export interface DiagnosticPanelProps {
  steps: DiagnosticStep[]
  running?: boolean
}

export function DiagnosticPanel({ steps, running = false }: DiagnosticPanelProps) {
  if (!running && steps.length === 0) return null

  const failureIndex = steps.findIndex((s) => !s.ok)
  const overallOk = !running && failureIndex === -1 && steps.length > 0
  const failure = failureIndex >= 0 ? steps[failureIndex] : null

  return (
    <div
      role="status"
      aria-live="polite"
      className={`rounded-md border px-3 py-2.5 text-[12px] ${
        overallOk
          ? "border-emerald-500/30 bg-emerald-500/5"
          : failure
            ? "border-destructive/30 bg-destructive/5"
            : "border-border bg-muted/40"
      }`}
    >
      {/* Cabeçalho */}
      <p className="mb-2 text-[11px] font-medium text-foreground/80">
        {running
          ? "Testando conexão…"
          : overallOk
            ? "✓ Conexão bem-sucedida"
            : "Falha na conexão"}
      </p>

      {/* Lista de etapas */}
      <ul className="space-y-1">
        {steps.map((step, idx) => {
          const isFailed = !step.ok
          const Icon = isFailed ? CircleX : CircleCheck
          return (
            <li
              key={`${step.stage}-${idx}`}
              className={`flex items-center justify-between gap-2 rounded px-1.5 py-0.5 ${
                isFailed ? "text-destructive" : "text-foreground/80"
              }`}
            >
              <span className="flex items-center gap-1.5">
                <Icon
                  className="size-3.5 shrink-0"
                  aria-label={isFailed ? "Falhou" : "OK"}
                />
                <span>{STAGE_LABELS[step.stage]}</span>
              </span>
              {step.latency_ms !== null && (
                <span className="text-[10px] text-muted-foreground">
                  {step.latency_ms}ms
                </span>
              )}
            </li>
          )
        })}
        {running && (
          <li className="flex items-center gap-1.5 px-1.5 py-0.5 text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" aria-label="Em progresso" />
            <span>Aguardando próxima etapa…</span>
          </li>
        )}
      </ul>

      {/* Hint de falha */}
      {failure && failure.hint && (
        <div className="mt-2 rounded border border-destructive/30 bg-destructive/10 px-2.5 py-2">
          <p className="text-[12px] text-destructive">{failure.hint}</p>
          {failure.error_msg && failure.error_msg !== failure.hint && (
            <details className="mt-1.5">
              <summary className="cursor-pointer text-[10px] text-muted-foreground hover:text-foreground">
                Detalhes técnicos
              </summary>
              <pre className="mt-1 whitespace-pre-wrap break-all text-[10px] text-muted-foreground">
                {failure.error_msg}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  )
}
