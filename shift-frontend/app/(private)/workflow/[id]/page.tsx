"use client"

import { use } from "react"
import { WorkflowEditor } from "@/components/workflow/workflow-editor"

interface WorkflowPageProps {
  params: Promise<{ id: string }>
}

export default function WorkflowPage({ params }: WorkflowPageProps) {
  const { id } = use(params)

  return (
    <WorkflowEditor
      workflowId={id}
      initialNodes={[]}
      initialEdges={[]}
    />
  )
}
