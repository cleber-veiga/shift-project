// ─── Tipos de domínio ──────────────────────────────────────────────────────────

export type User = {
  id: string
  email: string
  full_name: string | null
  is_active: boolean
  is_verified: boolean
  auth_provider: string
  created_at: string
  updated_at: string
  last_login_at: string | null
}

export type OrganizationRole = "OWNER" | "MANAGER" | "MEMBER" | "GUEST"

export type Organization = {
  id: string
  name: string
  billing_email?: string | null
  created_at: string
  my_role?: string | null
}

export type ERP = {
  id: string
  name: string
  slug: string
  code: string
  created_at: string
  updated_at: string
}

export type OrganizationMembership = {
  user_id: string
  email: string
  is_active: boolean
  role: string
  created_at: string
}

export type TokenResponse = {
  access_token: string
  refresh_token: string
  token_type: "bearer"
  access_token_expires_at: number
  refresh_token_expires_at: number
  user: User
}

export type LoginPayload = {
  email: string
  password: string
}

export type RegisterPayload = {
  email: string
  password: string
  full_name?: string
}

export type CreateOrganizationPayload = {
  name: string
}

export type CreateWorkspacePayload = {
  name: string
  organization_id: string
  erp_id?: string | null
}

export type UpdateWorkspacePayload = {
  name?: string
}

export type WorkspacePlayerDatabaseType =
  | "POSTGRESQL"
  | "MYSQL"
  | "SQLSERVER"
  | "ORACLE"
  | "FIREBIRD"
  | "SQLITE"
  | "SNOWFLAKE"

export type WorkspacePlayer = {
  id: string
  workspace_id: string
  name: string
  database_type: WorkspacePlayerDatabaseType
}

export type CreateWorkspacePlayerPayload = {
  name: string
  database_type: WorkspacePlayerDatabaseType
}

export type UpdateWorkspacePlayerPayload = {
  name?: string
  database_type?: WorkspacePlayerDatabaseType
}

export type Workspace = {
  id: string
  name: string
  organization_id: string
  erp_id?: string | null
  created_by_id?: string
  created_at: string
  my_role?: string | null
}

export type Project = {
  id: string
  workspace_id: string
  conglomerate_id?: string
  player_id?: string | null
  created_by_id?: string
  name: string
  description: string | null
  start_date?: string
  end_date?: string
  created_at: string
  updated_at?: string
}

export type CreateProjectPayload = {
  name: string
  description?: string | null
  player_id?: string | null
  conglomerate_id?: string | null
  start_date?: string | null
  end_date?: string | null
}

export type UpdateProjectPayload = Partial<CreateProjectPayload>

