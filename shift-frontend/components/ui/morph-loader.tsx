import { cn } from "@/lib/utils"

type MorphLoaderProps = {
  className?: string
}

export function MorphLoader({ className }: MorphLoaderProps) {
  return <span className={cn("morph-loader", className)} aria-hidden="true" />
}

