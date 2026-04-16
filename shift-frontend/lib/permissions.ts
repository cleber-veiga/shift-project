/**
 * Utilidades de verificacao de permissao no frontend.
 *
 * Hierarchy (higher index = more power):
 *   Workspace: VIEWER < CONSULTANT < MANAGER
 *   Organization: GUEST < MEMBER < MANAGER < OWNER
 */

const WS_RANK: Record<string, number> = {
  VIEWER: 1,
  CONSULTANT: 2,
  MANAGER: 3,
}

const ORG_RANK: Record<string, number> = {
  GUEST: 1,
  MEMBER: 2,
  MANAGER: 3,
  OWNER: 4,
}

export type WorkspaceRole = "VIEWER" | "CONSULTANT" | "MANAGER"
export type OrgRole = "GUEST" | "MEMBER" | "MANAGER" | "OWNER"

/**
 * Returns true if the user's workspace role meets or exceeds the required role.
 */
export function hasWorkspacePermission(
  userRole: string | null | undefined,
  requiredRole: WorkspaceRole,
): boolean {
  if (!userRole) return false
  return (WS_RANK[userRole] ?? 0) >= (WS_RANK[requiredRole] ?? 999)
}

/**
 * Returns true if the user's org role meets or exceeds the required role.
 */
export function hasOrgPermission(
  userRole: string | null | undefined,
  requiredRole: OrgRole,
): boolean {
  if (!userRole) return false
  return (ORG_RANK[userRole] ?? 0) >= (ORG_RANK[requiredRole] ?? 999)
}
