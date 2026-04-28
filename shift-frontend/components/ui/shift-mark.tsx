import type { CSSProperties, SVGProps } from "react"
import { cn } from "@/lib/utils"

export type ShiftMarkVariant = "dark" | "light" | "mono"

const INK = "#0e1220"
const PAPER = "#fdfcf7"
const ACCENT = "#6366f1"
const ACCENT_LIGHT = "#a5b4fc"

type Palette = {
  bg: string
  letter: string
  accent: string
  border?: string
}

const palettes: Record<ShiftMarkVariant, Palette> = {
  dark: { bg: INK, letter: "#ffffff", accent: ACCENT_LIGHT },
  light: { bg: PAPER, letter: INK, accent: ACCENT, border: "rgba(14,18,32,0.08)" },
  mono: { bg: "transparent", letter: "currentColor", accent: "currentColor" },
}

const ARC = {
  startX: 20,
  endX: 44,
  startY: 24,
  endY: 24,
  cp1x: 22,
  cp1y: 14,
  cp2x: 42,
  cp2y: 14,
}

const DOT_STOPS = [0, 0.2, 0.4, 0.6, 0.8, 1] as const

function arcPoint(t: number) {
  const { startX, startY, endX, endY, cp1x, cp1y, cp2x, cp2y } = ARC
  const x =
    Math.pow(1 - t, 3) * startX +
    3 * Math.pow(1 - t, 2) * t * cp1x +
    3 * (1 - t) * t * t * cp2x +
    t * t * t * endX
  const y =
    Math.pow(1 - t, 3) * startY +
    3 * Math.pow(1 - t, 2) * t * cp1y +
    3 * (1 - t) * t * t * cp2y +
    t * t * t * endY
  return { x, y }
}

type ShiftMarkProps = Omit<SVGProps<SVGSVGElement>, "size"> & {
  size?: number
  variant?: ShiftMarkVariant
  radius?: number
  title?: string
  animated?: boolean
}

export function ShiftMark({
  size = 32,
  variant = "dark",
  radius,
  title = "Shift",
  className,
  style,
  animated = false,
  ...rest
}: ShiftMarkProps) {
  const palette = palettes[variant]
  const r = radius ?? Math.round(size * 0.22)
  const haloId = `shift-mark-halo-${variant}-${size}`
  const mergedStyle: CSSProperties = { display: "block", ...style }

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      role="img"
      aria-label={title}
      className={className}
      style={mergedStyle}
      {...rest}
    >
      <defs>
        <radialGradient id={haloId}>
          <stop offset="0%" stopColor={palette.accent} stopOpacity="0.55" />
          <stop offset="100%" stopColor={palette.accent} stopOpacity="0" />
        </radialGradient>
      </defs>

      {variant !== "mono" ? (
        <rect
          x="2"
          y="2"
          width="60"
          height="60"
          rx={r}
          fill={palette.bg}
          stroke={palette.border ?? "none"}
          strokeWidth={palette.border ? 1 : 0}
        />
      ) : null}

      <path
        d={`M ${ARC.startX} ${ARC.startY} C ${ARC.cp1x} ${ARC.cp1y}, ${ARC.cp2x} ${ARC.cp2y}, ${ARC.endX} ${ARC.endY}`}
        stroke={palette.accent}
        strokeWidth="0.8"
        strokeLinecap="round"
        strokeDasharray="0.8 2.5"
        fill="none"
        opacity="0.4"
      />

      {DOT_STOPS.map((t) => {
        const { x, y } = arcPoint(t)
        const r = 0.7 + Math.sin(t * Math.PI * 0.85) * 0.6
        const opacity = 0.35 + Math.sin(t * Math.PI * 0.85) * 0.5
        return <circle key={t} cx={x} cy={y} r={r} fill={palette.accent} opacity={opacity} />
      })}

      <circle cx={ARC.endX} cy={ARC.endY} r="4" fill={`url(#${haloId})`} />
      <circle cx={ARC.endX} cy={ARC.endY} r="2.2" fill={palette.accent}>
        {animated ? (
          <animate attributeName="opacity" values="1;0.5;1" dur="2s" repeatCount="indefinite" />
        ) : null}
      </circle>
      {animated ? (
        <circle cx={ARC.endX} cy={ARC.endY} r="2.2" fill={palette.accent} opacity="0.4">
          <animate attributeName="r" values="2.2;6;2.2" dur="2s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.4;0;0.4" dur="2s" repeatCount="indefinite" />
        </circle>
      ) : null}

      <text
        x="32"
        y="49.5"
        textAnchor="middle"
        fontFamily='"Viasoft Regular", "Inter Tight", system-ui, sans-serif'
        fontSize="32"
        fontWeight={400}
        fill={palette.letter}
        letterSpacing="0"
      >
        S
      </text>
    </svg>
  )
}

