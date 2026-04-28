"use client"

import { useEffect, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import Link from "next/link"
import { ShieldAlert, UserPlus, XCircle } from "lucide-react"
import {
  acceptInvitation,
  getInvitationByToken,
  getValidSession,
  type InvitationDetail,
} from "@/lib/auth"
import { MorphLoader } from "@/components/ui/morph-loader"
import {
  ArrowRight,
  AUTH_TOKENS,
  AuthShell,
  CheckIcon,
  PaperCard,
  PrimaryCta,
} from "@/components/auth/auth-shell"

const { ACCENT, BORDER_PAPER, INK, PAPER_INSET } = AUTH_TOKENS

const SCOPE_LABELS: Record<string, string> = {
  ORGANIZATION: "Organização",
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
        setError("Convite não encontrado ou inválido.")
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

  const heroEyebrow = "Convite"
  const heroTitle =
    accepted ? (
      <>
        Convite{" "}
        <em style={{ fontStyle: "italic", fontWeight: 500, color: ACCENT }}>aceito</em>.
      </>
    ) : invitation?.is_expired ? (
      <>
        Este convite{" "}
        <em style={{ fontStyle: "italic", fontWeight: 500, color: ACCENT }}>expirou</em>.
      </>
    ) : invitation?.is_accepted ? (
      <>
        Este convite{" "}
        <em style={{ fontStyle: "italic", fontWeight: 500, color: ACCENT }}>já foi usado</em>.
      </>
    ) : (
      <>
        Você foi{" "}
        <em style={{ fontStyle: "italic", fontWeight: 500, color: ACCENT }}>convidado</em>.
      </>
    )

  const heroBody =
    accepted
      ? "Tudo pronto. Estamos te direcionando para o painel."
      : invitation?.is_expired
      ? "Solicite ao administrador que envie um novo convite. O link tem validade limitada."
      : invitation?.is_accepted
      ? "Faça login para acessar a área compartilhada com você."
      : invitation
      ? `Para acessar ${SCOPE_LABELS[invitation.scope] ?? invitation.scope}, aceite o convite abaixo.`
      : "Estamos validando seu convite."

  return (
    <AuthShell
      heroEyebrow={heroEyebrow}
      heroTitle={heroTitle}
      heroBody={heroBody}
    >
      <PaperCard eyebrow="Convite recebido">
        {loading ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: 16,
              fontSize: 14,
              color: "#6b7280",
            }}
          >
            <MorphLoader className="size-5" /> Carregando convite...
          </div>
        ) : null}

        {!loading && error && !invitation ? (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 12,
              padding: 16,
              borderRadius: 8,
              background: "rgba(239,68,68,0.06)",
              border: "1px solid rgba(239,68,68,0.18)",
              color: INK,
              textAlign: "center",
            }}
          >
            <XCircle className="size-7" style={{ color: "#dc2626" }} />
            <p style={{ margin: 0, fontWeight: 600 }}>Convite inválido</p>
            <p style={{ margin: 0, fontSize: 13, color: "#6b7280" }}>{error}</p>
            <Link
              href="/login"
              style={{
                marginTop: 4,
                color: INK,
                fontWeight: 600,
                textDecoration: "none",
                borderBottom: `1px solid ${ACCENT}`,
                paddingBottom: 1,
              }}
            >
              Ir para login
            </Link>
          </div>
        ) : null}

        {!loading && accepted ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              padding: 16,
              background: "rgba(99,102,241,0.06)",
              border: "1px solid rgba(99,102,241,0.18)",
              borderRadius: 8,
              fontSize: 14,
              color: INK,
            }}
          >
            <span
              style={{
                width: 28,
                height: 28,
                borderRadius: "50%",
                background: ACCENT,
                color: "white",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                flex: "0 0 auto",
              }}
            >
              <CheckIcon size={14} />
            </span>
            Redirecionando para o painel...
          </div>
        ) : null}

        {!loading && invitation?.is_expired ? (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 12,
              padding: 16,
              borderRadius: 8,
              background: "rgba(245,158,11,0.06)",
              border: "1px solid rgba(245,158,11,0.18)",
              textAlign: "center",
              color: INK,
            }}
          >
            <ShieldAlert className="size-6" style={{ color: "#b45309" }} />
            <p style={{ margin: 0, fontWeight: 600 }}>Convite expirado</p>
            <p style={{ margin: 0, fontSize: 13, color: "#6b7280" }}>
              Solicite um novo convite ao administrador.
            </p>
          </div>
        ) : null}

        {!loading && invitation && !invitation.is_expired && !invitation.is_accepted && !accepted ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div
              style={{
                background: PAPER_INSET,
                borderRadius: 8,
                padding: 16,
                display: "flex",
                flexDirection: "column",
                gap: 10,
              }}
            >
              <Row label={SCOPE_LABELS[invitation.scope] ?? "Escopo"} value={invitation.scope_name} bold />
              <Row label="Papel" value={<RoleBadge role={invitation.role} />} />
              {invitation.invited_by_name ? (
                <Row label="Convidado por" value={invitation.invited_by_name} />
              ) : null}
              <Row label="E-mail" value={invitation.email} />
            </div>

            {error ? (
              <p style={{ margin: 0, fontSize: 13, color: "#dc2626" }}>{error}</p>
            ) : null}

            {isLoggedIn ? (
              <PrimaryCta type="button" onClick={handleAccept} disabled={accepting}>
                {accepting ? (
                  <MorphLoader className="size-4" />
                ) : (
                  <>
                    <UserPlus className="size-4" /> Aceitar convite
                  </>
                )}
              </PrimaryCta>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <Link
                  href={`/login?redirect=/invite/${token}`}
                  style={{
                    height: 48,
                    background: INK,
                    color: "white",
                    borderRadius: 8,
                    fontSize: 14,
                    fontWeight: 600,
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    textDecoration: "none",
                  }}
                >
                  Fazer login
                </Link>
                <Link
                  href={`/register?redirect=/invite/${token}`}
                  style={{
                    height: 48,
                    background: "transparent",
                    border: `1px solid ${BORDER_PAPER}`,
                    color: INK,
                    borderRadius: 8,
                    fontSize: 14,
                    fontWeight: 500,
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    textDecoration: "none",
                  }}
                >
                  Criar conta
                </Link>
              </div>
            )}
          </div>
        ) : null}
      </PaperCard>
    </AuthShell>
  )
}

function Row({
  label,
  value,
  bold,
}: {
  label: string
  value: React.ReactNode
  bold?: boolean
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ fontSize: 12, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {label}
      </span>
      <span style={{ fontSize: 14, color: INK, fontWeight: bold ? 600 : 400 }}>{value}</span>
    </div>
  )
}

function RoleBadge({ role }: { role: string }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 8px",
        borderRadius: 999,
        background: "rgba(99,102,241,0.12)",
        color: ACCENT,
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: "0.04em",
        textTransform: "uppercase",
      }}
    >
      {role}
    </span>
  )
}
