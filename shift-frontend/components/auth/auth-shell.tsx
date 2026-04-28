import type { ReactNode } from "react"
import Link from "next/link"
import { ArrowUpRight, Database, Sparkles, Workflow } from "lucide-react"
import { ThemeToggle } from "@/components/auth/theme-toggle"
import { ShiftMarkAdaptive } from "@/components/ui/shift-mark"

type AuthShellProps = {
  eyebrow: string
  title: string
  description: string
  children: ReactNode
  footer?: ReactNode
}

const highlights = [
  {
    icon: Workflow,
    title: "Mapeamento reaproveitavel",
    description: "Transforme conhecimento operacional em fluxos de migracao reutilizaveis.",
  },
  {
    icon: Database,
    title: "Menos retrabalho",
    description: "Centralize regras, validacoes e estruturas sem depender de processos manuais.",
  },
  {
    icon: Sparkles,
    title: "Base pronta para crescer",
    description: "Comece pelo onboarding e evolua o produto sem carregar a vitrine inteira do design system.",
  },
]

export function AuthShell({
  eyebrow,
  title,
  description,
  children,
  footer,
}: AuthShellProps) {
  return (
    <main className="auth-shell relative min-h-screen overflow-hidden">
      <div className="auth-grid pointer-events-none absolute inset-0 opacity-70" />

      <div className="relative mx-auto flex min-h-screen max-w-7xl flex-col px-4 py-6 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between">
          <Link
            href="/login"
            className="inline-flex items-center gap-3 rounded-full border border-border/70 bg-card/80 px-3 py-2 backdrop-blur"
          >
            <ShiftMarkAdaptive size={36} />
            <span className="text-sm font-semibold tracking-[0.24em] text-foreground">
              SHIFT
            </span>
          </Link>

          <ThemeToggle />
        </div>

        <div className="flex flex-1 items-center py-10 lg:py-14">
          <div className="grid w-full gap-8 lg:grid-cols-[1.1fr_0.9fr] lg:gap-12">
            <section className="auth-brand hidden rounded-[2rem] border border-border/60 p-8 lg:flex lg:flex-col lg:justify-between">
              <div className="max-w-xl">
                <p className="text-sm font-semibold uppercase tracking-[0.3em] text-muted-foreground">
                  Shift Platform
                </p>
                <h1 className="mt-6 max-w-lg text-4xl font-semibold tracking-tight text-balance text-foreground xl:text-5xl">
                  Mapeie dados uma vez. Reaproveite sempre.
                </h1>
                <p className="mt-6 max-w-xl text-base leading-7 text-muted-foreground">
                  Esta base inicial concentra apenas os fluxos essenciais de autenticacao,
                  mantendo a linguagem visual do design system sem carregar todas as secoes
                  demonstrativas.
                </p>
              </div>

              <div className="grid gap-4">
                {highlights.map((item) => {
                  const Icon = item.icon

                  return (
                    <div
                      key={item.title}
                      className="rounded-3xl border border-border/70 bg-card/70 p-5 backdrop-blur"
                    >
                      <div className="flex items-start gap-4">
                        <span className="mt-0.5 inline-flex size-10 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                          <Icon className="size-5" />
                        </span>
                        <div>
                          <h2 className="text-base font-semibold text-foreground">
                            {item.title}
                          </h2>
                          <p className="mt-1 text-sm leading-6 text-muted-foreground">
                            {item.description}
                          </p>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>

            <section className="flex items-center justify-center">
              <div className="auth-panel w-full max-w-xl rounded-[2rem] border border-border/70 bg-card/84 p-6 backdrop-blur-xl sm:p-8">
                <div className="mb-8 flex items-start justify-between gap-4">
                  <div>
                    <p className="text-sm font-semibold uppercase tracking-[0.28em] text-muted-foreground">
                      {eyebrow}
                    </p>
                    <h2 className="mt-4 text-3xl font-semibold tracking-tight text-foreground">
                      {title}
                    </h2>
                    <p className="mt-3 max-w-md text-sm leading-6 text-muted-foreground">
                      {description}
                    </p>
                  </div>

                  <span className="hidden rounded-full border border-border/70 bg-background/70 p-2 text-muted-foreground sm:inline-flex">
                    <ArrowUpRight className="size-4" />
                  </span>
                </div>

                {children}

                {footer ? (
                  <div className="mt-8 border-t border-border/70 pt-6 text-sm text-muted-foreground">
                    {footer}
                  </div>
                ) : null}
              </div>
            </section>
          </div>
        </div>
      </div>
    </main>
  )
}
