import type { CSSProperties, ReactNode } from "react"
import { cn } from "@/lib/utils"

const ACCENT = "#6366f1"
const ACCENT_LIGHT = "#a5b4fc"

// ============================================================
// ARC GEOMETRY (mesma do Wordmark)
// ============================================================
const ARC_W = 360
const ARC_H = 56
const archTop = 6
const arcStartX = 68
const arcEndX = 292
const arcStartY = 44
const arcEndY = 44
const cp1x = arcStartX + 8
const cp1y = archTop - 12
const cp2x = arcEndX - 8
const cp2y = archTop - 12
const ARC_PATH = `M ${arcStartX} ${arcStartY} C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${arcEndX} ${arcEndY}`

// Arredonda para 4 casas decimais — evita hydration mismatch entre Node e browser.
const round4 = (n: number) => Math.round(n * 10000) / 10000

const NUM_DOTS = 7
const DOTS = Array.from({ length: NUM_DOTS }).map((_, i) => {
  const t = i / (NUM_DOTS - 1)
  const x =
    Math.pow(1 - t, 3) * arcStartX +
    3 * Math.pow(1 - t, 2) * t * cp1x +
    3 * (1 - t) * t * t * cp2x +
    t * t * t * arcEndX
  const y =
    Math.pow(1 - t, 3) * arcStartY +
    3 * Math.pow(1 - t, 2) * t * cp1y +
    3 * (1 - t) * t * t * cp2y +
    t * t * t * arcEndY
  const weight = 0.5 + Math.sin(t * Math.PI * 0.85) * 0.6
  return {
    t: round4(t),
    x: round4(x),
    y: round4(y),
    r: round4(1.6 + weight * 1.4),
    opacity: round4(0.35 + Math.sin(t * Math.PI * 0.85) * 0.5),
  }
})

// ============================================================
// V1 · COMET LOOP
// Splash · page boot · long-running operations.
// ============================================================
type ShiftCometProps = {
  size?: number
  accent?: string
  dim?: string
  duration?: string
  className?: string
  ariaLabel?: string
}

export function ShiftComet({
  size = 200,
  accent = ACCENT,
  dim = ACCENT,
  duration = "1.6s",
  className,
  ariaLabel = "Carregando",
}: ShiftCometProps) {
  const id = `shift-comet-${accent.replace("#", "")}`
  return (
    <svg
      width={size}
      height={size * (ARC_H / ARC_W)}
      viewBox={`0 0 ${ARC_W} ${ARC_H}`}
      fill="none"
      role="status"
      aria-label={ariaLabel}
      className={className}
      style={{ overflow: "visible", display: "block" }}
    >
      <defs>
        <radialGradient id={`${id}-glow`}>
          <stop offset="0%" stopColor="white" stopOpacity="1" />
          <stop offset="40%" stopColor={accent} stopOpacity="0.9" />
          <stop offset="100%" stopColor={accent} stopOpacity="0" />
        </radialGradient>
      </defs>
      <path
        d={ARC_PATH}
        stroke={dim}
        strokeWidth="1"
        strokeDasharray="1 5"
        fill="none"
        opacity="0.22"
        strokeLinecap="round"
      />
      {DOTS.map((d, i) => (
        <circle key={i} cx={d.x} cy={d.y} r={d.r * 0.55} fill={dim} opacity={d.opacity * 0.35} />
      ))}
      {[0.25, 0.2, 0.15, 0.1, 0.06].map((delay, i) => (
        <circle key={i} r={2.6 - i * 0.4} fill={accent} opacity={0.55 - i * 0.09}>
          <animateMotion
            dur={duration}
            repeatCount="indefinite"
            begin={`-${delay}s`}
            keyPoints="0;1"
            keyTimes="0;1"
            calcMode="spline"
            keySplines="0.4 0 0.2 1"
            path={ARC_PATH}
            rotate="auto"
          />
        </circle>
      ))}
      <circle r="9" fill={`url(#${id}-glow)`}>
        <animateMotion
          dur={duration}
          repeatCount="indefinite"
          calcMode="spline"
          keyTimes="0;1"
          keySplines="0.4 0 0.2 1"
          path={ARC_PATH}
        />
      </circle>
      <circle r="3.4" fill="white">
        <animateMotion
          dur={duration}
          repeatCount="indefinite"
          calcMode="spline"
          keyTimes="0;1"
          keySplines="0.4 0 0.2 1"
          path={ARC_PATH}
        />
      </circle>
    </svg>
  )
}

