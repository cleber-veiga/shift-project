import { cn } from "@/lib/utils"
import { ShiftMark, type ShiftMarkVariant } from "@/components/ui/shift-mark"

type ShiftBrandProps = {
  size?: number
  variant?: ShiftMarkVariant
  showWordmark?: boolean
  glow?: boolean
  animated?: boolean
  className?: string
}

export function ShiftBrand({
  size = 56,
  variant = "dark",
  showWordmark = true,
  glow = true,
  animated = false,
  className,
}: ShiftBrandProps) {
  return (
    <div className={cn("relative flex flex-col items-center", className)}>
      <div className="relative">
        {glow ? (
          <>
            <span
              aria-hidden
              className="pointer-events-none absolute -inset-4 -z-10 rounded-full bg-[#6366f1]/25 blur-2xl"
            />
            <span
              aria-hidden
              className="pointer-events-none absolute -inset-8 -z-20 rounded-full bg-[#a5b4fc]/10 blur-3xl"
            />
          </>
        ) : null}
        <div className="rounded-2xl bg-gradient-to-br from-white/10 via-white/5 to-transparent p-px shadow-[0_10px_40px_-12px_rgba(99,102,241,0.55)]">
          <ShiftMark size={size} variant={variant} animated={animated} />
        </div>
      </div>
      {showWordmark ? (
        <span
          className="mt-3 text-[11px] font-semibold uppercase text-neutral-400"
          style={{
            fontFamily: '"Viasoft Regular", "Inter Tight", system-ui, sans-serif',
            letterSpacing: "0.42em",
          }}
        >
          SHIFT
        </span>
      ) : null}
    </div>
  )
}

export default ShiftBrand
