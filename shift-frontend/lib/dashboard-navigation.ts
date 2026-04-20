import { Activity, AlertTriangle, Boxes, Building2, FileSpreadsheet, GitBranch, Home, KeyRound, Plug2, ShieldCheck, Users, type LucideIcon } from "lucide-react"

export type DashboardScope = "space" | "project"
export type DashboardSection = "visao-geral" | "grupo-economico" | "conexoes" | "fluxos" | "nos-personalizados" | "modelos-entrada" | "dead-letters" | "membros" | "controle-acesso" | "agent-activity" | "chaves-api"

type SectionDefinition = {
  slug: DashboardSection
  label: string
  description: string
  icon: LucideIcon
  /** Minimum workspace role required to see this section. Defaults to VIEWER. */
  minWorkspaceRole?: "VIEWER" | "CONSULTANT" | "MANAGER"
}

type HeaderMeta = {
  groupTitle: string
  pageTitle: string
}

export type DashboardNavigationItem = {
  scope: DashboardScope
  slug: DashboardSection
  label: string
  description: string
  href: string
  icon: LucideIcon
  minWorkspaceRole?: "VIEWER" | "CONSULTANT" | "MANAGER"
}

const sectionDefinitions: SectionDefinition[] = [
  {
    slug: "visao-geral",
    label: "Visão Geral",
    description: "Resumo do contexto atual e dos principais atalhos deste escopo.",
    icon: Home,
    minWorkspaceRole: "MANAGER",
  },
  {
    slug: "grupo-economico",
    label: "Grupo Econômico",
    description: "Gerencie os grupos econômicos disponíveis neste escopo.",
    icon: Building2,
  },
  {
    slug: "conexoes",
    label: "Conexões",
    description: "Visualize e organize as conexões disponíveis neste escopo.",
    icon: Plug2,
    minWorkspaceRole: "MANAGER",
  },
  {
    slug: "fluxos",
    label: "Fluxos",
    description: "Acompanhe e mantenha os fluxos configurados neste escopo.",
    icon: GitBranch,
    minWorkspaceRole: "MANAGER",
  },
  {
    slug: "nos-personalizados",
    label: "Nós Personalizados",
    description: "Cadastre nós compostos reutilizáveis (multi-tabela) que aparecem na paleta do editor.",
    icon: Boxes,
    minWorkspaceRole: "MANAGER",
  },
  {
    slug: "modelos-entrada",
    label: "Modelos de Entrada",
    description: "Defina templates de Excel/CSV para padronizar a importação de dados.",
    icon: FileSpreadsheet,
    minWorkspaceRole: "MANAGER",
  },
  {
    slug: "dead-letters",
    label: "Dead Letters",
    description: "Linhas problemáticas capturadas durante execuções de fluxos com retry manual.",
    icon: AlertTriangle,
    minWorkspaceRole: "CONSULTANT",
  },
  {
    slug: "membros",
    label: "Membros",
    description: "Gerencie os acessos e participantes vinculados a este escopo.",
    icon: Users,
    minWorkspaceRole: "MANAGER",
  },
  {
    slug: "controle-acesso",
    label: "Controle de Acesso",
    description: "Matriz de acessos consolidada: veja e gerencie quem pode acessar cada projeto.",
    icon: ShieldCheck,
    minWorkspaceRole: "MANAGER",
  },
  {
    slug: "agent-activity",
    label: "Atividade do Agente",
    description: "Audite chamadas do Platform Agent: ferramentas executadas, aprovacoes e avisos de seguranca.",
    icon: Activity,
    minWorkspaceRole: "MANAGER",
  },
  {
    slug: "chaves-api",
    label: "Chaves de API",
    description: "Emita e revogue chaves para o MCP Server do Shift (Claude Desktop, n8n, integrações externas).",
    icon: KeyRound,
    minWorkspaceRole: "MANAGER",
  },
]

