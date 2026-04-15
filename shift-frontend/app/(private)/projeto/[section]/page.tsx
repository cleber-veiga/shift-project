import { notFound } from "next/navigation"
import { ContextSectionPage } from "@/components/dashboard/context-section-page"
import { isDashboardSection } from "@/lib/dashboard-navigation"

interface PageProps {
  params: Promise<{ section: string }>
}

export default async function ProjectSectionPage({ params }: PageProps) {
  const { section } = await params

  if (!isDashboardSection(section)) {
    notFound()
  }

  return <ContextSectionPage scope="project" section={section} />
}
