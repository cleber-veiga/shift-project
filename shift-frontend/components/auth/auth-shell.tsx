"use client"

import type { CSSProperties, ReactNode } from "react"
import { Fragment, useEffect, useRef } from "react"
import Link from "next/link"
import { ShiftWordmark } from "@/components/ui/shift-mark"

const INK = "#0e1220"
const ACCENT = "#6366f1"
const CREAM = "#f5f4ee"
const PAPER = "#fdfcf7"
const PAPER_INSET = "#f5f4ee"
const BORDER_PAPER = "#ece9dd"

const monoFamily = 'var(--font-mono, "JetBrains Mono", ui-monospace, monospace)'
const sansFamily = 'var(--font-sans, "Inter Tight", system-ui, sans-serif)'

type AuthShellProps = {
  heroEyebrow: string
  heroTitle: ReactNode
  heroBody: ReactNode
  heroSupport?: ReactNode
  children: ReactNode
}

// ============================================================
// V2 COMET — RAF-driven, ref-based DOM updates
//
// Bypassa React state inteiramente para a animação. Uma única passagem
// de RAF atualiza inline-style direto no DOM via refs. Sem dependência
// de batching/scheduling do React, sem matchMedia que possa bloquear.
// ============================================================

const TOTAL_MS = 4400
const TRAIL_COUNT = 14
const round4 = (n: number) => Math.round(n * 10000) / 10000
const clamp01 = (v: number) => Math.max(0, Math.min(1, v))
const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3)
const easeInOutCubic = (t: number) =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2

type RevealOpts = { y?: number; x?: number; scale?: number }

function revealStyle(progress: number, start: number, end: number, opts: RevealOpts = {}) {
  const t = clamp01((progress - start) / (end - start))
  const eased = easeOutCubic(t)
  const yOff = opts.y == null ? 16 : opts.y
  const xOff = opts.x ?? 0
  const scale = opts.scale != null ? 1 - (1 - opts.scale) * (1 - eased) : 1
  return {
    opacity: round4(eased),
    transform: `translate(${round4(xOff * (1 - eased))}px, ${round4(yOff * (1 - eased))}px) scale(${round4(scale)})`,
  }
}

function cometAt(t: number) {
  const p0x = 245, p0y = 50
  const cp1x = 245, cp1y = 480
  const cp2x = 450, cp2y = 180
  const p3x = 970, p3y = 540
  const x =
    Math.pow(1 - t, 3) * p0x +
    3 * Math.pow(1 - t, 2) * t * cp1x +
    3 * (1 - t) * t * t * cp2x +
    t * t * t * p3x
  const y =
    Math.pow(1 - t, 3) * p0y +
    3 * Math.pow(1 - t, 2) * t * cp1y +
    3 * (1 - t) * t * t * cp2y +
    t * t * t * p3y
  return { x: round4(x), y: round4(y) }
}

function applyReveal(el: HTMLElement | null, s: { opacity: number; transform: string }) {
  if (!el) return
  el.style.opacity = String(s.opacity)
  el.style.transform = s.transform
}

