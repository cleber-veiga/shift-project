import type { ReactNode } from "react"

export function ForcedDarkLayout({ children }: { children: ReactNode }) {
  return (
    <div className="dark min-h-screen" style={{ colorScheme: "dark" }}>
      {children}
    </div>
  )
}
