import { cn } from "@/lib/utils"

// ─── Config central de roles ──────────────────────────────────────────────────

const ROLE_CONFIG: Record<string, { label: string; badge: string; text: string }> = {
  // Org
  OWNER:      { label: "Dono",          badge: "bg-amber-500/10 text-amber-700 ring-amber-500/18 dark:text-amber-300", text: "text-amber-700 dark:text-amber-300" },
  MANAGER:    { label: "Gerente",       badge: "bg-blue-500/10 text-blue-700 ring-blue-500/18 dark:text-blue-300", text: "text-blue-700 dark:text-blue-300" },
  MEMBER:     { label: "Membro",        badge: "bg-slate-500/10 text-slate-700 ring-slate-500/18 dark:text-slate-300", text: "text-slate-700 dark:text-slate-300" },
  GUEST:      { label: "Convidado",     badge: "bg-zinc-500/10 text-zinc-700 ring-zinc-500/18 dark:text-zinc-300", text: "text-zinc-700 dark:text-zinc-300" },
  // Workspace
  CONSULTANT: { label: "Consultor",     badge: "bg-violet-500/10 text-violet-700 ring-violet-500/18 dark:text-violet-300", text: "text-violet-700 dark:text-violet-300" },
  VIEWER:     { label: "Visualizador",  badge: "bg-cyan-500/10 text-cyan-700 ring-cyan-500/18 dark:text-cyan-300", text: "text-cyan-700 dark:text-cyan-300" },
  // Project
  EDITOR:     { label: "Editor",        badge: "bg-emerald-500/10 text-emerald-700 ring-emerald-500/18 dark:text-emerald-300", text: "text-emerald-700 dark:text-emerald-300" },
  CLIENT:     { label: "Cliente",       badge: "bg-orange-500/10 text-orange-700 ring-orange-500/18 dark:text-orange-300", text: "text-orange-700 dark:text-orange-300" },
}

const FALLBACK = { label: "", badge: "bg-muted text-muted-foreground ring-border", text: "text-muted-foreground" }

/** Retorna o rótulo traduzido de um role. */
export function roleLabel(role: string): string {
  return ROLE_CONFIG[role]?.label ?? role
}

/** Retorna a classe de cor de texto para um role (usado nos botões do header). */
export function roleTextClass(role: string): string {
  return ROLE_CONFIG[role]?.text ?? FALLBACK.text
}

/** Pill colorida para exibir em dropdowns. */
export function RoleBadge({ role }: { role: string }) {
  const cfg = ROLE_CONFIG[role] ?? { ...FALLBACK, label: role }
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold ring-1 ring-inset",
        cfg.badge
      )}
    >
      {cfg.label}
    </span>
  )
}
