// Base fields shared by all context variants
export interface AIContextBase {
  workspaceId: string | null
  workspaceName: string | null
  projectId: string | null
  projectName: string | null
  userRole: {
    workspace: "VIEWER" | "CONSULTANT" | "MANAGER" | null
    project: "CLIENT" | "EDITOR" | null
  }
}

export interface AIContextHome extends AIContextBase {
  section: "home"
  stats: {
    workflowsCount: number
    connectionsCount: number
    recentExecutions: number
  }
}

export interface AIContextWorkflowsList extends AIContextBase {
  section: "workflows_list"
  scope: "workspace" | "project"
  workflows: Array<{
    id: string
    name: string
    status: "active" | "inactive" | "draft"
    lastExecution: {
      status: "success" | "failed" | "running" | null
      at: string | null
    }
  }>
}

export interface AIContextWorkflowEditor extends AIContextBase {
  section: "workflow_editor"
  workflow: {
    id: string
    name: string
    status: string
    nodeCount: number
    lastSavedAt: string | null
  }
  selectedNodeIds: string[]
}

export interface AIContextConnections extends AIContextBase {
  section: "connections"
  scope: "workspace" | "project"
  connections: Array<{
    id: string
    name: string
    type: string
    isPublic: boolean
  }>
}

export interface AIContextPlayground extends AIContextBase {
  section: "playground"
  connection: {
    id: string
    name: string
    type: string
  }
}

export interface AIContextMembers extends AIContextBase {
  section: "project_members"
  members: Array<{
    userId: string
    email: string
    role: "CLIENT" | "EDITOR"
  }>
}

export interface AIContextOther extends AIContextBase {
  section: "other"
  pathname: string
}

export type AIContext =
  | AIContextHome
  | AIContextWorkflowsList
  | AIContextWorkflowEditor
  | AIContextConnections
  | AIContextPlayground
  | AIContextMembers
  | AIContextOther

export interface AIContextEmpty {
  section: "unknown"
  pathname: string
}

export type AIContextValue = AIContext | AIContextEmpty
