import { Building2, GitBranch, Home, Plug2, Users, type LucideIcon } from "lucide-react"

export type DashboardScope = "space" | "project"
export type DashboardSection = "visao-geral" | "grupo-economico" | "conexoes" | "fluxos" | "membros"

type SectionDefinition = {
  slug: DashboardSection
  label: string
  description: string
  icon: LucideIcon
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
}

const sectionDefinitions: SectionDefinition[] = [
  {
    slug: "visao-geral",
    label: "Visão Geral",
    description: "Resumo do contexto atual e dos principais atalhos deste escopo.",
    icon: Home,
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
  },
  {
    slug: "fluxos",
    label: "Fluxos",
    description: "Acompanhe e mantenha os fluxos configurados neste escopo.",
    icon: GitBranch,
  },
  {
    slug: "membros",
    label: "Membros",
    description: "Gerencie os acessos e participantes vinculados a este escopo.",
    icon: Users,
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
  }
}

function buildNavigationItems(scope: DashboardScope) {
  if (scope === "project") {
    return sectionDefinitions
      .filter((section) => section.slug !== "grupo-economico")
      .map((section) => getDashboardSectionMeta(scope, section.slug))
  }

  return sectionDefinitions.map((section) => getDashboardSectionMeta(scope, section.slug))
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
