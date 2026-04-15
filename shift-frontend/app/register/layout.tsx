import type { ReactNode } from "react"
import { ForcedDarkLayout } from "@/components/auth/forced-dark-layout"

export default function RegisterLayout({ children }: { children: ReactNode }) {
  return <ForcedDarkLayout>{children}</ForcedDarkLayout>
}