// ============================================================
// V4 · ARC SPINNER
// Inline · button loading · request pending.
// ============================================================
type ShiftSpinnerProps = {
  size?: number | string
  color?: string
  className?: string
  ariaLabel?: string
  style?: CSSProperties
}

export function ShiftSpinner({
  size,
  color = "currentColor",
  className,
  ariaLabel = "Carregando",
  style,
}: ShiftSpinnerProps) {
  const N = 8
  const wrapperStyle: CSSProperties = {
    display: "inline-block",
    verticalAlign: "middle",
    animation: "shift-rotate-cw 1.2s linear infinite",
    ...(size != null
      ? { width: typeof size === "number" ? `${size}px` : size, height: typeof size === "number" ? `${size}px` : size }
      : {}),
    ...style,
  }
  return (
    <span
      role="status"
      aria-label={ariaLabel}
      className={className}
      style={wrapperStyle}
    >
      <svg
        width="100%"
        height="100%"
        viewBox="0 0 64 64"
        fill="none"
        style={{ display: "block" }}
      >
        {Array.from({ length: N }).map((_, i) => {
          const angle = (i / N) * Math.PI * 2 - Math.PI / 2
          const r = 24
          const x = round4(32 + Math.cos(angle) * r)
          const y = round4(32 + Math.sin(angle) * r)
          const t = i / (N - 1)
          const weight = 0.4 + (1 - t) * 0.9
          return (
            <circle
              key={i}
              cx={x}
              cy={y}
              r={round4(1.6 + weight * 1.6)}
              fill={color}
              opacity={round4(0.2 + (1 - t) * 0.8)}
            />
          )
        })}
      </svg>
    </span>
  )
}

// ============================================================
// V6 · SHIMMER BAR
// Top-of-page progress · indeterminate.
// ============================================================
type ShiftShimmerBarProps = {
  width?: number | string
  height?: number
  color?: string
  track?: string
  className?: string
  style?: CSSProperties
}

export function ShiftShimmerBar({
  width = "100%",
  height = 4,
  color = "var(--primary, #6366f1)",
  track = "var(--muted, #f3f4f6)",
  className,
  style,
}: ShiftShimmerBarProps) {
  return (
    <div
      className={className}
      style={{
        width,
        height,
        borderRadius: height / 2,
        background: track,
        position: "relative",
        overflow: "hidden",
        ...style,
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          width: "40%",
          background: `linear-gradient(90deg, transparent 0%, ${color} 50%, transparent 100%)`,
          animation: "shift-shimmer 1.4s linear infinite",
        }}
      />
    </div>
  )
}

// ============================================================
// SKELETON BLOCK
// Placeholder com shimmer indigo (300ms — 1s).
// ============================================================
type SkeletonProps = {
  className?: string
  style?: CSSProperties
  width?: number | string
  height?: number | string
  rounded?: number | "full"
}

export function Skeleton({ className, style, width, height, rounded }: SkeletonProps) {
  const radius = rounded === "full" ? 9999 : rounded ?? 4
  return (
    <span
      aria-hidden
      className={cn("shift-skeleton block", className)}
      style={{
        width: width ?? "100%",
        height: height ?? 12,
        borderRadius: radius,
        ...style,
      }}
    />
  )
}

// ============================================================
// SPLASH (full-screen) — V1 Comet + label
// ============================================================
type ShiftSplashProps = {
  label?: ReactNode
  variant?: "light" | "dark"
  className?: string
}

export function ShiftSplash({ label, variant = "light", className }: ShiftSplashProps) {
  const onDark = variant === "dark"
  const accent = onDark ? ACCENT_LIGHT : ACCENT
  return (
    <div
      className={cn(
        "flex min-h-screen flex-col items-center justify-center gap-6 px-4",
        onDark ? "bg-[#0e1220] text-[#f5f4ee]" : "bg-background text-foreground",
        className,
      )}
      role="status"
      aria-live="polite"
    >
      <ShiftComet size={280} accent={accent} dim={accent} />
      {label ? (
        <div className="text-center">
          <div
            className="font-mono text-[11px] uppercase tracking-[0.2em]"
            style={{ color: onDark ? "rgba(245,244,238,0.55)" : "var(--muted-foreground, #6b7280)" }}
          >
            SHIFT
          </div>
          <div
            className="mt-1.5 text-sm"
            style={{ color: onDark ? "rgba(245,244,238,0.7)" : "var(--muted-foreground, #6b7280)" }}
          >
            {label}
          </div>
        </div>
      ) : null}
    </div>
  )
}
