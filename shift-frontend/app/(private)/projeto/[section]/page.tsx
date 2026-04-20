import { notFound, redirect } from "next/navigation"
import { ContextSectionPage } from "@/components/dashboard/context-section-page"
import { isDashboardSection } from "@/lib/dashboard-navigation"

interface PageProps {
  params: Promise<{ section: string }>
}

const MOVED_TO_CONFIGURACOES: Record<string, string> = {
  membros: "/configuracoes/projeto/membros",
  "agent-activity": "/configuracoes/projeto/atividade-agente",
  "chaves-api": "/configuracoes/projeto/chaves-api",
}

export default async function ProjectSectionPage({ params }: PageProps) {
  const { section } = await params

  if (MOVED_TO_CONFIGURACOES[section]) {
    redirect(MOVED_TO_CONFIGURACOES[section])
  }

  if (!isDashboardSection(section)) {
    notFound()
  }

  return <ContextSectionPage scope="project" section={section} />
}
