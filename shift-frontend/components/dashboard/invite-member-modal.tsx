"use client"

import { useState } from "react"
import { Mail, UserPlus, X } from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

type RoleOption = { value: string; label: string }

const WORKSPACE_ROLES: RoleOption[] = [
  { value: "VIEWER", label: "Visualizador" },
  { value: "CONSULTANT", label: "Consultor" },
  { value: "MANAGER", label: "Gerente" },
]

const PROJECT_ROLES: RoleOption[] = [
  { value: "CLIENT", label: "Cliente" },
  { value: "EDITOR", label: "Editor" },
]

interface InviteMemberModalProps {
  open: boolean
  onClose: () => void
  onInvite: (email: string, role: string) => Promise<void>
  scope: "space" | "project"
}

export function InviteMemberModal({ open, onClose, onInvite, scope }: InviteMemberModalProps) {
  const [email, setEmail] = useState("")
  const [role, setRole] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const roles = scope === "space" ? WORKSPACE_ROLES : PROJECT_ROLES

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim() || !role) return

    setLoading(true)
    setError("")
    try {
      await onInvite(email.trim(), role)
      setEmail("")
      setRole("")
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao enviar convite.")
    } finally {
      setLoading(false)
    }
  }

  const handleClose = () => {
    if (loading) return
    setEmail("")
    setRole("")
    setError("")
    onClose()
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={handleClose} />

      <div
        role="dialog"
        aria-modal="true"
        className="relative z-10 w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-2xl"
      >
        <div className="mb-5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10">
              <UserPlus className="size-4 text-primary" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-foreground">Convidar Membro</h2>
              <p className="text-xs text-muted-foreground">
                {scope === "space" ? "Convide para o workspace" : "Convide para o projeto"}
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
              Email
            </label>
            <div className="relative">
              <Mail className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="email@exemplo.com"
                className="w-full rounded-lg border border-input bg-background py-2.5 pl-10 pr-3.5 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-2 focus:ring-ring/20"
                required
              />
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              Papel
            </label>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger className="w-full bg-background">
                <SelectValue placeholder="Selecione um papel" />
              </SelectTrigger>
              <SelectContent>
                {roles.map((r) => (
                  <SelectItem key={r.value} value={r.value}>
                    {r.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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
              disabled={loading || !email.trim() || !role}
              className="inline-flex items-center gap-2 rounded-lg bg-foreground px-4 py-2 text-sm font-semibold text-background transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? (
                <MorphLoader className="size-4" />
              ) : (
                <>
                  <UserPlus className="size-3.5" />
                  Enviar Convite
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
