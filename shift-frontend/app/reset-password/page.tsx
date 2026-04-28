"use client"

import { useRef, useState } from "react"
import Link from "next/link"
import { ArrowLeft } from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import { forgotPassword, resetPassword, verifyResetCode } from "@/lib/auth"
import {
  ArrowRight,
  AUTH_TOKENS,
  AuthShell,
  CheckIcon,
  NoteBlock,
  PaperCard,
  PaperField,
  PrimaryCta,
  Requirements,
} from "@/components/auth/auth-shell"

const { ACCENT, BORDER_PAPER, INK, PAPER_INSET } = AUTH_TOKENS

type Step = "email" | "sent" | "reset" | "done"

const passwordRules = [
  { label: "Pelo menos 8 caracteres", test: (v: string) => v.length >= 8 },
  { label: "Uma letra maiúscula", test: (v: string) => /[A-Z]/.test(v) },
  { label: "Um número ou símbolo", test: (v: string) => /[\d^A-Za-z0-9]/.test(v) || /[^A-Za-z0-9]/.test(v) },
]

export default function ResetPasswordPage() {
  const [step, setStep] = useState<Step>("email")
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState("")
  const [email, setEmail] = useState("")
  const [code, setCode] = useState(["", "", "", "", "", ""])
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const codeRefs = useRef<Array<HTMLInputElement | null>>([])

  const codeString = code.join("")

  const handleEmail = async (event: React.FormEvent) => {
    event.preventDefault()
    setIsLoading(true)
    setError("")
    try {
      await forgotPassword(email)
      setStep("sent")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao enviar email de recuperação.")
    } finally {
      setIsLoading(false)
    }
  }

  const handleCodeInput = (index: number, value: string) => {
    const digit = value.replace(/\D/g, "").slice(-1)
    const next = [...code]
    next[index] = digit
    setCode(next)
    if (digit && index < 5) codeRefs.current[index + 1]?.focus()
  }

  const handleCodeKeyDown = (index: number, event: React.KeyboardEvent) => {
    if (event.key === "Backspace" && !code[index] && index > 0) {
      codeRefs.current[index - 1]?.focus()
    }
  }

  const handleCodePaste = (event: React.ClipboardEvent) => {
    const pasted = event.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6)
    if (pasted.length === 6) {
      setCode(pasted.split(""))
      codeRefs.current[5]?.focus()
    }
  }

  const handleVerifyCode = async (event: React.FormEvent) => {
    event.preventDefault()
    if (codeString.length < 6) return
    setIsLoading(true)
    setError("")
    try {
      const result = await verifyResetCode(email, codeString)
      if (!result.valid) {
        setError("Código inválido ou expirado.")
        return
      }
      setStep("reset")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao verificar código.")
    } finally {
      setIsLoading(false)
    }
  }

  const handleReset = async (event: React.FormEvent) => {
    event.preventDefault()
    if (password !== confirm) return
    setIsLoading(true)
    setError("")
    try {
      await resetPassword(email, codeString, password)
      setStep("done")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao redefinir senha.")
    } finally {
      setIsLoading(false)
    }
  }

  const heroByStep = (() => {
    switch (step) {
      case "email":
        return {
          eyebrow: "Recuperação",
          title: (
            <>
              Esqueceu
              <br />
              sua{" "}
              <em style={{ fontStyle: "italic", fontWeight: 500, color: ACCENT }}>senha</em>?
            </>
          ),
          body: "Sem problema. Informe o e-mail associado à sua conta e enviaremos um código de verificação.",
          support: (
            <NoteBlock>
              Por segurança, o código expira em <strong style={{ color: INK }}>30 minutos</strong>. Se não chegar, verifique a pasta de spam.
            </NoteBlock>
          ),
        }
      case "sent":
        return {
          eyebrow: "Verificação",
          title: (
            <>
              Confirme o
              <br />
              <em style={{ fontStyle: "italic", fontWeight: 500, color: ACCENT }}>código</em> de 6 dígitos.
            </>
          ),
          body: (
            <>
              Enviamos um código para <strong style={{ color: INK }}>{email}</strong>. Cole ou digite os 6 dígitos para continuar.
            </>
          ),
          support: (
            <NoteBlock>
              O código expira em 30 minutos. Não recebeu?{" "}
              <button
                type="button"
                onClick={() => {
                  setCode(["", "", "", "", "", ""])
                  setStep("email")
                }}
                style={{
                  background: "none",
                  border: "none",
                  color: ACCENT,
                  fontWeight: 600,
                  cursor: "pointer",
                  padding: 0,
                  fontFamily: "inherit",
                  fontSize: "inherit",
                }}
              >
                Reenviar
              </button>
              .
            </NoteBlock>
          ),
        }
      case "reset":
        return {
          eyebrow: "Nova senha",
          title: (
            <>
              Defina sua
              <br />
              <em style={{ fontStyle: "italic", fontWeight: 500, color: ACCENT }}>nova</em> senha.
            </>
          ),
          body: "Escolha uma senha forte. Você poderá entrar imediatamente após confirmar.",
          support: (
            <Requirements
              items={passwordRules.map((r) => ({ label: r.label, ok: r.test(password) }))}
            />
          ),
        }
      case "done":
        return {
          eyebrow: "Concluído",
          title: (
            <>
              Tudo certo. Sua{" "}
              <em style={{ fontStyle: "italic", fontWeight: 500, color: ACCENT }}>senha</em> foi atualizada.
            </>
          ),
          body: "Você já pode entrar com a nova senha. Te direcionamos abaixo.",
        }
    }
  })()

  return (
    <AuthShell
      heroEyebrow={heroByStep.eyebrow}
      heroTitle={heroByStep.title}
      heroBody={heroByStep.body}
      heroSupport={heroByStep.support}
    >
      <PaperCard eyebrow={step === "done" ? "Senha redefinida" : "Recuperar acesso"}>
        {step === "email" ? (
          <form onSubmit={handleEmail} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <PaperField
              label="E-mail"
              placeholder="voce@empresa.com"
              type="email"
              value={email}
              onChange={setEmail}
              required
              autoComplete="email"
            />
            {error ? (
              <p style={{ margin: 0, fontSize: 13, color: "#dc2626" }}>{error}</p>
            ) : null}
            <PrimaryCta type="submit" disabled={isLoading}>
              {isLoading ? <MorphLoader className="size-4" /> : <>Enviar código <ArrowRight /></>}
            </PrimaryCta>
          </form>
        ) : null}

        {step === "sent" ? (
          <form
            onSubmit={handleVerifyCode}
            style={{ display: "flex", flexDirection: "column", gap: 16 }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 8,
              }}
              onPaste={handleCodePaste}
            >
              {code.map((digit, index) => (
                <input
                  key={index}
                  ref={(el) => {
                    codeRefs.current[index] = el
                  }}
                  type="text"
                  inputMode="numeric"
                  maxLength={1}
                  value={digit}
                  onChange={(event) => handleCodeInput(index, event.target.value)}
                  onKeyDown={(event) => handleCodeKeyDown(index, event)}
                  style={{
                    width: 52,
                    height: 56,
                    background: PAPER_INSET,
                    border: "1px solid transparent",
                    borderRadius: 8,
                    textAlign: "center",
                    fontSize: 22,
                    fontWeight: 600,
                    color: INK,
                    outline: "none",
                    fontFamily: "inherit",
                  }}
                />
              ))}
            </div>
            {error ? (
              <p style={{ margin: 0, fontSize: 13, color: "#dc2626" }}>{error}</p>
            ) : null}
            <PrimaryCta type="submit" disabled={isLoading || codeString.length < 6}>
              {isLoading ? <MorphLoader className="size-4" /> : <>Verificar código <ArrowRight /></>}
            </PrimaryCta>
          </form>
        ) : null}

        {step === "reset" ? (
          <form onSubmit={handleReset} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <PaperField
              label="Nova senha"
              placeholder="Mínimo 8 caracteres"
              type="password"
              value={password}
              onChange={setPassword}
              required
              minLength={8}
              autoComplete="new-password"
            />
            <PaperField
              label="Confirmar senha"
              placeholder="Repita a nova senha"
              type="password"
              value={confirm}
              onChange={setConfirm}
              required
              autoComplete="new-password"
              invalid={confirm.length > 0 && confirm !== password}
            />
            {confirm.length > 0 && confirm !== password ? (
              <p style={{ margin: 0, fontSize: 13, color: "#dc2626" }}>Senhas não coincidem.</p>
            ) : null}
            {error ? (
              <p style={{ margin: 0, fontSize: 13, color: "#dc2626" }}>{error}</p>
            ) : null}
            <PrimaryCta
              type="submit"
              disabled={isLoading || password !== confirm || password.length < 8}
            >
              {isLoading ? <MorphLoader className="size-4" /> : <>Atualizar senha <ArrowRight /></>}
            </PrimaryCta>
          </form>
        ) : null}

        {step === "done" ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 16, alignItems: "stretch" }}>
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
              Senha atualizada com sucesso.
            </div>
            <Link
              href="/login"
              style={{
                marginTop: 8,
                height: 48,
                background: INK,
                color: "white",
                borderRadius: 8,
                fontSize: 14,
                fontWeight: 600,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 8,
                textDecoration: "none",
              }}
            >
              Ir para login <ArrowRight />
            </Link>
          </div>
        ) : null}

        <div
          style={{
            marginTop: 28,
            paddingTop: 20,
            borderTop: `1px solid ${BORDER_PAPER}`,
            fontSize: 13,
            color: "#6b7280",
            textAlign: "center",
          }}
        >
          {step === "done" ? null : (
            <Link
              href="/login"
              style={{
                color: INK,
                fontWeight: 600,
                textDecoration: "none",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <ArrowLeft size={14} /> Voltar ao login
            </Link>
          )}
        </div>
      </PaperCard>
    </AuthShell>
  )
}
