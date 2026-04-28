"use client"

import { Suspense, useEffect, useState } from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { Eye, EyeOff } from "lucide-react"
import { getValidSession, listOrganizations, login } from "@/lib/auth"
import { MorphLoader } from "@/components/ui/morph-loader"
import {
  ArrowRight,
  AUTH_TOKENS,
  AuthShell,
  PaperCard,
  PaperDivider,
  PaperField,
  PrimaryCta,
  SsoButtons,
} from "@/components/auth/auth-shell"

const { ACCENT, BORDER_PAPER, INK } = AUTH_TOKENS

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginPageInner />
    </Suspense>
  )
}

function LoginPageInner() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const redirect = searchParams.get("redirect")
  const [showPassword, setShowPassword] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")

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
    setIsLoading(true)
    setError("")
    try {
      await login({ email, password })
      if (redirect) {
        router.push(redirect)
      } else {
        const orgs = await listOrganizations()
        router.push(orgs.length === 0 ? "/onboarding" : "/dashboard")
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao autenticar.")
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <AuthShell
      heroEyebrow="Login"
      heroTitle={
        <>
          Faça{" "}
          <em style={{ fontStyle: "italic", fontWeight: 500, color: ACCENT }}>login</em>
          <br />
          no Shift.
        </>
      }
      heroBody="Plataforma de workflows de ETL: orquestre extração, transformação e carga de dados entre sistemas — sem código intermediário."
    >
      <PaperCard eyebrow="Acesso à conta">
        <SsoButtons />
        <PaperDivider />

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <PaperField
            label="E-mail"
            placeholder="voce@empresa.com"
            type="email"
            value={email}
            onChange={setEmail}
            required
            autoComplete="email"
          />
          <PaperField
            label="Senha"
            placeholder="••••••••"
            type={showPassword ? "text" : "password"}
            value={password}
            onChange={setPassword}
            required
            autoComplete="current-password"
            action={
              <Link
                href="/reset-password"
                style={{ color: ACCENT, textDecoration: "none", fontWeight: 500 }}
              >
                Esqueceu?
              </Link>
            }
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

          {error ? (
            <p style={{ margin: 0, fontSize: 13, color: "#dc2626" }}>{error}</p>
          ) : null}

          <PrimaryCta type="submit" disabled={isLoading}>
            {isLoading ? <MorphLoader className="size-4" /> : <>Entrar <ArrowRight /></>}
          </PrimaryCta>
        </form>

        <p
          style={{
            margin: "24px 0 0",
            fontSize: 13,
            color: "#6b7280",
            textAlign: "center",
          }}
        >
          Sem conta?{" "}
          <Link
            href="/register"
            style={{
              color: INK,
              fontWeight: 600,
              textDecoration: "none",
              borderBottom: `1px solid ${ACCENT}`,
              paddingBottom: 1,
            }}
          >
            Crie agora
          </Link>
        </p>
        <p
          style={{
            marginTop: 16,
            fontSize: 11,
            color: "#9ca3af",
            textAlign: "center",
          }}
        >
          Ao fazer login, você concorda com nossos{" "}
          <Link href="#" style={{ color: "#6b7280", textDecoration: "underline", textDecorationColor: BORDER_PAPER }}>
            Termos
          </Link>{" "}
          e{" "}
          <Link href="#" style={{ color: "#6b7280", textDecoration: "underline", textDecorationColor: BORDER_PAPER }}>
            Política de Privacidade
          </Link>
          .
        </p>
      </PaperCard>
    </AuthShell>
  )
}
