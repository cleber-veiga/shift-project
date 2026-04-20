"use client"

import { useMemo } from "react"
import { useTheme } from "next-themes"
import { Check, Moon, Sun } from "lucide-react"
import { cn } from "@/lib/utils"

const themeOptions = [
  { value: "light" as const, label: "Light", description: "Interface clara." },
  { value: "dark" as const, label: "Dark", description: "Interface escura." },
]

export default function AparenciaPage() {
  const { theme, setTheme, resolvedTheme } = useTheme()

  const selectedTheme = useMemo(() => {
    if (theme === "light" || theme === "dark") return theme
    return resolvedTheme === "dark" ? "dark" : "light"
  }, [resolvedTheme, theme])

  return (
    <section className="rounded-2xl border border-border bg-card p-6">
      <div>
        <h2 className="text-base font-semibold text-foreground">Tema</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Escolha entre tema claro e escuro.
        </p>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        {themeOptions.map((option) => {
          const isSelected = selectedTheme === option.value
          return (
            <button
              key={option.value}
              type="button"
              onClick={() => setTheme(option.value)}
              className={cn(
                "flex items-start justify-between rounded-lg border p-3 text-left transition-colors",
                isSelected
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-foreground/20 hover:bg-accent/40",
              )}
            >
              <div className="space-y-1">
                <p className="text-sm font-medium text-foreground">{option.label}</p>
                <p className="text-xs text-muted-foreground">{option.description}</p>
              </div>
              <div className="ml-3 mt-0.5 flex items-center gap-1.5 text-muted-foreground">
                {option.value === "light" ? <Sun className="size-4" /> : <Moon className="size-4" />}
                {isSelected ? <Check className="size-4 text-primary" /> : null}
              </div>
            </button>
          )
        })}
      </div>
    </section>
  )
}
