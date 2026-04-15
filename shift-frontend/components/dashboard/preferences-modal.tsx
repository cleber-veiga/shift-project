"use client"

import { useEffect, useMemo } from "react"
import { useTheme } from "next-themes"
import { Check, Moon, Sun, X } from "lucide-react"
import { cn } from "@/lib/utils"

interface PreferencesModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

type Option<T extends string> = {
  value: T
  label: string
  description: string
}

const themeOptions: Option<"light" | "dark">[] = [
  { value: "light", label: "Light", description: "Interface clara." },
  { value: "dark", label: "Dark", description: "Interface escura." },
]

export function PreferencesModal({ open, onOpenChange }: PreferencesModalProps) {
  const { theme, setTheme, resolvedTheme } = useTheme()

  useEffect(() => {
    if (!open) return

    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onOpenChange(false)
      }
    }

    document.addEventListener("keydown", onEscape)
    return () => document.removeEventListener("keydown", onEscape)
  }, [onOpenChange, open])

  const selectedTheme = useMemo(() => {
    if (theme === "light" || theme === "dark") return theme
    return resolvedTheme === "dark" ? "dark" : "light"
  }, [resolvedTheme, theme])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-[2px]"
      role="presentation"
      onClick={() => onOpenChange(false)}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Preferencias"
        className="flex w-[min(720px,96vw)] flex-col rounded-2xl border border-border bg-card shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <p className="text-base font-semibold text-foreground">Preferencias</p>
            <p className="text-xs text-muted-foreground">Personalize a experiencia visual do sistema.</p>
          </div>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label="Fechar preferencias"
          >
            <X className="size-4" />
          </button>
        </div>

        <section className="p-5">
          <div>
            <h3 className="text-sm font-semibold text-foreground">Tema</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Escolha entre tema claro e escuro.
            </p>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
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
                        : "border-border hover:border-foreground/20 hover:bg-accent/40"
                    )}
                  >
                    <div className="space-y-1">
                      <p className="text-sm font-medium text-foreground">{option.label}</p>
                      <p className="text-xs text-muted-foreground">{option.description}</p>
                    </div>
                    <div className="ml-3 mt-0.5 flex items-center gap-1.5 text-muted-foreground">
                      {option.value === "light" ? (
                        <Sun className="size-4" />
                      ) : (
                        <Moon className="size-4" />
                      )}
                      {isSelected ? <Check className="size-4 text-primary" /> : null}
                    </div>
                  </button>
                )
              })}
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