export function AuthShell({
  heroEyebrow,
  heroTitle,
  heroBody,
  heroSupport,
  children,
}: AuthShellProps) {
  const headerRef = useRef<HTMLElement>(null)
  const eyebrowRef = useRef<HTMLDivElement>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const bodyRef = useRef<HTMLParagraphElement>(null)
  const statsRef = useRef<HTMLDivElement>(null)
  const cardRef = useRef<HTMLDivElement>(null)
  const footerRef = useRef<HTMLElement>(null)
  const cometRef = useRef<SVGSVGElement>(null)
  const trailRefs = useRef<Array<SVGCircleElement | null>>([])
  const headHaloRef = useRef<SVGCircleElement>(null)
  const headOuterRef = useRef<SVGCircleElement>(null)
  const headInnerRef = useRef<SVGCircleElement>(null)

  useEffect(() => {
    let startTs: number | null = null
    let rafId = 0

    const tick = (ts: number) => {
      if (startTs == null) startTs = ts
      const elapsed = ts - startTs
      const p = Math.min(1, elapsed / TOTAL_MS)

      // Cascata de reveals
      applyReveal(headerRef.current, revealStyle(p, 0.04, 0.16))
      applyReveal(footerRef.current, revealStyle(p, 0.04, 0.14))
      applyReveal(eyebrowRef.current, revealStyle(p, 0.22, 0.30))
      applyReveal(titleRef.current, revealStyle(p, 0.26, 0.40))
      applyReveal(bodyRef.current, revealStyle(p, 0.36, 0.48))
      applyReveal(statsRef.current, revealStyle(p, 0.44, 0.54))
      applyReveal(cardRef.current, revealStyle(p, 0.52, 0.66, { scale: 0.95 }))

      // Cometa: ativo entre 0.18 e 0.92
      const COMET_START = 0.18
      const COMET_END = 0.92
      const cometVisible = p > COMET_START && p < COMET_END
      if (cometRef.current) {
        cometRef.current.style.display = cometVisible ? "block" : "none"
      }
      if (cometVisible) {
        const tt = clamp01((p - COMET_START) / (COMET_END - COMET_START))
        const eased = easeInOutCubic(tt)
        const { x, y } = cometAt(eased)
        const fadeIn = Math.min(1, tt * 8)
        const fadeOut = tt > 0.9 ? Math.min(1, (1 - tt) * 10) : 1
        const op = round4(fadeIn * fadeOut)

        // Atualiza cabeças (halo + outer + inner)
        const headPos = String(x)
        const headPosY = String(y)
        if (headHaloRef.current) {
          headHaloRef.current.setAttribute("cx", headPos)
          headHaloRef.current.setAttribute("cy", headPosY)
          headHaloRef.current.setAttribute("opacity", String(op))
        }
        if (headOuterRef.current) {
          headOuterRef.current.setAttribute("cx", headPos)
          headOuterRef.current.setAttribute("cy", headPosY)
          headOuterRef.current.setAttribute("opacity", String(op))
        }
        if (headInnerRef.current) {
          headInnerRef.current.setAttribute("cx", headPos)
          headInnerRef.current.setAttribute("cy", headPosY)
          headInnerRef.current.setAttribute("opacity", String(op))
        }

        // Trail: cada círculo é uma posição defasada
        for (let i = 0; i < TRAIL_COUNT; i++) {
          const el = trailRefs.current[i]
          if (!el) continue
          const lag = (i + 1) * 0.025
          const ttt = Math.max(0, eased - lag)
          const pos = cometAt(ttt)
          const trailOp = round4(((1 - i / TRAIL_COUNT) * 0.6) * op)
          el.setAttribute("cx", String(pos.x))
          el.setAttribute("cy", String(pos.y))
          el.setAttribute("opacity", String(trailOp))
        }
      }

      if (p < 1) {
        rafId = requestAnimationFrame(tick)
      }
    }
    rafId = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafId)
  }, [])

  // Estilo inicial (antes do RAF rodar): tudo invisível com offset
  const initialHidden: CSSProperties = {
    opacity: 0,
    transform: "translate(0px, 16px) scale(1)",
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        background: CREAM,
        color: INK,
        fontFamily: sansFamily,
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div
        aria-hidden
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "radial-gradient(circle at 1px 1px, rgba(14,18,32,0.06) 1px, transparent 0)",
          backgroundSize: "20px 20px",
          opacity: 0.55,
          pointerEvents: "none",
        }}
      />

      <div
        aria-hidden
        style={{
          position: "absolute",
          top: -120,
          left: -160,
          opacity: 0.045,
          transform: "rotate(-8deg)",
          pointerEvents: "none",
        }}
      >
        <DecorativeMark size={760} />
      </div>

      <div
        style={{
          position: "relative",
          zIndex: 1,
          minHeight: "100vh",
          maxWidth: 1280,
          margin: "0 auto",
          padding: "28px 48px 84px",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <AuthCometSvg
          cometRef={cometRef}
          trailRefs={trailRefs}
          headHaloRef={headHaloRef}
          headOuterRef={headOuterRef}
          headInnerRef={headInnerRef}
        />

        <header
          ref={headerRef}
          style={{
            display: "flex",
            alignItems: "center",
            marginBottom: 24,
            ...initialHidden,
          }}
        >
          <Link href="/login" style={{ display: "inline-flex", textDecoration: "none" }}>
            <ShiftWordmark scale={0.5} variant="light" />
          </Link>
        </header>

        <div
          style={{
            flex: 1,
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) minmax(0, 480px)",
            gap: 64,
            alignItems: "center",
          }}
        >
          <section style={{ display: "flex", flexDirection: "column", justifyContent: "center" }}>
            <div
              ref={eyebrowRef}
              style={{
                fontFamily: monoFamily,
                fontSize: 11,
                color: "#6b7280",
                textTransform: "uppercase",
                letterSpacing: "0.15em",
                marginBottom: 24,
                display: "flex",
                alignItems: "center",
                gap: 8,
                ...initialHidden,
              }}
            >
              <span style={{ display: "inline-block", width: 24, height: 1, background: "#6b7280" }} />
              {heroEyebrow}
            </div>

            <h1
              ref={titleRef}
              style={{
                margin: 0,
                fontSize: "clamp(48px, 6vw, 80px)",
                fontWeight: 800,
                letterSpacing: "-0.04em",
                lineHeight: 0.95,
                maxWidth: 580,
                color: INK,
                ...initialHidden,
              }}
            >
              {heroTitle}
            </h1>

            <p
              ref={bodyRef}
              style={{
                margin: "32px 0 0",
                fontSize: 18,
                lineHeight: 1.5,
                color: "#4b5563",
                maxWidth: 460,
                ...initialHidden,
              }}
            >
              {heroBody}
            </p>

            {heroSupport ? (
              <div
                ref={statsRef}
                style={{
                  marginTop: 48,
                  ...initialHidden,
                }}
              >
                {heroSupport}
              </div>
            ) : null}
          </section>

          <div
            ref={cardRef}
            style={{
              display: "flex",
              justifyContent: "center",
              ...initialHidden,
            }}
          >
            {children}
          </div>
        </div>

        <footer
          ref={footerRef}
          style={{
            marginTop: 48,
            paddingTop: 16,
            borderTop: "1px solid #d1d5db",
            display: "flex",
            justifyContent: "space-between",
            fontSize: 12,
            color: "#6b7280",
            ...initialHidden,
          }}
        >
          <span>© {new Date().getFullYear()} Shift · Viasoft</span>
        </footer>
      </div>
    </main>
  )
}

