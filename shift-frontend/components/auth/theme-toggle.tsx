'use client'

import { useSyncExternalStore } from "react"
import { MoonStar, SunMedium } from "lucide-react"
import { useTheme } from "next-themes"
import { cn } from "@/lib/utils"

export function ThemeToggle({ className }: { className?: string }) {
  const { resolvedTheme, setTheme } = useTheme()
  const mounted = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false
  )

  const isDark = mounted ? resolvedTheme === "dark" : false

  return (
    <button
      type="button"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className={cn(
        "inline-flex h-10 items-center gap-2 rounded-full border border-border/70 bg-card/80 px-3 text-sm font-medium text-muted-foreground backdrop-blur hover:text-foreground",
        className
      )}
      aria-label={isDark ? "Ativar tema claro" : "Ativar tema escuro"}
    >
      {isDark ? <SunMedium className="size-4" /> : <MoonStar className="size-4" />}
      <span>{isDark ? "Light" : "Dark"}</span>
    </button>
  )
}
