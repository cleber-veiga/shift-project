"use client"

import { BanIcon, KeyRound, Loader2 } from "lucide-react"
import type { AgentApiKey } from "@/lib/auth"

function formatDate(iso: string | null | undefined) {
  if (!iso) return "—"
  try {
    return new Intl.DateTimeFormat("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso))
  } catch {
    return iso
  }
}

function getKeyStatus(k: AgentApiKey): "ativa" | "revogada" | "expirada" {
  if (k.revoked_at) return "revogada"
  if (k.expires_at && new Date(k.expires_at) < new Date()) return "expirada"
  return "ativa"
}

function StatusBadge({ keyRow }: { keyRow: AgentApiKey }) {
  const status = getKeyStatus(keyRow)
  if (status === "revogada") {
    return (
      <span className="inline-flex rounded bg-muted px-2 py-0.5 text-[10px] font-medium uppercase text-muted-foreground">
        Revogada
      </span>
    )
  }
  if (status === "expirada") {
    return (
      <span className="inline-flex rounded bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium uppercase text-amber-600 dark:text-amber-400">
        Expirada
      </span>
    )
  }
  return (
    <span className="inline-flex rounded bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium uppercase text-emerald-600 dark:text-emerald-400">
      Ativa
    </span>
  )
}

function ToolsBadges({ tools }: { tools: string[] }) {
  if (tools.includes("*")) {
    return (
      <span
        className="inline-flex rounded bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary"
        title="Todas as tools liberadas"
      >
        todas
      </span>
    )
  }
  const visible = tools.slice(0, 3)
  const remaining = tools.length - visible.length
  return (
    <div className="flex flex-wrap gap-1">
      {visible.map((t) => (
        <span
          key={t}
          className="inline-flex rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
          title={t}
        >
          {t}
        </span>
      ))}
      {remaining > 0 && (
        <span
          className="inline-flex rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
          title={tools.slice(3).join(", ")}
        >
          +{remaining}
        </span>
      )}
    </div>
  )
}

interface ApiKeysListProps {
  keys: AgentApiKey[]
  isLoading: boolean
  error: string | null
  canManage: boolean
  onRevoke: (key: AgentApiKey) => void
}

export function ApiKeysList({ keys, isLoading, error, canManage, onRevoke }: ApiKeysListProps) {
  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> Carregando chaves...
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-destructive/30 bg-card">
        <p className="text-sm text-destructive">{error}</p>
      </div>
    )
  }

  if (keys.length === 0) {
    return (
      <div className="flex h-40 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border bg-card">
        <KeyRound className="size-8 text-muted-foreground/30" />
        <div className="text-center">
          <p className="text-sm font-medium text-foreground">Nenhuma chave criada</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Crie uma chave para conectar o Claude Desktop ou n8n a este projeto.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="overflow-auto rounded-xl border border-border bg-card shadow-sm">
      <div className="grid min-w-[860px] grid-cols-[1fr_200px_150px_130px_110px_80px] items-center border-b border-border px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
        <span>Chave</span>
        <span>Tools permitidas</span>
        <span>Último uso</span>
        <span>Expira em</span>
        <span>Status</span>
        <span className="text-right">Ações</span>
      </div>

      <div className="divide-y divide-border">
        {keys.map((k) => {
          const status = getKeyStatus(k)
          const isInactive = status !== "ativa"
          return (
            <div
              key={k.id}
              className={`grid min-w-[860px] grid-cols-[1fr_200px_150px_130px_110px_80px] items-center px-4 py-4 transition-colors hover:bg-muted/10 ${
                isInactive ? "opacity-60" : ""
              }`}
            >
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <KeyRound className="size-4" />
                </div>
                <div className="min-w-0">
                  <p className="truncate text-[13px] font-semibold text-foreground">{k.name}</p>
                  <p className="truncate font-mono text-[11px] text-muted-foreground">
                    {k.prefix}…
                  </p>
                </div>
              </div>

              <div>
                <ToolsBadges tools={k.allowed_tools} />
              </div>

              <p className="text-[12px] text-foreground">{formatDate(k.last_used_at)}</p>
              <p className="text-[12px] text-foreground">{formatDate(k.expires_at)}</p>

              <div>
                <StatusBadge keyRow={k} />
              </div>

              <div className="flex items-center justify-end">
                {canManage && !k.revoked_at ? (
                  <button
                    type="button"
                    onClick={() => onRevoke(k)}
                    className="rounded p-2 text-amber-600/80 transition-colors hover:bg-muted hover:text-amber-600"
                    aria-label={`Revogar chave ${k.name}`}
                    title="Revogar chave"
                  >
                    <BanIcon className="size-4" />
                  </button>
                ) : null}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
