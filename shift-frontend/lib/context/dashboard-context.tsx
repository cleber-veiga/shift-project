"use client"

import {
  clearSelectedProjectId,
  clearSelectedWorkspaceId,
  createOrganization,
  createWorkspaceProject,
  createWorkspace,
  updateProject,
  deleteProject,
  fetchMe,
  getSelectedOrganizationId,
  getSelectedProjectId,
  getSelectedWorkspaceId,
  getValidSession,
  listOrganizations,
  listOrganizationWorkspaces,
  listWorkspaceProjects,
  setSelectedOrganizationId,
  setSelectedProjectId as persistSelectedProjectId,
  setSelectedWorkspaceId as persistSelectedWorkspaceId,
  type Organization,
  type OrganizationRole,
  type Project,
  type CreateProjectPayload,
  type Workspace,
} from "@/lib/auth"
import { useRouter } from "next/navigation"
import { createContext, useContext, useEffect, useMemo, useState } from "react"

type OrganizationWithRole = Organization & {
  role: OrganizationRole | "MEMBER"
}

interface DashboardContextType {
  organizations: OrganizationWithRole[]
  workspacesByOrg: Record<string, Workspace[]>
  projectsByWorkspace: Record<string, Project[]>
  selectedOrgId: string | null
  selectedWorkspaceId: string | null
  selectedProjectId: string | null
  isLoading: boolean
  error: string
  setSelectedOrgId: (id: string) => void
  setSelectedWorkspaceId: (id: string) => void
  setSelectedProjectId: (id: string) => void
  selectedOrganization: OrganizationWithRole | null
  availableWorkspaces: Workspace[]
  selectedWorkspace: Workspace | null
  availableProjects: Project[]
  selectedProject: Project | null
  loadWorkspacesForOrganization: (orgId: string, preferredWorkspaceId?: string | null) => Promise<void>
  loadProjectsForWorkspace: (workspaceId: string, preferredProjectId?: string | null) => Promise<void>
  reloadOrganizations: (preferredOrgId?: string | null) => Promise<void>
  createOrganizationAndSelect: (payload: { name: string }) => Promise<OrganizationWithRole>
  createWorkspaceAndSelect: (payload: { organization_id: string; name: string; erp_id?: string | null }) => Promise<Workspace>
  createProjectAndSelect: (payload: { workspace_id: string } & CreateProjectPayload) => Promise<Project>
  updateProjectAndRefresh: (
    payload: { project_id: string; workspace_id: string } & CreateProjectPayload
  ) => Promise<Project>
  deleteProjectAndRefresh: (payload: { project_id: string; workspace_id: string }) => Promise<void>
}

const DashboardContext = createContext<DashboardContextType | undefined>(undefined)