export type Conglomerate = {
  id: string
  organization_id: string
  name: string
  description: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export type EconomicGroup = Conglomerate

export type CreateEconomicGroupPayload = {
  name: string
  description?: string | null
  is_active?: boolean
}

export type UpdateEconomicGroupPayload = Partial<CreateEconomicGroupPayload>

export type Establishment = {
  id: string
  economic_group_id: string
  corporate_name: string
  trade_name: string | null
  cnpj: string
  erp_code: number | null
  cnae: string
  state_registration: string | null
  cep: string | null
  city: string | null
  state: string | null
  notes: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export type CreateEstablishmentPayload = {
  corporate_name: string
  trade_name?: string | null
  cnpj: string
  erp_code?: number | null
  cnae: string
  state_registration?: string | null
  cep?: string | null
  city?: string | null
  state?: string | null
  notes?: string | null
  is_active?: boolean
}

export type UpdateEstablishmentPayload = Partial<CreateEstablishmentPayload>

// ─── Input Models ─────────────────────────────────────────────────────────────

export type InputModelColumnType = "text" | "number" | "integer" | "date" | "datetime" | "boolean"
export type InputModelFileType = "excel" | "csv" | "data"

export type InputModelColumn = {
  name: string
  type: InputModelColumnType
  required: boolean
}

export type InputModelSheet = {
  name: string
  columns: InputModelColumn[]
}

export type InputModelSchema = {
  sheets: InputModelSheet[]
}

export type InputModel = {
  id: string
  workspace_id: string
  name: string
  description: string | null
  file_type: InputModelFileType
  schema_def: InputModelSchema
  created_by_id: string | null
  created_at: string
  updated_at: string
}

export type CreateInputModelPayload = {
  name: string
  description?: string | null
  file_type: InputModelFileType
  schema_def: InputModelSchema
}

export type UpdateInputModelPayload = {
  name?: string
  description?: string | null
  file_type?: InputModelFileType
  schema_def?: InputModelSchema
}

export type InputModelValidationResult = {
  valid: boolean
  errors: string[]
}

export type InputModelRow = {
  id: string
  input_model_id: string
  row_order: number
  data: Record<string, unknown>
  created_at: string
}

export type InputModelRowsResponse = {
  total: number
  rows: InputModelRow[]
}

// ─── Invitations ──────────────────────────────────────────────────────────────

export type InvitationStatus = "PENDING" | "ACCEPTED" | "CANCELLED" | "EXPIRED"

export type Invitation = {
  id: string
  email: string
  scope: string
  role: string
  status: InvitationStatus
  invited_by_name: string | null
  invited_by_email: string
  expires_at: string
  created_at: string
}

export type InvitationDetail = {
  id: string
  email: string
  scope: string
  scope_name: string
  role: string
  invited_by_name: string | null
  is_expired: boolean
  is_accepted: boolean
}

export type AcceptInvitationResult = {
  success: boolean
  message: string
  scope: string
  scope_id: string
}

export type Member = {
  user_id: string
  email: string
  full_name?: string | null
  is_active: boolean
  role: string
  created_at: string
}

export type ConnectionType = "oracle" | "postgresql" | "firebird" | "sqlserver" | "mysql"

export type Connection = {
  id: string
  workspace_id: string | null
  project_id: string | null
  player_id: string | null
  name: string
  type: ConnectionType
  host: string
  port: number
  database: string
  username: string
  extra_params: Record<string, unknown> | null
  include_schemas: string[] | null
  is_public: boolean
  created_by_id: string | null
  created_at: string
  updated_at: string
}

export type CreateConnectionPayload = {
  name: string
  workspace_id?: string | null
  project_id?: string | null
  /** UUID do sistema. Quando informado, 'database' é resolvido automaticamente. */
  player_id?: string | null
  type: ConnectionType
  host: string
  port: number
  /** Obrigatório apenas quando player_id não for informado. */
  database?: string | null
  username: string
  password: string
  extra_params?: Record<string, unknown> | null
  include_schemas?: string[] | null
  is_public?: boolean
}

export type UpdateConnectionPayload = {
  name?: string
  player_id?: string | null
  host?: string
  port?: number
  database?: string
  username?: string
  password?: string
  extra_params?: Record<string, unknown> | null
  include_schemas?: string[] | null
  is_public?: boolean
}

export type TestConnectionResult = {
  success: boolean
  message: string
}

// ─── Sessão local ──────────────────────────────────────────────────────────────

const SESSION_STORAGE_KEY = "shift.auth.session"
const SELECTED_ORGANIZATION_STORAGE_KEY = "shift.selected.organization_id"
const SELECTED_WORKSPACE_STORAGE_KEY = "shift.selected.workspace_id"
const SELECTED_PROJECT_STORAGE_KEY = "shift.selected.project_id"

export type AuthSession = {
  accessToken: string
  refreshToken: string
  accessTokenExpiresAt: number
  refreshTokenExpiresAt: number
  user: User
}

function getApiBaseUrl() {
  const value = process.env.NEXT_PUBLIC_API_BASE_URL
  return value && value.trim().length > 0 ? value.trim() : "http://localhost:8000/api/v1"
}

function isBrowser() {
  return typeof window !== "undefined"
}

function toSession(response: TokenResponse): AuthSession {
  return {
    accessToken: response.access_token,
    refreshToken: response.refresh_token,
    accessTokenExpiresAt: response.access_token_expires_at,
    refreshTokenExpiresAt: response.refresh_token_expires_at,
    user: response.user,
  }
}

export function getStoredSession(): AuthSession | null {
  if (!isBrowser()) return null
  const raw = window.localStorage.getItem(SESSION_STORAGE_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as AuthSession
  } catch {
    window.localStorage.removeItem(SESSION_STORAGE_KEY)
    return null
  }
}

export function storeSession(session: AuthSession) {
  if (!isBrowser()) return
  window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session))
}

export function clearSession() {
  if (!isBrowser()) return
  window.localStorage.removeItem(SESSION_STORAGE_KEY)
}

export function setSelectedOrganizationId(organizationId: string) {
  if (!isBrowser()) return
  window.localStorage.setItem(SELECTED_ORGANIZATION_STORAGE_KEY, organizationId)
}

export function getSelectedOrganizationId(): string | null {
  if (!isBrowser()) return null
  return window.localStorage.getItem(SELECTED_ORGANIZATION_STORAGE_KEY)
}

export function clearSelectedOrganizationId() {
  if (!isBrowser()) return
  window.localStorage.removeItem(SELECTED_ORGANIZATION_STORAGE_KEY)
}

export function setSelectedWorkspaceId(workspaceId: string) {
  if (!isBrowser()) return
  window.localStorage.setItem(SELECTED_WORKSPACE_STORAGE_KEY, workspaceId)
}

export function getSelectedWorkspaceId(): string | null {
  if (!isBrowser()) return null
  return window.localStorage.getItem(SELECTED_WORKSPACE_STORAGE_KEY)
}

export function clearSelectedWorkspaceId() {
  if (!isBrowser()) return
  window.localStorage.removeItem(SELECTED_WORKSPACE_STORAGE_KEY)
}

export function setSelectedProjectId(projectId: string) {
  if (!isBrowser()) return
  window.localStorage.setItem(SELECTED_PROJECT_STORAGE_KEY, projectId)
}

export function getSelectedProjectId(): string | null {
  if (!isBrowser()) return null
  return window.localStorage.getItem(SELECTED_PROJECT_STORAGE_KEY)
}

export function clearSelectedProjectId() {
  if (!isBrowser()) return
  window.localStorage.removeItem(SELECTED_PROJECT_STORAGE_KEY)
}

function isAccessTokenExpired(session: AuthSession) {
  const now = Math.floor(Date.now() / 1000)
  return session.accessTokenExpiresAt <= now + 10
}

// ─── HTTP helpers ──────────────────────────────────────────────────────────────

async function parseApiError(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as {
      detail?:
        | string
        | Array<{
            loc?: Array<string | number>
            msg?: string
          }>
    }
    if (typeof data.detail === "string" && data.detail.trim().length > 0) {
      return data.detail
    }
    if (Array.isArray(data.detail) && data.detail.length > 0) {
      const first = data.detail[0]
      const msg = typeof first?.msg === "string" ? first.msg.trim() : ""
      const loc =
        Array.isArray(first?.loc) && first.loc.length > 0
          ? first.loc.map((item) => String(item)).join(".")
          : ""
      if (msg && loc) return `${loc}: ${msg}`
      if (msg) return msg
    }
  } catch {
    // ignore
  }
  return `Erro na requisição (${response.status}).`
}

