"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { ArrowRight, Eye, EyeOff, Github } from "lucide-react"
import { getValidSession, listOrganizations, login } from "@/lib/auth"
import { cn } from "@/lib/utils"
import { MorphLoader } from "@/components/ui/morph-loader"

export default function LoginPage() {
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

      <div className="relative z-10 w-full max-w-sm px-4">
        <div className="mb-8 flex flex-col items-center gap-4">
          <div className="flex size-11 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-lg font-bold text-white shadow-lg">
            A
          </div>
          <div className="text-center">
            <h1 className="text-xl font-semibold text-white">Faça login no Shift</h1>
            <p className="mt-1 text-sm text-neutral-500">Entre com suas credenciais para continuar.</p>
          </div>
        </div>

        <div className="mb-6 grid grid-cols-2 gap-3">
          <button
            type="button"
            disabled
            title="Login com Google ainda não conectado no frontend"
            className="flex items-center justify-center gap-2 rounded-lg border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium text-neutral-300 opacity-50"
          >
            <svg className="size-4" viewBox="0 0 24 24" fill="currentColor">
              <path
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                fill="#4285F4"
              />
              <path
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                fill="#34A853"
              />
              <path
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                fill="#FBBC05"
              />
              <path
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                fill="#EA4335"
              />
            </svg>
            Google
          </button>
          <button
            type="button"
            disabled
            className="flex items-center justify-center gap-2 rounded-lg border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium text-neutral-300 opacity-50"
          >
            <Github className="size-4" />
            GitHub
          </button>
        </div>

        <div className="relative mb-6">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-white/10" />
          </div>
          <div className="relative flex justify-center">
            <span className="bg-[#0a0a0a] px-3 text-xs text-neutral-600">Ou continue com email</span>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-neutral-400">Email</label>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="email@example.com"
              className="w-full rounded-lg border border-white/10 bg-white/5 px-3.5 py-2.5 text-sm text-white placeholder-neutral-600 outline-none transition-all focus:border-white/30 focus:ring-2 focus:ring-white/10"
              required
            />
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <label className="text-xs font-medium text-neutral-400">Senha</label>
              <Link
                href="/reset-password"
                className="text-xs text-neutral-500 transition-colors hover:text-white"
              >
                Esqueceu a senha?
              </Link>
            </div>
            <div className="relative">
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="********"
                className="w-full rounded-lg border border-white/10 bg-white/5 px-3.5 py-2.5 pr-10 text-sm text-white placeholder-neutral-600 outline-none transition-all focus:border-white/30 focus:ring-2 focus:ring-white/10"
                required
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-neutral-600 transition-colors hover:text-neutral-400"
              >
                {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
          </div>

          {error ? <p className="text-sm text-red-400">{error}</p> : null}

          <button
            type="submit"
            disabled={isLoading}
            className={cn(
              "flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-all",
              "bg-white text-neutral-900 shadow-[0_1px_0_0_rgba(255,255,255,0.1)_inset]",
              "hover:bg-neutral-100 active:bg-neutral-200",
              "disabled:cursor-not-allowed disabled:opacity-60"
            )}
          >
            {isLoading ? (
              <MorphLoader className="size-4" />
            ) : (
              <>
                Entrar
                <ArrowRight className="size-4" />
              </>
            )}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-neutral-600">
          Não tem uma conta?{" "}
          <Link
            href="/register"
            className="text-neutral-400 underline-offset-4 transition-colors hover:text-white hover:underline"
          >
            Cadastre-se
          </Link>
        </p>
        <p className="mt-4 text-center text-xs text-neutral-700">
          Ao fazer login, você concorda com nossos <Link href="#" className="underline-offset-4 hover:underline">Termos</Link> e{" "}
          <Link href="#" className="underline-offset-4 hover:underline">Política de Privacidade</Link>.
        </p>
      </div>
    </div>
  )
}