type AuthCometSvgProps = {
  cometRef: React.RefObject<SVGSVGElement | null>
  trailRefs: React.RefObject<Array<SVGCircleElement | null>>
  headHaloRef: React.RefObject<SVGCircleElement | null>
  headOuterRef: React.RefObject<SVGCircleElement | null>
  headInnerRef: React.RefObject<SVGCircleElement | null>
}

function AuthCometSvg({
  cometRef,
  trailRefs,
  headHaloRef,
  headOuterRef,
  headInnerRef,
}: AuthCometSvgProps) {
  return (
    <svg
      ref={cometRef}
      aria-hidden
      width="100%"
      height="100%"
      viewBox="0 0 1280 800"
      preserveAspectRatio="xMidYMid meet"
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        zIndex: 2,
        display: "none",
      }}
    >
      <defs>
        <radialGradient id="auth-comet-glow">
          <stop offset="0%" stopColor="white" stopOpacity="1" />
          <stop offset="40%" stopColor={ACCENT} stopOpacity="0.9" />
          <stop offset="100%" stopColor={ACCENT} stopOpacity="0" />
        </radialGradient>
      </defs>

      {Array.from({ length: TRAIL_COUNT }).map((_, i) => {
        const r = round4(2 + (1 - i / TRAIL_COUNT) * 2.5)
        return (
          <circle
            key={i}
            ref={(el) => {
              trailRefs.current[i] = el
            }}
            cx="0"
            cy="0"
            r={r}
            fill={ACCENT}
            opacity="0"
          />
        )
      })}

      <circle ref={headHaloRef} cx="0" cy="0" r="22" fill="url(#auth-comet-glow)" opacity="0" />
      <circle ref={headOuterRef} cx="0" cy="0" r="5" fill="white" opacity="0" />
      <circle ref={headInnerRef} cx="0" cy="0" r="2.5" fill="white" opacity="0" />
    </svg>
  )
}