async function parseResponseBody<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T
  const raw = await response.text()
  if (!raw) return undefined as T
  return JSON.parse(raw) as T
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  })
  if (!response.ok) throw new Error(await parseApiError(response))
  return parseResponseBody<T>(response)
}

function dispatchSessionExpired() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("auth:session-expired"))
  }
}

async function authorizedRequest<T>(path: string, init: RequestInit): Promise<T> {
  const session = await getValidSession()
  if (!session) {
    dispatchSessionExpired()
    throw new Error("Sua sessão expirou. Faça login novamente.")
  }

  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${session.accessToken}`,
      ...(init.headers ?? {}),
    },
  })

  if (response.status === 401) {
    clearSession()
    dispatchSessionExpired()
    throw new Error("Sua sessão expirou. Faça login novamente.")
  }

  if (!response.ok) throw new Error(await parseApiError(response))
  return parseResponseBody<T>(response)
}

// ─── Autenticação ──────────────────────────────────────────────────────────────

export async function login(payload: LoginPayload): Promise<AuthSession> {
  const data = await request<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email: payload.email, password: payload.password }),
  })
  const session = toSession(data)
  storeSession(session)
  return session
}

export async function register(payload: RegisterPayload): Promise<AuthSession> {
  const data = await request<TokenResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({
      email: payload.email,
      password: payload.password,
      full_name: payload.full_name ?? null,
    }),
  })
  const session = toSession(data)
  storeSession(session)
  return session
}

export async function refreshSession(refreshToken: string): Promise<AuthSession> {
  const data = await request<TokenResponse>("/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
  const session = toSession(data)
  storeSession(session)
  return session
}

export async function fetchMe(accessToken: string): Promise<User> {
  const response = await fetch(`${getApiBaseUrl()}/auth/me`, {
    method: "GET",
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  if (!response.ok) throw new Error(await parseApiError(response))
  return (await response.json()) as User
}

export async function getValidSession(): Promise<AuthSession | null> {
  const session = getStoredSession()
  if (!session) return null

  if (!isAccessTokenExpired(session)) return session

  const now = Math.floor(Date.now() / 1000)
  if (session.refreshTokenExpiresAt <= now) {
    clearSession()
    return null
  }

  try {
    return await refreshSession(session.refreshToken)
  } catch {
    clearSession()
    return null
  }
}

export async function logout() {
  const session = getStoredSession()
  if (session) {
    try {
      await request<{ detail: string }>("/auth/logout", {
        method: "POST",
        body: JSON.stringify({ refresh_token: session.refreshToken }),
      })
    } catch {
      // best effort
    }
  }
  clearSession()
  clearSelectedOrganizationId()
  clearSelectedWorkspaceId()
  clearSelectedProjectId()
}

// ─── Reset de senha ────────────────────────────────────────────────────────────

export async function forgotPassword(email: string): Promise<{ message: string }> {
  return request<{ message: string }>("/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email }),
  })
}

export async function verifyResetCode(
  email: string,
  code: string
): Promise<{ valid: boolean }> {
  return request<{ valid: boolean }>("/auth/verify-reset-code", {
    method: "POST",
    body: JSON.stringify({ email, code }),
  })
}

export async function resetPassword(
  email: string,
  code: string,
  new_password: string
): Promise<{ message: string }> {
  return request<{ message: string }>("/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ email, code, new_password }),
  })
}

// ─── Organizações ──────────────────────────────────────────────────────────────

export async function listOrganizations(): Promise<Organization[]> {
  return authorizedRequest<Organization[]>("/organizations", { method: "GET" })
}

export async function createOrganization(
  payload: CreateOrganizationPayload
): Promise<Organization> {
  return authorizedRequest<Organization>("/organizations", {
    method: "POST",
    body: JSON.stringify({ name: payload.name }),
  })
}

export async function listOrganizationMembers(
  organizationId: string
): Promise<OrganizationMembership[]> {
  return authorizedRequest<OrganizationMembership[]>(
    `/organizations/${organizationId}/members`,
    { method: "GET" }
  )
}

// ─── Workspaces ────────────────────────────────────────────────────────────────

export async function listOrganizationWorkspaces(
  organizationId: string
): Promise<Workspace[]> {
  return authorizedRequest<Workspace[]>(
    `/workspaces/organization/${organizationId}`,
    { method: "GET" }
  )
}

export async function createWorkspace(payload: CreateWorkspacePayload): Promise<Workspace> {
  return authorizedRequest<Workspace>("/workspaces", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export async function updateWorkspace(
  workspaceId: string,
  payload: UpdateWorkspacePayload
): Promise<Workspace> {
  return authorizedRequest<Workspace>(`/workspaces/${workspaceId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  })
}

// ─── ERPs ──────────────────────────────────────────────────────────────────────

export async function listErps(params?: { q?: string }): Promise<ERP[]> {
  const query = new URLSearchParams()
  if (params?.q) query.append("q", params.q)
  const qs = query.toString()
  return authorizedRequest<ERP[]>(`/erps${qs ? `?${qs}` : ""}`, { method: "GET" })
}

// ─── Workspace Players (Sistemas) ─────────────────────────────────────────────

