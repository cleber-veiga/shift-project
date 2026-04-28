import { cn } from "@/lib/utils"
import { ShiftSpinner } from "@/components/ui/shift-loader"

type MorphLoaderProps = {
  className?: string
}

/**
 * Loader inline padrão do Shift — V4 Arc Spinner (8 dots em círculo
 * com peso decrescente, rotação 1.2s linear).
 *
 * Mantém o nome legado `MorphLoader` para compatibilidade com os 85+
 * usos espalhados pela app. A cor herda do contexto (`currentColor`)
 * e o tamanho vem do `className` (ex.: `size-4`, `size-14`).
 *
 * Para splash/full-screen use `<ShiftSplash>` ou `<ShiftComet>`.
 */
export function MorphLoader({ className }: MorphLoaderProps) {
  return (
    <ShiftSpinner
      className={cn("size-4 align-middle", className)}
      color="currentColor"
    />
  )
}
