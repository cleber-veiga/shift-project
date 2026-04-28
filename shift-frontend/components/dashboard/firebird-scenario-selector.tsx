"use client"

import { Container, MonitorCog, Network } from "lucide-react"
import type { ComponentType, SVGProps } from "react"

export type FirebirdScenario = "bundled" | "windows-host" | "remote-server"

interface ScenarioOption {
  value: FirebirdScenario
  label: string
  description: string
  Icon: ComponentType<SVGProps<SVGSVGElement>>
}

const SCENARIOS: ScenarioOption[] = [
  {
    value: "bundled",
    label: "Tenho apenas o arquivo .fdb",
    description:
      "A Shift sobe um servidor Firebird embutido em container e usa seu arquivo via mount. Ideal quando o cliente não tem Firebird instalado.",
    Icon: Container,
  },
  {
    value: "windows-host",
    label: "O servidor Firebird roda na máquina Windows",
    description:
      "A Shift conecta no Firebird que já está rodando no host Windows via host.docker.internal. Requer porta 3050 liberada no firewall.",
    Icon: MonitorCog,
  },
  {
    value: "remote-server",
    label: "Servidor Firebird remoto na rede",
    description:
      "Conexão TCP direta para um servidor Firebird em outra máquina (IP ou hostname).",
    Icon: Network,
  },
]

export interface FirebirdScenarioSelectorProps {
  value: FirebirdScenario
  onChange: (value: FirebirdScenario) => void
  disabled?: boolean
}

export function FirebirdScenarioSelector({
  value,
  onChange,
  disabled = false,
}: FirebirdScenarioSelectorProps) {
  return (
    <div
      role="radiogroup"
      aria-label="Cenário de deploy do Firebird"
      className="grid gap-2"
    >
      {SCENARIOS.map((opt) => {
        const selected = value === opt.value
        const { Icon } = opt
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => !disabled && onChange(opt.value)}
            disabled={disabled}
            className={`flex items-start gap-3 rounded-md border px-3 py-2.5 text-left transition-colors disabled:opacity-60 ${
              selected
                ? "border-emerald-500/40 bg-emerald-500/5"
                : "border-border bg-background hover:border-muted-foreground/40 hover:bg-muted/50"
            }`}
          >
            <span
              className={`mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md ${
                selected
                  ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              <Icon className="size-4" aria-hidden />
            </span>
            <span className="flex flex-col gap-0.5">
              <span
                className={`text-[13px] font-medium ${
                  selected ? "text-foreground" : "text-foreground/90"
                }`}
              >
                {opt.label}
              </span>
              <span className="text-[11px] leading-relaxed text-muted-foreground">
                {opt.description}
              </span>
            </span>
          </button>
        )
      })}
    </div>
  )
}

/** Infere o cenario a partir do host de uma conexao existente. */
export function inferScenarioFromHost(host: string | null | undefined): FirebirdScenario {
  const h = (host ?? "").trim().toLowerCase()
  if (h === "firebird25" || h === "firebird30") return "bundled"
  if (h.startsWith("firebird25.") || h.startsWith("firebird30.")) return "bundled"
  if (h === "host.docker.internal") return "windows-host"
  return "remote-server"
}