type ShiftMarkAdaptiveProps = {
  size?: number
  className?: string
  title?: string
  animated?: boolean
}

export function ShiftMarkAdaptive({ size = 32, className, title, animated }: ShiftMarkAdaptiveProps) {
  return (
    <>
      <span className={cn("inline-block dark:hidden", className)}>
        <ShiftMark size={size} variant="light" title={title} animated={animated} />
      </span>
      <span className={cn("hidden dark:inline-block", className)}>
        <ShiftMark size={size} variant="dark" title={title} animated={animated} />
      </span>
    </>
  )
}

type ShiftWordmarkProps = {
  scale?: number
  variant?: ShiftMarkVariant
  animated?: boolean
  showTagline?: boolean
  className?: string
  title?: string
}

const W_INK = INK
const W_LIGHT_INK = "#ffffff"

export function ShiftWordmark({
  scale = 1,
  variant = "light",
  animated = false,
  showTagline = false,
  className,
  title = "Shift",
}: ShiftWordmarkProps) {
  const palette = palettes[variant]
  const ink =
    variant === "dark" ? W_LIGHT_INK : variant === "mono" ? "currentColor" : W_INK
  const accent = palette.accent

  const W = 360
  const H = showTagline ? 150 : 130
  const baseY = 100
  const archTop = 6
  const arcStartX = 68
  const arcEndX = 292
  const arcStartY = 44
  const arcEndY = 44

  const NUM = 7
  const dotsArc = Array.from({ length: NUM }).map((_, i) => {
    const t = i / (NUM - 1)
    const cp1x = arcStartX + 8
    const cp1y = archTop - 12
    const cp2x = arcEndX - 8
    const cp2y = archTop - 12
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
      x,
      y,
      r: 1.6 + weight * 1.4,
      opacity: 0.35 + Math.sin(t * Math.PI * 0.85) * 0.5,
    }
  })

  const haloId = `shift-wordmark-halo-${variant}`

  return (
    <svg
      width={W * scale}
      height={H * scale}
      viewBox={`0 0 ${W} ${H}`}
      fill="none"
      role="img"
      aria-label={title}
      className={className}
      style={{ overflow: "visible", display: "block" }}
    >
      <defs>
        <radialGradient id={haloId}>
          <stop offset="0%" stopColor={accent} stopOpacity="0.6" />
          <stop offset="100%" stopColor={accent} stopOpacity="0" />
        </radialGradient>
      </defs>

      <path
        d={`M ${arcStartX} ${arcStartY} C ${arcStartX + 8} ${archTop - 10}, ${arcEndX - 8} ${
          archTop - 10
        }, ${arcEndX} ${arcEndY}`}
        stroke={accent}
        strokeWidth="1"
        strokeLinecap="round"
        strokeDasharray="1 5"
        fill="none"
        opacity="0.35"
      />

      {dotsArc.map((d, i) => (
        <circle key={i} cx={d.x} cy={d.y} r={d.r} fill={accent} opacity={d.opacity} />
      ))}

      <circle cx={arcEndX} cy={arcEndY} r="14" fill={`url(#${haloId})`} />
      <circle cx={arcEndX} cy={arcEndY} r="4.5" fill={accent}>
        {animated ? (
          <animate attributeName="opacity" values="1;0.5;1" dur="2s" repeatCount="indefinite" />
        ) : null}
      </circle>
      {animated ? (
        <circle cx={arcEndX} cy={arcEndY} r="4.5" fill={accent} opacity="0.4">
          <animate attributeName="r" values="4.5;14;4.5" dur="2s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.4;0;0.4" dur="2s" repeatCount="indefinite" />
        </circle>
      ) : null}

      <text
        x={W / 2}
        y={baseY}
        textAnchor="middle"
        fontFamily='"Viasoft Regular", "Inter Tight", system-ui, sans-serif'
        fontSize="64"
        fontWeight={400}
        fill={ink}
        letterSpacing="0"
      >
        SHIFT
      </text>

      {showTagline ? (
        <text
          x={W / 2}
          y={baseY + 32}
          textAnchor="middle"
          fontFamily='"JetBrains Mono", ui-monospace, monospace'
          fontSize="9"
          fontWeight={500}
          fill={ink}
          opacity="0.55"
          letterSpacing="0.32em"
        >
          DATA  ·  IN  ·  MOTION
        </text>
      ) : null}
    </svg>
  )
}

export default ShiftMark
