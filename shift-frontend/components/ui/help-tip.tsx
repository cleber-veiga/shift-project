"use client"

/**
 * HelpTip — pequeno icone de interrogacao com popover de ajuda.
 *
 * Uso:
 *   <Label>
 *     Modelo de entrada
 *     <HelpTip article="modelos-entrada">
 *       Define a estrutura esperada do arquivo. Vinculado, valida na execução.
 *     </HelpTip>
 *   </Label>
 *
 * O `article` opcional cria um link "Saiba mais" pra rota /ajuda/<slug>.
 * Sem ele, mostra so o texto curto. Bom pra docs progressivas: comeca
 * inline e aprofunda no artigo.
 *
 * Sem dependencia em Radix/shadcn Popover — implementacao minima com
 * useState. A intencao e zero overhead pra explicacao de 1 frase.
 */

import { useState, useRef, useEffect } from "react"
import Link from "next/link"
import { HelpCircle } from "lucide-react"

export type HelpTipProps = {
  children: React.ReactNode
  /** Slug do artigo em /ajuda. Se passado, mostra link "Saiba mais". */
  article?: string
  className?: string
}

export function HelpTip({ children, article, className }: HelpTipProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement | null>(null)

  // Click fora fecha
  useEffect(() => {
    if (!open) return
    function onDocClick(e: MouseEvent) {
      if (!ref.current) return
      if (!ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDocClick)
    return () => document.removeEventListener("mousedown", onDocClick)
  }, [open])

  return (
    <span ref={ref} className={`relative inline-flex ${className ?? ""}`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label="Ajuda"
        className="inline-flex size-3.5 items-center justify-center rounded-full text-muted-foreground/60 transition-colors hover:text-foreground"
      >
        <HelpCircle className="size-3.5" />
      </button>

      {open && (
        <span
          role="tooltip"
          className="absolute left-1/2 top-5 z-50 w-64 -translate-x-1/2 rounded-md border border-border bg-popover p-3 text-xs leading-relaxed text-popover-foreground shadow-md"
        >
          <span className="block text-muted-foreground">{children}</span>
          {article && (
            <Link
              href={`/ajuda/${article}`}
              className="mt-2 inline-block text-primary hover:underline"
              onClick={() => setOpen(false)}
            >
              Saiba mais →
            </Link>
          )}
        </span>
      )}
    </span>
  )
}