function DecorativeMark({ size = 720 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none">
      <rect x="2" y="2" width="60" height="60" rx={size * 0.22} fill={INK} />
      <text
        x="32"
        y="49.5"
        textAnchor="middle"
        fontFamily='"Viasoft Regular", "Inter Tight", system-ui, sans-serif'
        fontSize="32"
        fontWeight={400}
        fill={INK}
        letterSpacing="0"
      >
        S
      </text>
    </svg>
  )
}

// ============================================================
// PAPER CARD primitives
// ============================================================

type PaperCardProps = {
  eyebrow: string
  urlHint?: string
  width?: number
  children: ReactNode
}

export function PaperCard({ eyebrow, urlHint = "shift.app", width = 460, children }: PaperCardProps) {
  return (
    <div
      style={{
        width: "100%",
        maxWidth: width,
        background: PAPER,
        borderRadius: 4,
        padding: 40,
        boxShadow:
          "0 1px 0 rgba(14,18,32,0.04), 0 24px 48px -16px rgba(14,18,32,0.12), 0 2px 6px rgba(14,18,32,0.04)",
        color: INK,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          paddingBottom: 20,
          marginBottom: 24,
          borderBottom: `1px solid ${BORDER_PAPER}`,
        }}
      >
        <div
          style={{
            fontFamily: monoFamily,
            fontSize: 11,
            color: "#6b7280",
            textTransform: "uppercase",
            letterSpacing: "0.12em",
            fontWeight: 500,
          }}
        >
          {eyebrow}
        </div>
        <div style={{ fontFamily: monoFamily, fontSize: 11, color: "#9ca3af" }}>{urlHint}</div>
      </div>
      {children}
    </div>
  )
}

// ============================================================
// PAPER FIELD
// ============================================================

type PaperFieldProps = {
  label: string
  placeholder?: string
  type?: string
  value?: string
  defaultValue?: string
  onChange?: (value: string) => void
  trailing?: ReactNode
  action?: ReactNode
  required?: boolean
  minLength?: number
  autoComplete?: string
  inputMode?: "numeric" | "text" | "email"
  invalid?: boolean
}

