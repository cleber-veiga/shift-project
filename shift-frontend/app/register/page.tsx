"use client"

import { Suspense, useEffect, useState } from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { Eye, EyeOff } from "lucide-react"
import { getValidSession, register } from "@/lib/auth"
import { MorphLoader } from "@/components/ui/morph-loader"
import {
  ArrowRight,
  AUTH_TOKENS,
  AuthShell,
  PaperCard,
  PaperDivider,
  PaperField,
  PrimaryCta,
  Requirements,
  SsoButtons,
} from "@/components/auth/auth-shell"

const { ACCENT, BORDER_PAPER, INK } = AUTH_TOKENS

const requirementChecks = [
  { label: "Pelo menos 8 caracteres", test: (v: string) => v.length >= 8 },
  { label: "Uma letra maiúscula", test: (v: string) => /[A-Z]/.test(v) },
  { label: "Um número", test: (v: string) => /\d/.test(v) },
  { label: "Um caractere especial", test: (v: string) => /[^A-Za-z0-9]/.test(v) },
]

export default function RegisterPage() {
  return (
    <Suspense fallback={null}>
      <RegisterPageInner />
    </Suspense>
  )
}

function RegisterPageInner() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const redirect = searchParams.get("redirect")
  const [showPassword, setShowPassword] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState("")
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [accepted, setAccepted] = useState(true)

  useEffect(() => {
    async function checkSession() {
      const session = await getValidSession()
      if (session) {
        router.replace("/dashboard")
      }
    }
    checkSession()
  }, [router])

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!accepted) {
      setError("É preciso aceitar os Termos e a Política para continuar.")
      return
    }
    setIsLoading(true)
    setError("")
    try {
      await register({
        email,
        password,
        full_name: name.trim() || undefined,
      })
      router.push(redirect || "/onboarding")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao criar conta.")
    } finally {
      setIsLoading(false)
    }
  }

  const requirementItems = requirementChecks.map((r) => ({
    label: r.label,
    ok: r.test(password),
  }))

  return (
    <AuthShell
      heroEyebrow="Cadastro"
      heroTitle={
        <>
          Junte-se
          <br />
          ao{" "}
          <em style={{ fontStyle: "italic", fontWeight: 500, color: ACCENT }}>Shift</em>.
        </>
      }
      heroBody="Crie sua conta e comece a desenhar workflows de ETL em minutos: conecte fontes, transforme dados e entregue em qualquer destino."
      heroSupport={
        password.length > 0 ? (
          <Requirements items={requirementItems} caption="Sua senha precisa ter" />
        ) : null
      }
    >
      <PaperCard eyebrow="Crie sua conta">
        <SsoButtons />
        <PaperDivider />

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <PaperField
            label="Nome completo"
            placeholder="Seu nome"
            value={name}
            onChange={setName}
            required
            autoComplete="name"
          />
          <PaperField
            label="E-mail corporativo"
            placeholder="voce@empresa.com"
            type="email"
            value={email}
            onChange={setEmail}
            required
            autoComplete="email"
          />
          <PaperField
            label="Senha"
            placeholder="Mínimo 8 caracteres"
            type={showPassword ? "text" : "password"}
            value={password}
            onChange={setPassword}
            required
            minLength={8}
            autoComplete="new-password"
            trailing={
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? "Esconder senha" : "Mostrar senha"}
                style={{
                  background: "none",
                  border: "none",
                  color: "#9ca3af",
                  cursor: "pointer",
                  padding: 6,
                  display: "inline-flex",
                  alignItems: "center",
                }}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            }
          />

          <label
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 8,
              fontSize: 13,
              color: "#4b5563",
              cursor: "pointer",
              marginTop: 4,
              lineHeight: 1.5,
            }}
          >
            <input
              type="checkbox"
              checked={accepted}
              onChange={(e) => setAccepted(e.target.checked)}
              style={{ accentColor: ACCENT, marginTop: 3 }}
            />
            <span>
              Concordo com os{" "}
              <Link
                href="#"
                style={{
                  color: INK,
                  fontWeight: 600,
                  textDecoration: "underline",
                  textDecorationColor: BORDER_PAPER,
                }}
              >
                Termos
              </Link>{" "}
              e a{" "}
              <Link
                href="#"
                style={{
                  color: INK,
                  fontWeight: 600,
                  textDecoration: "underline",
                  textDecorationColor: BORDER_PAPER,
                }}
              >
                Política de Privacidade
              </Link>
              .
            </span>
          </label>

          {error ? (
            <p style={{ margin: 0, fontSize: 13, color: "#dc2626" }}>{error}</p>
          ) : null}

          <PrimaryCta type="submit" disabled={isLoading}>
            {isLoading ? <MorphLoader className="size-4" /> : <>Criar conta <ArrowRight /></>}
          </PrimaryCta>
        </form>

        <p style={{ margin: "24px 0 0", fontSize: 13, color: "#6b7280", textAlign: "center" }}>
          Já tem conta?{" "}
          <Link
            href="/login"
            style={{
              color: INK,
              fontWeight: 600,
              textDecoration: "none",
              borderBottom: `1px solid ${ACCENT}`,
              paddingBottom: 1,
            }}
          >
            Entre
          </Link>
        </p>
      </PaperCard>
    </AuthShell>
  )
}
