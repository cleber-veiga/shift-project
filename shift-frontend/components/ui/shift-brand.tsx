import { cn } from "@/lib/utils"
import { ShiftMark, type ShiftMarkVariant } from "@/components/ui/shift-mark"

type ShiftBrandProps = {
  size?: number
  variant?: ShiftMarkVariant
  showWordmark?: boolean
  glow?: boolean
  className?: string
}

export function ShiftBrand({
  size = 56,
  variant = "dark",
  showWordmark = true,
  glow = true,
  className,
}: ShiftBrandProps) {
  return (
    <div className={cn("relative flex flex-col items-center", className)}>
      <div className="relative">
        {glow ? (
          <>
            <span
              aria-hidden
              className="pointer-events-none absolute -inset-4 -z-10 rounded-full bg-indigo-500/25 blur-2xl"
            />
            <span
              aria-hidden
              className="pointer-events-none absolute -inset-8 -z-20 rounded-full bg-violet-500/10 blur-3xl"
            />
          </>
        ) : null}
        <div className="rounded-2xl bg-gradient-to-br from-white/15 via-white/5 to-transparent p-px shadow-[0_10px_40px_-12px_rgba(123,140,255,0.55)]">
          <ShiftMark size={size} variant={variant} />
        </div>
      </div>
      {showWordmark ? (
        <span className="mt-3 text-[11px] font-semibold uppercase tracking-[0.42em] text-neutral-400">
          Shift
        </span>
      ) : null}
    </div>
  )
}

export default ShiftBrand