export async function listWorkspacePlayers(
  workspaceId: string
): Promise<WorkspacePlayer[]> {
  return authorizedRequest<WorkspacePlayer[]>(`/workspaces/${workspaceId}/players`, {
    method: "GET",
  })
}

export async function createWorkspacePlayer(
  workspaceId: string,
  payload: CreateWorkspacePlayerPayload
): Promise<WorkspacePlayer> {
  return authorizedRequest<WorkspacePlayer>(`/workspaces/${workspaceId}/players`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export async function updateWorkspacePlayer(
  workspaceId: string,
  playerId: string,
  payload: UpdateWorkspacePlayerPayload
): Promise<WorkspacePlayer> {
  return authorizedRequest<WorkspacePlayer>(
    `/workspaces/${workspaceId}/players/${playerId}`,
    { method: "PUT", body: JSON.stringify(payload) }
  )
}

export async function deleteWorkspacePlayer(
  workspaceId: string,
  playerId: string
): Promise<void> {
  return authorizedRequest<void>(`/workspaces/${workspaceId}/players/${playerId}`, {
    method: "DELETE",
  })
}

// ─── Projetos ──────────────────────────────────────────────────────────────────

export async function listWorkspaceProjects(
  workspaceId: string
): Promise<Project[]> {
  return authorizedRequest<Project[]>(`/workspaces/${workspaceId}/projects`, {
    method: "GET",
  })
}

export async function createWorkspaceProject(
  workspaceId: string,
  payload: CreateProjectPayload
): Promise<Project> {
  return authorizedRequest<Project>(`/workspaces/${workspaceId}/projects`, {
    method: "POST",
    body: JSON.stringify({ name: payload.name, description: payload.description ?? null }),
  })
}

export async function updateProject(
  projectId: string,
  payload: UpdateProjectPayload
): Promise<Project> {
  return authorizedRequest<Project>(`/projects/${projectId}`, {
    method: "PUT",
    body: JSON.stringify({ name: payload.name, description: payload.description ?? null }),
  })
}

// ─── Grupos Econômicos ────────────────────────────────────────────────────────

export async function listOrganizationConglomerates(
  organizationId: string
): Promise<Conglomerate[]> {
  return authorizedRequest<Conglomerate[]>(
    `/organizations/${organizationId}/economic-groups`,
    { method: "GET" }
  )
}

export async function createEconomicGroup(
  organizationId: string,
  payload: CreateEconomicGroupPayload
): Promise<EconomicGroup> {
  return authorizedRequest<EconomicGroup>(
    `/organizations/${organizationId}/economic-groups`,
    { method: "POST", body: JSON.stringify(payload) }
  )
}

export async function getEconomicGroup(groupId: string): Promise<EconomicGroup> {
  return authorizedRequest<EconomicGroup>(`/economic-groups/${groupId}`, { method: "GET" })
}

export async function updateEconomicGroup(
  groupId: string,
  payload: UpdateEconomicGroupPayload
): Promise<EconomicGroup> {
  return authorizedRequest<EconomicGroup>(`/economic-groups/${groupId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  })
}

export async function deleteEconomicGroup(groupId: string): Promise<void> {
  return authorizedRequest<void>(`/economic-groups/${groupId}`, { method: "DELETE" })
}

export async function listEstablishments(groupId: string): Promise<Establishment[]> {
  return authorizedRequest<Establishment[]>(
    `/economic-groups/${groupId}/establishments`,
    { method: "GET" }
  )
}

export async function createEstablishment(
  groupId: string,
  payload: CreateEstablishmentPayload
): Promise<Establishment> {
  return authorizedRequest<Establishment>(
    `/economic-groups/${groupId}/establishments`,
    { method: "POST", body: JSON.stringify(payload) }
  )
}

export async function updateEstablishment(
  establishmentId: string,
  payload: UpdateEstablishmentPayload
): Promise<Establishment> {
  return authorizedRequest<Establishment>(`/establishments/${establishmentId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  })
}

export async function deleteEstablishment(establishmentId: string): Promise<void> {
  return authorizedRequest<void>(`/establishments/${establishmentId}`, { method: "DELETE" })
}

// ─── Lookups (CNPJ / CEP) ────────────────────────────────────────────────────

export type CNPJLookup = {
  cnpj: string
  razao_social: string
  nome_fantasia: string | null
  cnae_fiscal: string | null
  cnae_fiscal_descricao: string | null
  logradouro: string | null
  numero: string | null
  complemento: string | null
  bairro: string | null
  cep: string | null
  municipio: string | null
  uf: string | null
  situacao_cadastral: string | null
  inscricao_estadual: string | null
}

export type CEPLookup = {
  cep: string
  logradouro: string | null
  complemento: string | null
  bairro: string | null
  localidade: string | null
  uf: string | null
  estado: string | null
}

export async function lookupCnpj(cnpj: string): Promise<CNPJLookup> {
  return authorizedRequest<CNPJLookup>(`/lookups/cnpj/${cnpj.replace(/\D/g, "")}`, { method: "GET" })
}

export async function lookupCep(cep: string): Promise<CEPLookup> {
  return authorizedRequest<CEPLookup>(`/lookups/cep/${cep.replace(/\D/g, "")}`, { method: "GET" })
}

// ─── Conexões ─────────────────────────────────────────────────────────────────

export async function listWorkspaceConnections(
  workspaceId: string
): Promise<Connection[]> {
  return authorizedRequest<Connection[]>(
    `/connections?workspace_id=${workspaceId}`,
    { method: "GET" }
  )
}

export async function listProjectConnections(
  projectId: string
): Promise<Connection[]> {
  return authorizedRequest<Connection[]>(
    `/projects/${projectId}/connections`,
    { method: "GET" }
  )
}

export async function createConnection(
  payload: CreateConnectionPayload
): Promise<Connection> {
  return authorizedRequest<Connection>("/connections", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export async function updateConnection(
  connectionId: string,
  payload: UpdateConnectionPayload
): Promise<Connection> {
  return authorizedRequest<Connection>(`/connections/${connectionId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  })
}

export async function deleteConnection(connectionId: string): Promise<void> {
  return authorizedRequest<void>(`/connections/${connectionId}`, {
    method: "DELETE",
  })
}

export async function testConnection(
  connectionId: string
): Promise<TestConnectionResult> {
  return authorizedRequest<TestConnectionResult>(
    `/connections/${connectionId}/test`,
    { method: "POST" }
  )
}

export async function getConnection(connectionId: string): Promise<Connection> {
  return authorizedRequest<Connection>(`/connections/${connectionId}`, {
    method: "GET",
  })
}

// ─── Playground ─────────────────────────────────────────────────────────────

export type SchemaColumn = {
  name: string
  type: string
  nullable: boolean
}

export type SchemaTable = {
  name: string
  schema: string | null
  columns: SchemaColumn[]
}

export type SchemaResponse = {
  tables: SchemaTable[]
  updated_at: string | null
  is_cached: boolean
}

export type PlaygroundQueryResponse = {
  columns: string[]
  rows: unknown[][]
  row_count: number
  truncated: boolean
  execution_time_ms: number
}

const _schemaCache = new Map<string, { data: SchemaResponse; ts: number }>()
const _SCHEMA_CACHE_TTL = 5 * 60 * 1000 // 5 minutos

export async function getConnectionSchema(
  connectionId: string,
  force = false
): Promise<SchemaResponse> {
  const cacheKey = connectionId
  if (!force) {
    const cached = _schemaCache.get(cacheKey)
    if (cached && Date.now() - cached.ts < _SCHEMA_CACHE_TTL) {
      return cached.data
    }
  }
  const url = force
    ? `/connections/${connectionId}/schema?force=true`
    : `/connections/${connectionId}/schema`
  const result = await authorizedRequest<SchemaResponse>(url, { method: "GET" })
  _schemaCache.set(cacheKey, { data: result, ts: Date.now() })
  return result
}

export async function executePlaygroundQuery(
  connectionId: string,
  query: string,
  maxRows: number = 500
): Promise<PlaygroundQueryResponse> {
  return authorizedRequest<PlaygroundQueryResponse>(
    `/connections/${connectionId}/query`,
    {
      method: "POST",
      body: JSON.stringify({ query, max_rows: maxRows }),
    }
  )
}

// ─── Saved Queries ──────────────────────────────────────────────────────────

export type SavedQuery = {
  id: string
  workspace_id: string
  player_id: string
  database_type: string
  name: string
  description: string | null
  query: string
  created_by_id: string | null
  created_at: string
  updated_at: string
}

export async function listSavedQueries(connectionId: string): Promise<SavedQuery[]> {
  return authorizedRequest<SavedQuery[]>(
    `/connections/${connectionId}/saved-queries`,
    { method: "GET" }
  )
}

export async function createSavedQuery(
  connectionId: string,
  payload: { name: string; description?: string; query: string }
): Promise<SavedQuery> {
  return authorizedRequest<SavedQuery>(
    `/connections/${connectionId}/saved-queries`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  )
}

export async function updateSavedQuery(
  queryId: string,
  payload: { name?: string; description?: string; query?: string }
): Promise<SavedQuery> {
  return authorizedRequest<SavedQuery>(
    `/saved-queries/${queryId}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    }
  )
}

export async function deleteSavedQuery(queryId: string): Promise<void> {
  await authorizedRequest<void>(
    `/saved-queries/${queryId}`,
    { method: "DELETE" }
  )
}

// ─── AI Chat (SQL Assistant) ───────────────────────────────────────────────

export type AiChatMessage = { role: "user" | "assistant"; content: string }

export interface AiChatCallbacks {
  onDelta: (text: string) => void
  onToolCall?: (name: string, args: Record<string, unknown>) => void
  onToolResult?: (name: string, preview: string) => void
  onError?: (message: string) => void
  onDone?: () => void
}

/**
 * Envia mensagens para o assistente SQL e processa o stream SSE de resposta.
 * Usa fetch direto (nao authorizedRequest) para poder ler o ReadableStream.
 */
export async function streamAiChat(
  connectionId: string,
  messages: AiChatMessage[],
  callbacks: AiChatCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const session = await getValidSession()
  if (!session) {
    callbacks.onError?.("Sessao expirada. Faca login novamente.")
    return
  }

  const response = await fetch(
    `${getApiBaseUrl()}/connections/${connectionId}/chat`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session.accessToken}`,
      },
      body: JSON.stringify({ messages }),
      signal,
    },
  )

  if (!response.ok) {
    let detail = "Erro ao conectar com o assistente."
    try {
      const err = await response.json()
      if (err.detail) detail = err.detail
    } catch { /* ignora */ }
    callbacks.onError?.(detail)
    return
  }

  const reader = response.body?.getReader()
  if (!reader) {
    callbacks.onError?.("Stream nao disponivel.")
    return
  }

  const decoder = new TextDecoder()
  let buffer = ""

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // Parsear eventos SSE (separados por \n\n)
      const parts = buffer.split("\n\n")
      buffer = parts.pop() ?? ""

      for (const part of parts) {
        if (!part.trim()) continue

        let eventType = "delta"
        let eventData = ""

        for (const line of part.split("\n")) {
          if (line.startsWith("event: ")) {
            eventType = line.slice(7).trim()
          } else if (line.startsWith("data: ")) {
            eventData = line.slice(6)
          }
        }

        if (!eventData) continue

        try {
          const parsed = JSON.parse(eventData)

          switch (eventType) {
            case "delta":
              callbacks.onDelta(parsed.text ?? "")
              break
            case "tool_call":
              callbacks.onToolCall?.(parsed.name, parsed.args ?? {})
              break
            case "tool_result":
              callbacks.onToolResult?.(parsed.name, parsed.preview ?? "")
              break
            case "error":
              callbacks.onError?.(parsed.message ?? "Erro desconhecido.")
              break
            case "done":
              callbacks.onDone?.()
              return
          }
        } catch {
          // Chunk JSON malformado — ignora
        }
      }
    }

    // Stream terminou sem evento done
    callbacks.onDone?.()
  } finally {
    reader.releaseLock()
  }
}

// ─── Workflows ────────────────────────────────────────────────────────────────

export type Workflow = {
  id: string
  name: string
  description: string | null
  project_id: string | null
  workspace_id: string | null
  is_template: boolean
  is_published: boolean
  status: "draft" | "published"
  definition: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type CreateWorkflowPayload = {
  name: string
  description?: string | null
  project_id?: string | null
  workspace_id?: string | null
  is_template?: boolean
  definition?: Record<string, unknown>
}

export type UpdateWorkflowPayload = {
  name?: string
  description?: string | null
  definition?: Record<string, unknown>
  is_template?: boolean
  is_published?: boolean
  status?: "draft" | "published"
}

export type ExecutionResponse = {
  execution_id: string
  status: string
}

export type ExecutionStatusResponse = {
  execution_id: string
  status: string
  result: Record<string, unknown> | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
}

export async function createWorkflow(
  payload: CreateWorkflowPayload
): Promise<Workflow> {
  // O sistema de autorização do backend resolve workspace_id apenas via
  // path params ou query params — não via body. Por isso passamos também na URL.
  const scopeParam = payload.workspace_id
    ? `?workspace_id=${payload.workspace_id}`
    : payload.project_id
    ? `?project_id=${payload.project_id}`
    : ""
  return authorizedRequest<Workflow>(`/workflows${scopeParam}`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export async function listProjectWorkflows(
  projectId: string
): Promise<Workflow[]> {
  return authorizedRequest<Workflow[]>(
    `/projects/${projectId}/workflows`,
    { method: "GET" }
  )
}

export async function listWorkspaceWorkflows(
  workspaceId: string
): Promise<Workflow[]> {
  return authorizedRequest<Workflow[]>(
    `/workspaces/${workspaceId}/workflows`,
    { method: "GET" }
  )
}

export async function listWorkspaceTemplates(
  workspaceId: string
): Promise<Workflow[]> {
  return authorizedRequest<Workflow[]>(
    `/workspaces/${workspaceId}/templates`,
    { method: "GET" }
  )
}

export async function getWorkflow(workflowId: string): Promise<Workflow> {
  return authorizedRequest<Workflow>(`/workflows/${workflowId}`, {
    method: "GET",
  })
}

export async function updateWorkflow(
  workflowId: string,
  payload: UpdateWorkflowPayload
): Promise<Workflow> {
  return authorizedRequest<Workflow>(`/workflows/${workflowId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  })
}

export async function deleteWorkflow(workflowId: string): Promise<void> {
  return authorizedRequest<void>(`/workflows/${workflowId}`, {
    method: "DELETE",
  })
}

export async function executeWorkflow(
  workflowId: string,
  payload?: Record<string, unknown>
): Promise<ExecutionResponse> {
  return authorizedRequest<ExecutionResponse>(
    `/workflows/${workflowId}/execute`,
    {
      method: "POST",
      body: JSON.stringify(payload ?? {}),
    }
  )
}

// ─── Workflow Schedule (Cron) ────────────────────────────────────────────

export type WorkflowScheduleStatus = {
  workflow_id: string
  is_active: boolean
  is_published: boolean
  has_cron_node: boolean
  cron_expression: string | null
  timezone: string | null
}

export async function getWorkflowSchedule(
  workflowId: string,
): Promise<WorkflowScheduleStatus> {
  return authorizedRequest<WorkflowScheduleStatus>(
    `/workflows/${workflowId}/schedule`,
    { method: "GET" },
  )
}

export async function getExecutionStatus(
  executionId: string
): Promise<ExecutionStatusResponse> {
  return authorizedRequest<ExecutionStatusResponse>(
    `/workflows/executions/${executionId}/status`,
    { method: "GET" }
  )
}

// ─── Teste de workflow com SSE ─────────────────────────────────────────────────

export type WorkflowTestEvent =
  | { type: "execution_start"; execution_id: string; node_count: number; timestamp: string }
  | { type: "node_start"; node_id: string; node_type: string; label: string; timestamp: string }
  | { type: "node_complete"; node_id: string; label: string; output: Record<string, unknown>; duration_ms: number; is_pinned?: boolean; timestamp: string }
  | { type: "node_error"; node_id: string; label: string; error: string; duration_ms: number; timestamp: string }
  | { type: "execution_complete"; execution_id: string; status: "SUCCESS" | "FAILED"; duration_ms: number; timestamp: string }
  | { type: "error"; error: string }

export type WorkflowTestCallbacks = {
  onEvent: (event: WorkflowTestEvent) => void
  onError?: (message: string) => void
  onDone?: () => void
}

/**
 * Executa um workflow em modo de teste via SSE.
 * Usa fetch com Authorization header (EventSource nativo nao suporta headers).
 */
export async function testWorkflowStream(
  workflowId: string,
  workspaceId: string | undefined,
  callbacks: WorkflowTestCallbacks,
  signal?: AbortSignal,
  targetNodeId?: string,
): Promise<void> {
  const session = await getValidSession()
  if (!session) {
    callbacks.onError?.("Sessao expirada. Faca login novamente.")
    return
  }

  const params = new URLSearchParams()
  if (workspaceId) params.set("workspace_id", workspaceId)
  if (targetNodeId) params.set("target_node_id", targetNodeId)
  const qs = params.toString() ? `?${params.toString()}` : ""
  const response = await fetch(
    `${getApiBaseUrl()}/workflows/${workflowId}/test${qs}`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${session.accessToken}`,
        Accept: "text/event-stream",
      },
      signal,
    },
  ).catch(() => null)

  if (!response) {
    callbacks.onError?.("Falha ao conectar com o servidor.")
    callbacks.onDone?.()
    return
  }

  if (!response.ok) {
    let detail = "Erro ao iniciar execucao."
    try {
      const err = await response.json()
      if (err.detail) detail = String(err.detail)
    } catch { /* ignora */ }
    callbacks.onError?.(detail)
    callbacks.onDone?.()
    return
  }

  const reader = response.body?.getReader()
  if (!reader) {
    callbacks.onError?.("Stream nao disponivel.")
    callbacks.onDone?.()
    return
  }

  const decoder = new TextDecoder()
  let buffer = ""

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // Eventos SSE sao separados por \n\n
      const parts = buffer.split("\n\n")
      buffer = parts.pop() ?? ""

      for (const part of parts) {
        if (!part.trim()) continue
        for (const line of part.split("\n")) {
          if (line.startsWith("data: ")) {
            try {
              const event = JSON.parse(line.slice(6)) as WorkflowTestEvent
              callbacks.onEvent(event)
            } catch { /* linha malformada, ignora */ }
          }
        }
      }
    }
  } catch (err) {
    if (err instanceof Error && err.name !== "AbortError") {
      callbacks.onError?.("Conexao interrompida inesperadamente.")
    }
  } finally {
    reader.releaseLock()
    callbacks.onDone?.()
  }
}

// ─── Input Models API ─────────────────────────────────────────────────────────

export async function listWorkspaceInputModels(workspaceId: string): Promise<InputModel[]> {
  return authorizedRequest<InputModel[]>(`/workspaces/${workspaceId}/input-models`, { method: "GET" })
}

export async function createInputModel(workspaceId: string, payload: CreateInputModelPayload): Promise<InputModel> {
  return authorizedRequest<InputModel>(`/workspaces/${workspaceId}/input-models`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export async function getInputModel(inputModelId: string): Promise<InputModel> {
  return authorizedRequest<InputModel>(`/input-models/${inputModelId}`, { method: "GET" })
}

export async function updateInputModel(inputModelId: string, payload: UpdateInputModelPayload): Promise<InputModel> {
  return authorizedRequest<InputModel>(`/input-models/${inputModelId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  })
}

export async function deleteInputModel(inputModelId: string): Promise<void> {
  return authorizedRequest<void>(`/input-models/${inputModelId}`, { method: "DELETE" })
}

export async function downloadInputModelTemplate(inputModelId: string): Promise<void> {
  const session = getStoredSession()
  if (!session) throw new Error("Sessao expirada.")
  const res = await fetch(`${getApiBaseUrl()}/input-models/${inputModelId}/template`, {
    headers: { Authorization: `Bearer ${session.accessToken}` },
  })
  if (!res.ok) throw new Error("Erro ao baixar template.")
  const blob = await res.blob()
  const disposition = res.headers.get("Content-Disposition") ?? ""
  const match = disposition.match(/filename="?(.+?)"?$/)
  const filename = match?.[1] ?? "template"
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export async function validateInputModelFile(
  inputModelId: string,
  file: File,
): Promise<InputModelValidationResult> {
  const session = getStoredSession()
  if (!session) throw new Error("Sessao expirada.")
  const form = new FormData()
  form.append("file", file)
  const res = await fetch(`${getApiBaseUrl()}/input-models/${inputModelId}/validate`, {
    method: "POST",
    headers: { Authorization: `Bearer ${session.accessToken}` },
    body: form,
  })
  if (!res.ok) throw new Error("Erro ao validar arquivo.")
  return res.json() as Promise<InputModelValidationResult>
}

// ─── Input Model Rows API ────────────────────────────────────────────────────

export async function listInputModelRows(inputModelId: string): Promise<InputModelRowsResponse> {
  return authorizedRequest<InputModelRowsResponse>(`/input-models/${inputModelId}/rows`, { method: "GET" })
}

export async function addInputModelRow(inputModelId: string, data: Record<string, unknown>): Promise<InputModelRow> {
  return authorizedRequest<InputModelRow>(`/input-models/${inputModelId}/rows`, {
    method: "POST",
    body: JSON.stringify({ data }),
  })
}

export async function addInputModelRowsBulk(inputModelId: string, rows: Record<string, unknown>[]): Promise<InputModelRowsResponse> {
  return authorizedRequest<InputModelRowsResponse>(`/input-models/${inputModelId}/rows/bulk`, {
    method: "POST",
    body: JSON.stringify({ rows }),
  })
}

export async function updateInputModelRow(rowId: string, data: Record<string, unknown>): Promise<InputModelRow> {
  return authorizedRequest<InputModelRow>(`/input-model-rows/${rowId}`, {
    method: "PUT",
    body: JSON.stringify({ data }),
  })
}

export async function deleteInputModelRow(rowId: string): Promise<void> {
  return authorizedRequest<void>(`/input-model-rows/${rowId}`, { method: "DELETE" })
}

export async function clearInputModelRows(inputModelId: string): Promise<{ deleted: number }> {
  return authorizedRequest<{ deleted: number }>(`/input-models/${inputModelId}/rows`, { method: "DELETE" })
}

// ─── Access Matrix API ───────────────────────────────────────────────────────

export type AccessMatrixProjectEntry = {
  project_id: string
  project_name: string
}

export type AccessMatrixUserProjectRole = {
  project_id: string
  explicit_role: string | null
  effective_role: string | null
  source: "explicit" | "inherited_ws" | "inherited_org" | "none"
}

export type AccessMatrixUserEntry = {
  user_id: string
  email: string
  full_name: string | null
  is_active: boolean
  org_role: string | null
  ws_explicit_role: string | null
  ws_effective_role: string | null
  ws_role_source: "explicit" | "inherited_org" | "none"
  project_roles: AccessMatrixUserProjectRole[]
}

export type AccessMatrixResponse = {
  workspace_id: string
  workspace_name: string
  organization_id: string
  projects: AccessMatrixProjectEntry[]
  users: AccessMatrixUserEntry[]
}

export async function getWorkspaceAccessMatrix(workspaceId: string): Promise<AccessMatrixResponse> {
  return authorizedRequest<AccessMatrixResponse>(`/workspaces/${workspaceId}/access-matrix`, { method: "GET" })
}

// ─── Workspace Members API ────────────────────────────────────────────────────

export async function listWorkspaceMembers(workspaceId: string): Promise<Member[]> {
  return authorizedRequest<Member[]>(`/workspaces/${workspaceId}/members`, { method: "GET" })
}

export async function addWorkspaceMember(
  workspaceId: string,
  payload: { email: string; role: string },
): Promise<Member> {
  return authorizedRequest<Member>(`/workspaces/${workspaceId}/members`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export async function updateWorkspaceMemberRole(
  workspaceId: string,
  userId: string,
  role: string,
): Promise<Member> {
  return authorizedRequest<Member>(`/workspaces/${workspaceId}/members/${userId}`, {
    method: "PUT",
    body: JSON.stringify({ role }),
  })
}

export async function removeWorkspaceMember(workspaceId: string, userId: string): Promise<void> {
  return authorizedRequest<void>(`/workspaces/${workspaceId}/members/${userId}`, { method: "DELETE" })
}

// ─── Project Members API ──────────────────────────────────────────────────────

export async function listProjectMembers(projectId: string): Promise<Member[]> {
  return authorizedRequest<Member[]>(`/projects/${projectId}/members`, { method: "GET" })
}

export async function addProjectMember(
  projectId: string,
  payload: { email: string; role: string },
): Promise<Member> {
  return authorizedRequest<Member>(`/projects/${projectId}/members`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export async function updateProjectMemberRole(
  projectId: string,
  userId: string,
  role: string,
): Promise<Member> {
  return authorizedRequest<Member>(`/projects/${projectId}/members/${userId}`, {
    method: "PUT",
    body: JSON.stringify({ role }),
  })
}

export async function removeProjectMember(projectId: string, userId: string): Promise<void> {
  return authorizedRequest<void>(`/projects/${projectId}/members/${userId}`, { method: "DELETE" })
}

// ─── Invitations API ──────────────────────────────────────────────────────────

export async function createWorkspaceInvitation(
  workspaceId: string,
  payload: { email: string; role: string },
): Promise<Invitation> {
  return authorizedRequest<Invitation>(`/workspaces/${workspaceId}/invitations`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export async function createProjectInvitation(
  projectId: string,
  payload: { email: string; role: string },
): Promise<Invitation> {
  return authorizedRequest<Invitation>(`/projects/${projectId}/invitations`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export async function listWorkspaceInvitations(workspaceId: string): Promise<Invitation[]> {
  return authorizedRequest<Invitation[]>(`/workspaces/${workspaceId}/invitations`, { method: "GET" })
}

export async function listProjectInvitations(projectId: string): Promise<Invitation[]> {
  return authorizedRequest<Invitation[]>(`/projects/${projectId}/invitations`, { method: "GET" })
}

export async function cancelInvitation(invitationId: string): Promise<void> {
  return authorizedRequest<void>(`/invitations/${invitationId}`, { method: "DELETE" })
}

export async function resendInvitation(invitationId: string): Promise<Invitation> {
  return authorizedRequest<Invitation>(`/invitations/${invitationId}/resend`, { method: "POST" })
}

export async function getInvitationByToken(token: string): Promise<InvitationDetail> {
  return request<InvitationDetail>(`/invitations/accept/${token}`, { method: "GET" })
}

export async function acceptInvitation(token: string): Promise<AcceptInvitationResult> {
  return authorizedRequest<AcceptInvitationResult>(`/invitations/accept/${token}`, { method: "POST" })
}
