import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  LabelHTMLAttributes,
  ReactNode,
} from "react"
import { cn } from "@/lib/utils"
import { MorphLoader } from "@/components/ui/morph-loader"

export function AuthLabel({
  className,
  ...props
}: LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn("mb-2 block text-sm font-medium text-foreground", className)}
      {...props}
    />
  )
}

export function AuthInput({
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "flex h-12 w-full rounded-2xl border border-input bg-background/75 px-4 text-sm text-foreground placeholder:text-muted-foreground/80 focus:border-foreground/25 focus:outline-none focus:ring-4 focus:ring-foreground/8",
        className
      )}
      {...props}
    />
  )
}

type AuthButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  loading?: boolean
  variant?: "primary" | "secondary"
}

export function AuthButton({
  children,
  className,
  loading,
  variant = "primary",
  disabled,
  ...props
}: AuthButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex h-12 w-full items-center justify-center gap-2 rounded-2xl px-4 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60",
        variant === "primary" &&
          "bg-primary text-primary-foreground shadow-[0_18px_40px_color-mix(in_oklab,var(--foreground)_16%,transparent)] hover:opacity-92",
        variant === "secondary" &&
          "border border-border bg-card text-card-foreground hover:bg-accent",
        className
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? <MorphLoader className="size-4" /> : children}
    </button>
  )
}

export function SocialButton({
  children,
  icon,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  icon: ReactNode
}) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex h-12 w-full items-center justify-center gap-2 rounded-2xl border border-border bg-card/75 px-4 text-sm font-medium text-card-foreground transition hover:bg-accent",
        className
      )}
      {...props}
    >
      {icon}
      {children}
    </button>
  )
}

export function Divider({ label }: { label: string }) {
  return (
    <div className="relative py-1">
      <div className="absolute inset-0 flex items-center">
        <div className="w-full border-t border-border/80" />
      </div>
      <div className="relative flex justify-center">
        <span className="bg-card px-3 text-xs uppercase tracking-[0.2em] text-muted-foreground">
          {label}
        </span>
      </div>
    </div>
  )
}

export function GoogleMark() {
  return (
    <svg className="size-4" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M21.81 12.23c0-.72-.06-1.25-.19-1.8H12.2v3.4h5.53a4.8 4.8 0 0 1-2.05 3.14l3.04 2.35c1.78-1.65 3.09-4.08 3.09-7.09Z"
        fill="#4285F4"
      />
      <path
        d="M12.2 22c2.7 0 4.97-.89 6.63-2.4l-3.04-2.35c-.85.57-1.93.9-3.59.9-2.61 0-4.82-1.76-5.61-4.13H3.46v2.42A9.99 9.99 0 0 0 12.2 22Z"
        fill="#34A853"
      />
      <path
        d="M6.59 14.02A6.1 6.1 0 0 1 6.26 12c0-.7.12-1.38.33-2.02V7.56H3.46A9.97 9.97 0 0 0 2.4 12c0 1.59.38 3.09 1.06 4.44l3.13-2.42Z"
        fill="#FBBC05"
      />
      <path
        d="M12.2 5.85c1.77 0 3.03.76 3.72 1.4l2.71-2.71C17.16 3.17 14.88 2 12.2 2a9.99 9.99 0 0 0-8.74 5.56l3.13 2.42c.79-2.37 3-4.13 5.61-4.13Z"
        fill="#EA4335"
      />
    </svg>
  )
}
