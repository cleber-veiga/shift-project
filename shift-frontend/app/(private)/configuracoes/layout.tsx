"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  Activity,
  KeyRound,
  Palette,
  Settings as SettingsIcon,
  ShieldCheck,
  Users,
  type LucideIcon,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useDashboard } from "@/lib/context/dashboard-context"

type NavItem = { href: string; label: string; icon: LucideIcon }
type NavGroup = { title: string | null; items: NavItem[]; hint?: string | null }

export default function ConfiguracoesLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const { selectedProject } = useDashboard()

  const groups: NavGroup[] = [
    {
      title: null,
      items: [
        { href: "/configuracoes/aparencia", label: "Aparência", icon: Palette },
      ],
    },
    {
      title: "Espaço",
      items: [
        { href: "/configuracoes/espaco/membros", label: "Membros", icon: Users },
        { href: "/configuracoes/espaco/controle-acesso", label: "Controle de Acesso", icon: ShieldCheck },
        { href: "/configuracoes/espaco/chaves-api", label: "Chaves de API", icon: KeyRound },
      ],
    },
    {
      title: "Projeto",
      hint: selectedProject ? selectedProject.name : "Selecione um projeto para gerenciar",
      items: selectedProject
        ? [
            { href: "/configuracoes/projeto/membros", label: "Membros", icon: Users },
            { href: "/configuracoes/projeto/atividade-agente", label: "Atividade do Agente", icon: Activity },
            { href: "/configuracoes/projeto/chaves-api", label: "Chaves de API", icon: KeyRound },
          ]
        : [],
    },
  ]

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          <SettingsIcon className="size-3.5" />
          Configurações
        </div>
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Configurações</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Ajuste aparência, gerencie membros e emita chaves de API do espaço e do projeto ativo.
          </p>
        </div>
      </div>

      <div className="flex flex-col gap-6 lg:flex-row">
        <aside className="lg:w-64 lg:shrink-0">
          <nav className="flex flex-col gap-5">
            {groups.map((group, groupIdx) => (
              <div key={group.title ?? `group-${groupIdx}`} className="flex flex-col gap-1">
                {group.title ? (
                  <div className="px-3 pb-1">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                      {group.title}
                    </p>
                    {group.hint ? (
                      <p className="mt-0.5 truncate text-[11px] text-muted-foreground/80">{group.hint}</p>
                    ) : null}
                  </div>
                ) : null}

                {group.items.length === 0 ? (
                  <p className="rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
                    Nenhum projeto selecionado.
                  </p>
                ) : (
                  group.items.map((item) => {
                    const Icon = item.icon
                    const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`)
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        className={cn(
                          "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                          isActive
                            ? "bg-accent text-foreground"
                            : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
                        )}
                      >
                        <Icon className="size-4 shrink-0" />
                        <span>{item.label}</span>
                      </Link>
                    )
                  })
                )}
              </div>
            ))}
          </nav>
        </aside>

        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </div>
  )
}
