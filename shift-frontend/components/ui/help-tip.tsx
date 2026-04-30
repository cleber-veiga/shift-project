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
 * Renderizacao via React Portal + position: fixed: assim o popover escapa
 * de qualquer ``overflow: hidden`` em ancestrais (modais, painéis com
 * scroll, etc.) e a heranca de text-transform/tracking da <label> pai
 * tambem fica isolada.
 */

import { useState, useRef, useEffect } from "react"
import { createPortal } from "react-dom"
import Link from "next/link"
import { HelpCircle } from "lucide-react"

export type HelpTipProps = {
  children: React.ReactNode
  /** Slug do artigo em /ajuda. Se passado, mostra link "Saiba mais". */
  article?: string
  className?: string
}

const POPOVER_W = 256 // w-64

export function HelpTip({ children, article, className }: HelpTipProps) {
  const [open, setOpen] = useState(false)
  const btnRef = useRef<HTMLButtonElement | null>(null)
  const popoverRef = useRef<HTMLDivElement | null>(null)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)

  // Calcula a posicao do popover em coordenadas de viewport sempre que abre.
  // Reposiciona em scroll/resize pra acompanhar o botao mesmo quando a
  // pagina rola.
  useEffect(() => {
    if (!open) {
      setPos(null)
      return
    }
    const update = () => {
      const btn = btnRef.current
      if (!btn) return
      const r = btn.getBoundingClientRect()
      // Centraliza horizontalmente sobre o botao, mas clampa nas bordas
      // da viewport com margem de 8px pra nao colar nas extremidades.
      const idealLeft = r.left + r.width / 2 - POPOVER_W / 2
      const minLeft = 8
      const maxLeft = window.innerWidth - POPOVER_W - 8
      const left = Math.max(minLeft, Math.min(idealLeft, maxLeft))
      // Por padrao abre abaixo do icone; se nao couber abaixo, abre acima.
      const popoverH = popoverRef.current?.offsetHeight ?? 0
      const spaceBelow = window.innerHeight - r.bottom
      const top =
        popoverH > 0 && spaceBelow < popoverH + 12 && r.top > popoverH + 12
          ? r.top - popoverH - 6
          : r.bottom + 6
      setPos({ top, left })
    }
    update()
    // Roda update de novo após o popover ter sido renderizado pra refinar
    // o ``top`` baseado na altura medida (a primeira passada nao tem ref).
    const raf = requestAnimationFrame(update)
    window.addEventListener("scroll", update, true)
    window.addEventListener("resize", update)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener("scroll", update, true)
      window.removeEventListener("resize", update)
    }
  }, [open])

  // Click fora fecha (considera o botao + o popover via portal)
  useEffect(() => {
    if (!open) return
    function onDocClick(e: MouseEvent) {
      const target = e.target as Node
      if (btnRef.current?.contains(target)) return
      if (popoverRef.current?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener("mousedown", onDocClick)
    return () => document.removeEventListener("mousedown", onDocClick)
  }, [open])

  // Esc fecha
  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open])

  const popover =
    open && typeof document !== "undefined"
      ? createPortal(
          <div
            ref={popoverRef}
            role="tooltip"
            // ``normal-case tracking-normal`` reseta o text-transform e o
            // letter-spacing herdados de labels com ``uppercase``. Sem isso,
            // o conteudo do tooltip vira ALL CAPS quando o componente esta
            // dentro de um <label> de cabeçalho (padrao da plataforma).
            className="fixed z-[1000] w-64 rounded-md border border-border bg-popover p-3 text-xs normal-case leading-relaxed tracking-normal text-popover-foreground shadow-lg"
            style={{
              top: pos?.top ?? -9999,
              left: pos?.left ?? -9999,
              visibility: pos ? "visible" : "hidden",
            }}
          >
            <span className="block font-normal text-muted-foreground">
              {children}
            </span>
            {article && (
              <Link
                href={`/ajuda/${article}`}
                className="mt-2 inline-block font-medium text-primary hover:underline"
                onClick={() => setOpen(false)}
              >
                Saiba mais →
              </Link>
            )}
          </div>,
          document.body,
        )
      : null

  return (
    <span className={`relative inline-flex ${className ?? ""}`}>
      <button
        ref={btnRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label="Ajuda"
        className="inline-flex size-3.5 items-center justify-center rounded-full text-muted-foreground/60 transition-colors hover:text-foreground"
      >
        <HelpCircle className="size-3.5" />
      </button>
      {popover}
    </span>
  )
}