export function PaperField({
  label,
  placeholder,
  type = "text",
  value,
  defaultValue,
  onChange,
  trailing,
  action,
  required,
  minLength,
  autoComplete,
  inputMode,
  invalid,
}: PaperFieldProps) {
  const inputStyle: CSSProperties = {
    width: "100%",
    height: 44,
    background: PAPER_INSET,
    border: `1px solid ${invalid ? "#ef4444" : "transparent"}`,
    borderRadius: 8,
    padding: "0 14px",
    color: INK,
    fontSize: 14,
    outline: "none",
    paddingRight: trailing ? 40 : 14,
    fontFamily: "inherit",
  }
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
        <label style={{ fontSize: 12, fontWeight: 500, color: "#4b5563" }}>{label}</label>
        {action ? (
          <span style={{ fontSize: 12, color: ACCENT, fontWeight: 500 }}>{action}</span>
        ) : null}
      </div>
      <div style={{ position: "relative" }}>
        <input
          type={type}
          value={value}
          defaultValue={defaultValue}
          onChange={onChange ? (e) => onChange(e.target.value) : undefined}
          placeholder={placeholder}
          required={required}
          minLength={minLength}
          autoComplete={autoComplete}
          inputMode={inputMode}
          style={inputStyle}
        />
        {trailing ? (
          <div
            style={{
              position: "absolute",
              right: 8,
              top: "50%",
              transform: "translateY(-50%)",
              display: "flex",
              alignItems: "center",
            }}
          >
            {trailing}
          </div>
        ) : null}
      </div>
    </div>
  )
}

// ============================================================
// PRIMARY CTA
// ============================================================

type PrimaryCtaProps = {
  children: ReactNode
  type?: "button" | "submit"
  disabled?: boolean
  onClick?: () => void
}

export function PrimaryCta({ children, type = "submit", disabled, onClick }: PrimaryCtaProps) {
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      style={{
        marginTop: 8,
        height: 48,
        width: "100%",
        background: INK,
        color: "white",
        border: "none",
        borderRadius: 8,
        fontSize: 14,
        fontWeight: 600,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.6 : 1,
        fontFamily: "inherit",
      }}
    >
      {children}
    </button>
  )
}

// ============================================================
// PAPER DIVIDER
// ============================================================

export function PaperDivider({ label = "ou com email" }: { label?: string }) {
  return (
    <div style={{ position: "relative", textAlign: "center", margin: "0 0 20px" }}>
      <div
        style={{
          position: "absolute",
          top: "50%",
          left: 0,
          right: 0,
          height: 1,
          background: BORDER_PAPER,
        }}
      />
      <span
        style={{
          position: "relative",
          background: PAPER,
          padding: "0 12px",
          fontSize: 11,
          color: "#9ca3af",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          fontWeight: 500,
          fontFamily: monoFamily,
        }}
      >
        {label}
      </span>
    </div>
  )
}

// ============================================================
// SSO BUTTONS
// ============================================================

const ssoBtnStyle: CSSProperties = {
  height: 42,
  padding: "0 12px",
  background: PAPER_INSET,
  border: "1px solid transparent",
  borderRadius: 8,
  color: INK,
  fontSize: 13,
  fontWeight: 500,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 8,
  cursor: "not-allowed",
  opacity: 0.7,
  fontFamily: "inherit",
}

export function SsoButtons() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 20 }}>
      <button type="button" disabled style={ssoBtnStyle} title="SSO Google ainda não conectado">
        <GoogleIcon /> Google
      </button>
      <button type="button" disabled style={ssoBtnStyle} title="SSO GitHub ainda não conectado">
        <GitHubIcon /> GitHub
      </button>
    </div>
  )
}

function GoogleIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 18 18">
      <path
        fill="#4285F4"
        d="M16.51 8.18c0-.49-.04-.96-.13-1.41H9v2.81h4.21a3.6 3.6 0 0 1-1.56 2.36v1.96h2.52c1.47-1.36 2.34-3.36 2.34-5.72z"
      />
      <path
        fill="#34A853"
        d="M9 16.5c2.11 0 3.88-.7 5.17-1.9l-2.52-1.96c-.7.47-1.6.75-2.65.75-2.04 0-3.76-1.38-4.38-3.23H1.93v2.03A7.5 7.5 0 0 0 9 16.5z"
      />
      <path
        fill="#FBBC05"
        d="M4.62 10.16A4.5 4.5 0 0 1 4.38 9c0-.4.07-.79.18-1.16V5.81H1.93A7.5 7.5 0 0 0 1.5 9c0 1.21.29 2.36.81 3.38l2.31-2.22z"
      />
      <path
        fill="#EA4335"
        d="M9 4.62c1.15 0 2.18.4 2.99 1.17l2.24-2.24A7.18 7.18 0 0 0 9 1.5 7.5 7.5 0 0 0 1.93 5.81l2.31 2.03c.62-1.85 2.34-3.22 4.76-3.22z"
      />
    </svg>
  )
}

function GitHubIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill={INK}>
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
    </svg>
  )
}

// ============================================================
// HERO SUPPORT BLOCKS
// ============================================================

export function StatRow({ items }: { items: { num: string; label: string }[] }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 32, fontSize: 13, color: "#6b7280" }}>
      {items.map((s, i) => (
        <Fragment key={s.label}>
          <div>
            <div
              style={{
                fontSize: 22,
                fontWeight: 700,
                color: INK,
                letterSpacing: "-0.02em",
              }}
            >
              {s.num}
            </div>
            <div style={{ fontSize: 12, color: "#6b7280", marginTop: 2 }}>{s.label}</div>
          </div>
          {i < items.length - 1 ? (
            <div style={{ width: 1, height: 32, background: "#d1d5db" }} />
          ) : null}
        </Fragment>
      ))}
    </div>
  )
}

export function ValueProps({ items }: { items: string[] }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 460 }}>
      {items.map((it) => (
        <div
          key={it}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            fontSize: 14,
            color: "#374151",
          }}
        >
          <span
            style={{
              width: 20,
              height: 20,
              borderRadius: "50%",
              background: ACCENT,
              color: "white",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              flex: "0 0 auto",
            }}
          >
            <CheckIcon size={12} />
          </span>
          {it}
        </div>
      ))}
    </div>
  )
}

export function NoteBlock({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        padding: "14px 16px",
        background: "rgba(99,102,241,0.06)",
        border: "1px solid rgba(99,102,241,0.18)",
        borderRadius: 8,
        fontSize: 13,
        color: "#374151",
        lineHeight: 1.5,
        maxWidth: 440,
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
      }}
    >
      <span
        style={{
          width: 18,
          height: 18,
          borderRadius: "50%",
          background: ACCENT,
          color: "white",
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          flex: "0 0 auto",
          fontSize: 11,
          fontWeight: 700,
          marginTop: 1,
        }}
      >
        i
      </span>
      <span>{children}</span>
    </div>
  )
}

export function Requirements({
  items,
  caption = "Sua nova senha precisa ter",
}: {
  items: { label: string; ok: boolean }[]
  caption?: string
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, maxWidth: 460 }}>
      <div
        style={{
          fontFamily: monoFamily,
          fontSize: 11,
          color: "#6b7280",
          textTransform: "uppercase",
          letterSpacing: "0.1em",
          fontWeight: 500,
          marginBottom: 4,
        }}
      >
        {caption}
      </div>
      {items.map((it) => (
        <div
          key={it.label}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            fontSize: 13,
            color: it.ok ? INK : "#9ca3af",
          }}
        >
          <span
            style={{
              width: 16,
              height: 16,
              borderRadius: "50%",
              background: it.ok ? ACCENT : "transparent",
              border: it.ok ? "none" : "1px solid #d1d5db",
              color: "white",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              flex: "0 0 auto",
            }}
          >
            {it.ok ? <CheckIcon size={10} /> : null}
          </span>
          {it.label}
        </div>
      ))}
    </div>
  )
}

export function CheckIcon({ size = 14 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 8.5l3.5 3.5L13 5" />
    </svg>
  )
}

export function ArrowRight({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 8h10M9 4l4 4-4 4" />
    </svg>
  )
}

// ============================================================
// Helpers
// ============================================================

export const AUTH_TOKENS = {
  INK,
  ACCENT,
  CREAM,
  PAPER,
  PAPER_INSET,
  BORDER_PAPER,
  monoFamily,
}
