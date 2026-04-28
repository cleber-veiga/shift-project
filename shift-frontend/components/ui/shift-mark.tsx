import type { CSSProperties, SVGProps } from "react"
import { cn } from "@/lib/utils"

export type ShiftMarkVariant = "dark" | "light" | "mono"

type ShiftMarkProps = Omit<SVGProps<SVGSVGElement>, "size"> & {
  size?: number
  variant?: ShiftMarkVariant
  radius?: number
  title?: string
}

const palettes = {
  dark: { bg: "#1a2030", stroke: "#7b8cff", letter: "#ffffff", border: undefined as string | undefined },
  light: { bg: "#ffffff", stroke: "#4a5bd4", letter: "#1a2030", border: "#1a2030" },
  mono: { bg: "transparent", stroke: "currentColor", letter: "currentColor", border: undefined },
} as const

export function ShiftMark({
  size = 32,
  variant = "dark",
  radius,
  title = "Shift",
  className,
  style,
  ...rest
}: ShiftMarkProps) {
  const palette = palettes[variant]
  const r = radius ?? Math.round(size * 0.22)
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
      {variant !== "mono" ? (
        <rect
          x="2"
          y="2"
          width="60"
          height="60"
          rx={r}
          fill={palette.bg}
          stroke={palette.border ?? "none"}
          strokeWidth={palette.border ? 1.5 : 0}
        />
      ) : null}
      <path
        d="M14 20 L8 32 L14 44"
        stroke={palette.stroke}
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <path
        d="M50 20 L56 32 L50 44"
        stroke={palette.stroke}
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <text
        x="32"
        y="44"
        textAnchor="middle"
        fontFamily="Inter, system-ui, sans-serif"
        fontSize="34"
        fontWeight={800}
        fill={palette.letter}
        letterSpacing="-0.04em"
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
}

export function ShiftMarkAdaptive({ size = 32, className, title }: ShiftMarkAdaptiveProps) {
  return (
    <>
      <span className={cn("inline-block dark:hidden", className)}>
        <ShiftMark size={size} variant="dark" title={title} />
      </span>
      <span className={cn("hidden dark:inline-block", className)}>
        <ShiftMark size={size} variant="light" title={title} />
      </span>
    </>
  )
}

export default ShiftMark