const sectionMap = Object.fromEntries(sectionDefinitions.map((section) => [section.slug, section])) as Record<
  DashboardSection,
  SectionDefinition
>

export function isDashboardSection(value: string): value is DashboardSection {
  return value in sectionMap
}

export function getDashboardHref(scope: DashboardScope, section: DashboardSection) {
  if (scope === "space" && section === "visao-geral") return "/home"
  return `/${scope === "space" ? "espaco" : "projeto"}/${section}`
}

export function getDashboardSectionMeta(scope: DashboardScope, section: DashboardSection): DashboardNavigationItem {
  const definition = sectionMap[section]

  return {
    scope,
    slug: section,
    label: definition.label,
    description: definition.description,
    href: getDashboardHref(scope, section),
    icon: definition.icon,
    minWorkspaceRole: definition.minWorkspaceRole,
  }
}

function buildNavigationItems(scope: DashboardScope) {
  if (scope === "project") {
    return sectionDefinitions
      .filter(
        (section) =>
          section.slug !== "grupo-economico" &&
          section.slug !== "modelos-entrada" &&
          section.slug !== "controle-acesso" &&
          section.slug !== "dead-letters" &&
          section.slug !== "membros" &&
          section.slug !== "agent-activity" &&
          section.slug !== "chaves-api",
      )
      .map((section) => getDashboardSectionMeta(scope, section.slug))
  }

  return sectionDefinitions
    .filter(
      (section) =>
        section.slug !== "agent-activity" &&
        section.slug !== "membros" &&
        section.slug !== "controle-acesso" &&
        section.slug !== "chaves-api",
    )
    .map((section) => getDashboardSectionMeta(scope, section.slug))
}

export const dashboardNavigationGroups = [
  {
    key: "space" as const,
    title: "Espaço",
    items: buildNavigationItems("space"),
  },
  {
    key: "project" as const,
    title: "Projeto",
    items: buildNavigationItems("project"),
  },
]

export function getHeaderMetaFromPathname(pathname: string): HeaderMeta {
  if (pathname === "/home") {
    return {
      groupTitle: "Espaço",
      pageTitle: "Visão Geral",
    }
  }

  const spaceMatch = pathname.match(/^\/espaco\/([^/]+)/)
  if (spaceMatch && isDashboardSection(spaceMatch[1])) {
    return {
      groupTitle: "Espaço",
      pageTitle: sectionMap[spaceMatch[1]].label,
    }
  }

  const projectMatch = pathname.match(/^\/projeto\/([^/]+)/)
  if (projectMatch && isDashboardSection(projectMatch[1])) {
    return {
      groupTitle: "Projeto",
      pageTitle: sectionMap[projectMatch[1]].label,
    }
  }

  if (pathname.startsWith("/configuracoes")) {
    const tabMap: Record<string, string> = {
      "/configuracoes/aparencia": "Aparência",
      "/configuracoes/espaco/membros": "Membros (Espaço)",
      "/configuracoes/espaco/controle-acesso": "Controle de Acesso",
      "/configuracoes/espaco/chaves-api": "Chaves de API (Espaço)",
      "/configuracoes/projeto/membros": "Membros (Projeto)",
      "/configuracoes/projeto/atividade-agente": "Atividade do Agente",
      "/configuracoes/projeto/chaves-api": "Chaves de API (Projeto)",
    }
    const match = Object.keys(tabMap).find((p) => pathname === p || pathname.startsWith(`${p}/`))
    return {
      groupTitle: "Configurações",
      pageTitle: match ? tabMap[match] : "Configurações",
    }
  }

  if (pathname.startsWith("/workflow/")) {
    return {
      groupTitle: "Espaço",
      pageTitle: "Editor de Fluxo",
    }
  }

  if (pathname.startsWith("/workspaces/")) {
    return {
      groupTitle: "Espaço",
      pageTitle: "Workspace",
    }
  }

  return {
    groupTitle: "Painel",
    pageTitle: "Home",
  }
}
