/**
 * Maps icon name strings from the node registry to Lucide React components.
 */
import {
  ArrowRightLeft,
  BarChart3,
  Braces,
  Calculator,
  Clock,
  Code,
  Database,
  DatabaseZap,
  FileSpreadsheet,
  Filter,
  Globe,
  MousePointerClick,
  RefreshCw,
  Send,
  Sheet,
  Sparkles,
  Webhook,
  type LucideIcon,
} from "lucide-react"

const iconMap: Record<string, LucideIcon> = {
  ArrowRightLeft,
  BarChart3,
  Braces,
  Calculator,
  Clock,
  Code,
  Database,
  DatabaseZap,
  FileSpreadsheet,
  Filter,
  Globe,
  MousePointerClick,
  RefreshCw,
  Send,
  Sheet,
  Sparkles,
  Webhook,
}

export function getNodeIcon(name: string): LucideIcon {
  return iconMap[name] ?? Database
}
