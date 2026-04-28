"use client"

import { useEffect, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import Link from "next/link"
import { CheckCircle2, Loader2, Mail, ShieldAlert, UserPlus, XCircle } from "lucide-react"
import { acceptInvitation, getInvitationByToken, getValidSession, type InvitationDetail } from "@/lib/auth"
import { cn } from "@/lib/utils"
import { MorphLoader } from "@/components/ui/morph-loader"
import { ShiftBrand } from "@/components/ui/shift-brand"

const SCOPE_LABELS: Record<string, string> = {
  ORGANIZATION: "Organizacao",
  WORKSPACE: "Workspace",
  PROJECT: "Projeto",
}

export default function InvitePage() {
  const { token } = useParams<{ token: string }>()
  const router = useRouter()
  const [invitation, setInvitation] = useState<InvitationDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [accepting, setAccepting] = useState(false)
  const [error, setError] = useState("")
  const [accepted, setAccepted] = useState(false)
  const [isLoggedIn, setIsLoggedIn] = useState(false)

  useEffect(() => {
    async function load() {
      try {
        const [detail, session] = await Promise.all([
          getInvitationByToken(token),
          getValidSession(),
        ])
        setInvitation(detail)
        setIsLoggedIn(!!session)
      } catch {
        setError("Convite nao encontrado ou invalido.")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [token])

  const handleAccept = async () => {
    setAccepting(true)
    setError("")
    try {
      const result = await acceptInvitation(token)
      if (result.success) {
        setAccepted(true)
        setTimeout(() => router.push("/dashboard"), 2000)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao aceitar convite.")
    } finally {
      setAccepting(false)
    }
  }

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-[#0a0a0a]">
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage: `
            linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)
          `,
          backgroundSize: "64px 64px",
        }}
      />
      <div className="pointer-events-none absolute left-1/2 top-0 h-[300px] w-[600px] -translate-x-1/2 rounded-full bg-white/[0.03] blur-3xl" />

      <div className="relative z-10 w-full max-w-md px-4">
        <div className="mb-8 flex flex-col items-center gap-5">
          <ShiftBrand size={52} />
        </div>

        {loading ? (
          <div className="flex flex-col items-center gap-3 py-12">
            <Loader2 className="size-6 animate-spin text-neutral-400" />
            <p className="text-sm text-neutral-500">Carregando convite...</p>
          </div>
        ) : error && !invitation ? (
          <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-6 text-center">
            <XCircle className="mx-auto mb-3 size-10 text-red-400" />
            <h2 className="text-lg font-semibold text-white">Convite invalido</h2>
            <p className="mt-2 text-sm text-neutral-400">{error}</p>
            <Link
              href="/login"
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-white/10 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-white/20"
            >
              Ir para Login
            </Link>
          </div>
        ) : accepted ? (
          <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-6 text-center">
            <CheckCircle2 className="mx-auto mb-3 size-10 text-emerald-400" />
            <h2 className="text-lg font-semibold text-white">Convite aceito!</h2>
            <p className="mt-2 text-sm text-neutral-400">Redirecionando para o painel...</p>
          </div>
        ) : invitation?.is_expired ? (
          <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-6 text-center">
            <ShieldAlert className="mx-auto mb-3 size-10 text-amber-400" />
            <h2 className="text-lg font-semibold text-white">Convite expirado</h2>
            <p className="mt-2 text-sm text-neutral-400">
              Este convite nao e mais valido. Solicite ao administrador que envie um novo convite.
            </p>
          </div>
        ) : invitation?.is_accepted ? (
          <div className="rounded-xl border border-blue-500/20 bg-blue-500/5 p-6 text-center">
            <CheckCircle2 className="mx-auto mb-3 size-10 text-blue-400" />
            <h2 className="text-lg font-semibold text-white">Convite ja aceito</h2>
            <p className="mt-2 text-sm text-neutral-400">
              Este convite ja foi utilizado.
            </p>
            <Link
              href="/login"
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-white/10 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-white/20"
            >
              Ir para Login
            </Link>
          </div>
        ) : invitation ? (
          <div className="rounded-xl border border-white/10 bg-white/[0.02] p-6">
            <div className="mb-6 flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-full bg-white/5">
                <Mail className="size-5 text-neutral-400" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-white">Voce foi convidado</h2>
                <p className="text-sm text-neutral-500">para o {SCOPE_LABELS[invitation.scope] ?? invitation.scope}</p>
              </div>
            </div>

            <div className="space-y-3 rounded-lg border border-white/5 bg-white/[0.02] p-4">
              <div className="flex items-center justify-between">
                <span className="text-xs text-neutral-500">{SCOPE_LABELS[invitation.scope] ?? "Escopo"}</span>
                <span className="text-sm font-medium text-white">{invitation.scope_name}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-neutral-500">Papel</span>
                <span className="inline-flex rounded bg-white/10 px-2 py-0.5 text-xs font-medium text-white">
                  {invitation.role}
                </span>
              </div>
              {invitation.invited_by_name ? (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-neutral-500">Convidado por</span>
                  <span className="text-sm text-neutral-300">{invitation.invited_by_name}</span>
                </div>
              ) : null}
              <div className="flex items-center justify-between">
                <span className="text-xs text-neutral-500">Email</span>
                <span className="text-sm text-neutral-300">{invitation.email}</span>
              </div>
            </div>

            {error ? <p className="mt-4 text-sm text-red-400">{error}</p> : null}

            {isLoggedIn ? (
              <button
                type="button"
                onClick={handleAccept}
                disabled={accepting}
                className={cn(
                  "mt-6 flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-all",
                  "bg-white text-neutral-900",
                  "hover:bg-neutral-100 active:bg-neutral-200",
                  "disabled:cursor-not-allowed disabled:opacity-60",
                )}
              >
                {accepting ? (
                  <MorphLoader className="size-4" />
                ) : (
                  <>
                    <UserPlus className="size-4" />
                    Aceitar Convite
                  </>
                )}
              </button>
            ) : (
              <div className="mt-6 space-y-3">
                <p className="text-center text-xs text-neutral-500">
                  Voce precisa estar logado para aceitar este convite.
                </p>
                <div className="grid grid-cols-2 gap-3">
                  <Link
                    href={`/login?redirect=/invite/${token}`}
                    className="flex items-center justify-center rounded-lg bg-white px-4 py-2.5 text-sm font-semibold text-neutral-900 transition-colors hover:bg-neutral-100"
                  >
                    Fazer Login
                  </Link>
                  <Link
                    href={`/register?redirect=/invite/${token}`}
                    className="flex items-center justify-center rounded-lg border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-white/10"
                  >
                    Criar Conta
                  </Link>
                </div>
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  )
}