export function DashboardProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState("")
  const [organizations, setOrganizations] = useState<OrganizationWithRole[]>([])
  const [workspacesByOrg, setWorkspacesByOrg] = useState<Record<string, Workspace[]>>({})
  const [projectsByWorkspace, setProjectsByWorkspace] = useState<Record<string, Project[]>>({})
  const [selectedOrgId, setSelectedOrgIdState] = useState<string | null>(null)
  const [selectedWorkspaceId, setSelectedWorkspaceIdState] = useState<string | null>(null)
  const [selectedProjectId, setSelectedProjectIdState] = useState<string | null>(null)

  const selectedOrganization = useMemo(() => {
    if (!selectedOrgId) return null
    return organizations.find((org) => org.id === selectedOrgId) ?? null
  }, [organizations, selectedOrgId])

  const availableWorkspaces = useMemo(() => {
    if (!selectedOrgId) return []
    return workspacesByOrg[selectedOrgId] ?? []
  }, [selectedOrgId, workspacesByOrg])

  const selectedWorkspace = useMemo(() => {
    if (!selectedWorkspaceId) return null
    return availableWorkspaces.find((workspace) => workspace.id === selectedWorkspaceId) ?? null
  }, [availableWorkspaces, selectedWorkspaceId])

  const availableProjects = useMemo(() => {
    if (!selectedWorkspaceId) return []
    return projectsByWorkspace[selectedWorkspaceId] ?? []
  }, [selectedWorkspaceId, projectsByWorkspace])

  const selectedProject = useMemo(() => {
    if (!selectedProjectId) return null
    return availableProjects.find((project) => project.id === selectedProjectId) ?? null
  }, [availableProjects, selectedProjectId])

  async function loadProjectsForWorkspace(workspaceId: string, preferredProjectId?: string | null) {
    const projects = await listWorkspaceProjects(workspaceId)
    setProjectsByWorkspace((current) => ({ ...current, [workspaceId]: projects }))

    if (projects.length === 0) {
      clearSelectedProjectId()
      setSelectedProjectIdState(null)
      return
    }

    const storedProjectId = preferredProjectId ?? getSelectedProjectId()
    const nextProjectId =
      (storedProjectId && projects.some((project) => project.id === storedProjectId) && storedProjectId) ||
      projects[0].id

    persistSelectedProjectId(nextProjectId)
    setSelectedProjectIdState(nextProjectId)
  }

  async function loadWorkspacesForOrganization(organizationId: string, preferredWorkspaceId?: string | null) {
    const workspaces = await listOrganizationWorkspaces(organizationId)
    setWorkspacesByOrg((current) => ({ ...current, [organizationId]: workspaces }))

    if (workspaces.length === 0) {
      clearSelectedWorkspaceId()
      setSelectedWorkspaceIdState(null)
      clearSelectedProjectId()
      setSelectedProjectIdState(null)
      return
    }

    const storedWorkspaceId = preferredWorkspaceId ?? getSelectedWorkspaceId()
    const nextWorkspaceId =
      (storedWorkspaceId && workspaces.some((ws) => ws.id === storedWorkspaceId) && storedWorkspaceId) ||
      workspaces[0].id

    persistSelectedWorkspaceId(nextWorkspaceId)
    setSelectedWorkspaceIdState(nextWorkspaceId)
    await loadProjectsForWorkspace(nextWorkspaceId)
  }

  async function reloadOrganizations(preferredOrgId?: string | null) {
    const orgs = await listOrganizations()
    setOrganizations(orgs.map((org) => ({ ...org, role: (org.my_role ?? "MEMBER") as OrganizationRole | "MEMBER" })))

    if (orgs.length === 0) {
      setSelectedOrgIdState(null)
      clearSelectedWorkspaceId()
      setSelectedWorkspaceIdState(null)
      clearSelectedProjectId()
      setSelectedProjectIdState(null)
      return
    }

    const storedOrgId = getSelectedOrganizationId()
    const currentOrgId = selectedOrgId
    const nextOrgId =
      (preferredOrgId && orgs.some((org) => org.id === preferredOrgId) && preferredOrgId) ||
      (currentOrgId && orgs.some((org) => org.id === currentOrgId) && currentOrgId) ||
      (storedOrgId && orgs.some((org) => org.id === storedOrgId) && storedOrgId) ||
      orgs[0].id

    setSelectedOrganizationId(nextOrgId)
    setSelectedOrgIdState(nextOrgId)
    await loadWorkspacesForOrganization(nextOrgId)
  }

  async function createOrganizationAndSelect(payload: { name: string }) {
    const created = await createOrganization({ name: payload.name })
    await reloadOrganizations(created.id)
    return {
      ...created,
      role: "OWNER",
    } satisfies OrganizationWithRole
  }

  async function createWorkspaceAndSelect(payload: { organization_id: string; name: string; erp_id?: string | null }) {
    const created = await createWorkspace({
      organization_id: payload.organization_id,
      name: payload.name,
      erp_id: payload.erp_id ?? null,
    })
    await loadWorkspacesForOrganization(payload.organization_id, created.id)
    return created
  }

  async function createProjectAndSelect(payload: { workspace_id: string } & CreateProjectPayload) {
    const created = await createWorkspaceProject(payload.workspace_id, {
      name: payload.name,
      description: payload.description ?? null,
    })
    await loadProjectsForWorkspace(payload.workspace_id, created.id)
    return created
  }

  async function updateProjectAndRefresh(
    payload: { project_id: string; workspace_id: string } & CreateProjectPayload
  ) {
    const updated = await updateProject(payload.project_id, {
      name: payload.name,
      description: payload.description ?? null,
    })
    await loadProjectsForWorkspace(payload.workspace_id, updated.id)
    return updated
  }

  async function deleteProjectAndRefresh(payload: { project_id: string; workspace_id: string }) {
    await deleteProject(payload.project_id)
    await loadProjectsForWorkspace(payload.workspace_id)
  }

  useEffect(() => {
    async function init() {
      try {
        const session = await getValidSession()
        if (!session) {
          router.push("/login")
          return
        }

        const user = await fetchMe(session.accessToken)
        if (!user) {
          router.push("/login")
          return
        }
        await reloadOrganizations()
      } catch (err) {
        setError(err instanceof Error ? err.message : "Falha ao inicializar dashboard.")
      } finally {
        setIsLoading(false)
      }
    }

    init()
  }, [router])

  const setSelectedOrgId = (id: string) => {
    setSelectedOrganizationId(id)
    setSelectedOrgIdState(id)
    loadWorkspacesForOrganization(id)
  }

  const setSelectedWorkspaceId = (id: string) => {
    persistSelectedWorkspaceId(id)
    setSelectedWorkspaceIdState(id)
    loadProjectsForWorkspace(id)
  }

  const setSelectedProjectId = (id: string) => {
    persistSelectedProjectId(id)
    setSelectedProjectIdState(id)
  }

  return (
    <DashboardContext.Provider
      value={{
        organizations,
        workspacesByOrg,
        projectsByWorkspace,
        selectedOrgId,
        selectedWorkspaceId,
        selectedProjectId,
        isLoading,
        error,
        setSelectedOrgId,
        setSelectedWorkspaceId,
        setSelectedProjectId,
        selectedOrganization,
        availableWorkspaces,
        selectedWorkspace,
        availableProjects,
        selectedProject,
        loadWorkspacesForOrganization,
        loadProjectsForWorkspace,
        reloadOrganizations,
        createOrganizationAndSelect,
        createWorkspaceAndSelect,
        createProjectAndSelect,
        updateProjectAndRefresh,
        deleteProjectAndRefresh,
      }}
    >
      {children}
    </DashboardContext.Provider>
  )
}

export function useDashboard() {
  const context = useContext(DashboardContext)
  if (context === undefined) {
    throw new Error("useDashboard must be used within a DashboardProvider")
  }
  return context
}
