"use client"

import { useEffect, useRef, useState } from "react"
import { X, Play, Eye, EyeOff, Building2, FolderOpen } from "lucide-react"
import type {
  Connection,
  ConnectionType,
  CreateConnectionPayload,
  DiagnosticStep,
  UpdateConnectionPayload,
  WorkspacePlayer,
  WorkspacePlayerDatabaseType,
} from "@/lib/auth"
import {
  diagnoseConnectionById,
  diagnoseConnectionPayload,
  testConnection,
  listWorkspacePlayers,
} from "@/lib/auth"
import { DiagnosticPanel } from "@/components/dashboard/diagnostic-panel"
import {
  FirebirdScenarioSelector,
  inferScenarioFromHost,
  type FirebirdScenario,
} from "@/components/dashboard/firebird-scenario-selector"
import type { DashboardScope } from "@/lib/dashboard-navigation"
import { MorphLoader } from "@/components/ui/morph-loader"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useToast } from "@/lib/context/toast-context"

// ─── Constantes ───────────────────────────────────────────────────────────────

const CONNECTION_TYPES: { value: ConnectionType; label: string }[] = [
  { value: "postgresql", label: "PostgreSQL" },
  { value: "sqlserver", label: "SQL Server" },
  { value: "oracle", label: "Oracle" },
  { value: "mysql", label: "MySQL" },
  { value: "firebird", label: "Firebird" },
]

const DEFAULT_PORTS: Record<ConnectionType, number> = {
  postgresql: 5432,
  sqlserver: 1433,
  oracle: 1521,
  mysql: 3306,
  firebird: 3050,
}

/** Mapeia o database_type do sistema para o ConnectionType da conexão */
const PLAYER_DB_TYPE_MAP: Partial<Record<WorkspacePlayerDatabaseType, ConnectionType>> = {
  POSTGRESQL: "postgresql",
  MYSQL: "mysql",
  SQLSERVER: "sqlserver",
  ORACLE: "oracle",
  FIREBIRD: "firebird",
}

// ─── Firebird URL parser ───────────────────────────────────────────────────────

interface ParsedFirebirdUrl {
  host: string
  port: number
  database: string
  /** Cenario inferido do host parseado — ajuda o wizard a se manter sincronizado. */
  scenario?: FirebirdScenario
  error?: string
}

function parseFirebirdUrl(raw: string): ParsedFirebirdUrl {
  let url = raw.trim()
  url = url.replace(/^jdbc:firebirdsql:\/\//i, "")
  url = url.replace(/^firebird[\w+]*:\/\//i, "")

  if (url.startsWith("/")) {
    const database = url.slice(1)
    if (!database)
      return { host: "", port: 3050, database: "", error: "Informe o caminho do arquivo .fdb." }
    return {
      host: "localhost",
      port: 3050,
      database,
      scenario: inferScenarioFromHost("localhost"),
    }
  }

  const slashIdx = url.indexOf("/")
  if (slashIdx === -1) {
    const looksLikePath =
      /^[a-zA-Z]:[\\\/]/.test(url) || url.includes("\\") || url.includes("/")
    if (looksLikePath)
      return {
        host: "localhost",
        port: 3050,
        database: url,
        scenario: inferScenarioFromHost("localhost"),
      }
    return {
      host: "",
      port: 3050,
      database: "",
      error: "URL inválida. Informe o caminho após o host: 192.168.1.1:3050/caminho/MYDB.FDB",
    }
  }

  const hostPart = url.slice(0, slashIdx)
  const database = url.slice(slashIdx + 1)
  if (!database)
    return {
      host: "",
      port: 3050,
      database: "",
      error: "Informe o caminho do arquivo .fdb após o host.",
    }

  const colonIdx = hostPart.lastIndexOf(":")
  if (colonIdx === -1)
    return {
      host: hostPart,
      port: 3050,
      database,
      scenario: inferScenarioFromHost(hostPart),
    }

  const portStr = hostPart.slice(colonIdx + 1)
  const port = parseInt(portStr, 10)
  if (isNaN(port) || port < 1 || port > 65535)
    return { host: "", port: 3050, database: "", error: `Porta inválida: ${portStr}` }

  const finalHost = hostPart.slice(0, colonIdx)
  return {
    host: finalHost,
    port,
    database,
    scenario: inferScenarioFromHost(finalHost),
  }
}

function getPathDirectory(path: string): string {
  const trimmed = path.trim()
  const lastSeparator = Math.max(trimmed.lastIndexOf("\\"), trimmed.lastIndexOf("/"))
  if (lastSeparator === -1) return ""
  return trimmed.slice(0, lastSeparator)
}

function getSelectedFileAbsolutePath(input: HTMLInputElement, file: File): string {
  const fileWithPath = file as File & { path?: string }
  const nativePath = fileWithPath.path?.trim()
  if (nativePath) return nativePath

  const inputValue = input.value?.trim()
  if (!inputValue) return ""
  if (/^[a-zA-Z]:\\fakepath\\/i.test(inputValue)) return ""

  return inputValue
}

// ─── Tipos internos ───────────────────────────────────────────────────────────

type FirebirdMode = "fields" | "url"
type FirebirdVersion = "auto" | "3+" | "2.5"

const FIREBIRD_VERSIONS: { value: FirebirdVersion; label: string }[] = [
  { value: "auto", label: "Auto-detectar" },
  { value: "3+", label: "Firebird 3.0 ou superior" },
  { value: "2.5", label: "Firebird 2.5" },
]

/** Dica contextual quando uma etapa do diagnostico falha — combina o
 * cenario escolhido com a error_class para apontar a causa mais provavel. */
function scenarioContextualHint(
  scenario: FirebirdScenario,
  errorClass: string | null,
  database: string,
): string | null {
  if (!errorClass) return null
  if (scenario === "windows-host" && errorClass === "port_closed") {
    return "Verifique o Windows Firewall (comando PowerShell acima)."
  }
  if (scenario === "bundled" && errorClass === "path_not_found") {
    const fileName =
      database
        .split(/[\\/]/)
        .filter(Boolean)
        .pop() || "arquivo.fdb"
    return `O arquivo precisa estar em FIREBIRD_LEGACY_DATA_DIR. Caminho dentro do container: /firebird/data/${fileName}.`
  }
  if (scenario === "bundled" && errorClass === "wrong_ods") {
    return "Mude a versão do servidor — o arquivo é ODS de uma versão diferente da selecionada."
  }
  if (scenario === "bundled" && errorClass === "database_locked") {
    return (
      "O arquivo .fdb está sendo segurado por outro processo (geralmente o " +
      "Firebird Server local do Windows ou uma sessão DBeaver/IBExpert ativa). " +
      "Solução rápida: faça uma cópia dedicada para a Shift (`Copy-Item " +
      "C:\\Shift\\Data\\X.FDB C:\\Shift\\Data\\X_SHIFT.FDB`) e use o nome novo " +
      "no campo 'Caminho do arquivo .fdb'."
    )
  }
  return null
}

function normalizeFirebirdVersion(raw: unknown): FirebirdVersion {
  const s = String(raw ?? "").trim().toLowerCase()
  if (s === "2.5" || s === "2" || s === "fb2" || s === "fb2.5" || s === "fdb") return "2.5"
  if (s === "3+" || s === "3" || s === "3.0") return "3+"
  // Default = auto. Backend le o ODS do arquivo e decide.
  return "auto"
}

interface ConnectionFormModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  connection: Connection | null
  scope: DashboardScope
  workspaceId: string | null
  projectId: string | null
  onSubmit: (payload: CreateConnectionPayload | UpdateConnectionPayload) => Promise<void>
}

// ─── Componente ───────────────────────────────────────────────────────────────

export function ConnectionFormModal({
  open,
  onOpenChange,
  connection,
  scope,
  workspaceId,
  projectId,
  onSubmit,
}: ConnectionFormModalProps) {
  const isEditing = connection !== null
  const toast = useToast()

  // ── Campos principais ──
  const [name, setName] = useState("")
  const [isPublic, setIsPublic] = useState(true)
  const [type, setType] = useState<ConnectionType>("postgresql")
  const [host, setHost] = useState("")
  const [port, setPort] = useState(5432)
  const [database, setDatabase] = useState("")
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  // ── Sistema (player) ──
  const [players, setPlayers] = useState<WorkspacePlayer[]>([])
  const [playersLoading, setPlayersLoading] = useState(false)
  const [selectedPlayerId, setSelectedPlayerId] = useState<string | null>(null)

  // ── Firebird: modo de entrada (só quando sem player) ──
  const [firebirdMode, setFirebirdMode] = useState<FirebirdMode>("fields")
  const [firebirdUrl, setFirebirdUrl] = useState("")
  const [urlParseError, setUrlParseError] = useState("")
  // Lazy initializer le direto da prop. Combinado com `key` no parent que
  // forca remontagem ao trocar de conexao, garante que o valor inicial seja
  // sempre o que veio do backend — sem depender do useEffect.
  const [firebirdVersion, setFirebirdVersion] = useState<FirebirdVersion>(
    () => normalizeFirebirdVersion(connection?.extra_params?.firebird_version),
  )
  // Cenario do wizard. Inicializa por inferencia do host quando editando.
  const [firebirdScenario, setFirebirdScenario] = useState<FirebirdScenario>(
    () => inferScenarioFromHost(connection?.host),
  )

  // ── Firebird: builder inline de caminho ──
  const [pickedFileName, setPickedFileName] = useState<string | null>(null)
  const [builderDir, setBuilderDir] = useState("")
  const fileInputRef = useRef<HTMLInputElement>(null)

  // ── Schemas adicionais (Oracle / multi-schema) ──
  const [includeSchemasRaw, setIncludeSchemasRaw] = useState("")

  // ── Senha ──
  const [showPassword, setShowPassword] = useState(false)

  // ── Teste de conexão ──
  const [testing, setTesting] = useState(false)
  const [diagnosticSteps, setDiagnosticSteps] = useState<DiagnosticStep[]>([])

  /** Player atualmente selecionado (objeto completo) */
  const selectedPlayer = players.find((p) => p.id === selectedPlayerId) ?? null

  const isFirebird = isEditing ? connection.type === "firebird" : type === "firebird"

  // ─── Carrega players ao abrir ───────────────────────────────────────────────

  useEffect(() => {
    if (!open || !workspaceId) return
    setPlayersLoading(true)
    listWorkspacePlayers(workspaceId)
      .then(setPlayers)
      .catch(() => setPlayers([]))
      .finally(() => setPlayersLoading(false))
  }, [open, workspaceId])

  // ─── Inicialização ──────────────────────────────────────────────────────────

  useEffect(() => {
    if (!open) return
    // firebirdVersion ja foi inicializado da prop via lazy useState — nao
    // sobrescrever aqui senao seria redundante e re-executaria a cada mudanca
    // de prop. Os outros campos sao seguros pra setar via useEffect porque
    // nao tem o mesmo padrao de Select controlado.
    if (connection) {
      setName(connection.name)
      setIsPublic(connection.is_public)
      setType(connection.type)
      setHost(connection.host)
      setPort(connection.port)
      setDatabase(connection.database)
      setUsername(connection.username)
      setPassword("")
      setSelectedPlayerId(connection.player_id ?? null)
      setIncludeSchemasRaw(connection.include_schemas?.join(", ") ?? "")
      setFirebirdMode("fields")
      setFirebirdUrl("")
      setFirebirdScenario(inferScenarioFromHost(connection.host))
    } else {
      setName("")
      setIsPublic(true)
      setType("postgresql")
      setHost("")
      setPort(5432)
      setDatabase("")
      setUsername("")
      setPassword("")
      setSelectedPlayerId(null)
      setIncludeSchemasRaw("")
      setFirebirdMode("fields")
      setFirebirdUrl("")
      setFirebirdScenario("bundled")
    }
    setError("")
    setUrlParseError("")
    setShowPassword(false)
    setPickedFileName(null)
    setBuilderDir("")
    setDiagnosticSteps([])
  }, [open, connection])

  // ─── Keyboard / body overflow ───────────────────────────────────────────────

  useEffect(() => {
    if (!open) return
    const onEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !loading) onOpenChange(false)
    }
    document.addEventListener("keydown", onEscape)
    return () => document.removeEventListener("keydown", onEscape)
  }, [open, loading, onOpenChange])

  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = prev
    }
  }, [open])

  // ─── Handlers ───────────────────────────────────────────────────────────────

  function handlePlayerChange(playerId: string) {
    if (playerId === "__none__") {
      setSelectedPlayerId(null)
      return
    }
    const player = players.find((p) => p.id === playerId)
    if (!player) return
    setSelectedPlayerId(playerId)
    // Sugere o tipo de banco do sistema (usuário pode alterar)
    const mappedType = PLAYER_DB_TYPE_MAP[player.database_type]
    if (mappedType && !isEditing) {
      setType(mappedType)
      setPort(DEFAULT_PORTS[mappedType])
      setFirebirdMode("fields")
      setFirebirdUrl("")
      setUrlParseError("")
    }
  }

  function buildPath(dir: string, file: string): string {
    const d = dir.trim()
    const f = file.trim()
    if (!d) return f
    if (!f) return d
    const sep = d.includes("/") ? "/" : "\\"
    return d.endsWith("/") || d.endsWith("\\") ? `${d}${f}` : `${d}${sep}${f}`
  }

  function handleFileInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return

    const absolutePath = getSelectedFileAbsolutePath(e.target, file)
    if (absolutePath) {
      setPickedFileName(null)
      setBuilderDir("")
      setDatabase(absolutePath)
      e.target.value = ""
      return
    }

    const nextDir = builderDir.trim() || getPathDirectory(database)

    setPickedFileName(file.name)
    setBuilderDir(nextDir)
    setDatabase(nextDir ? buildPath(nextDir, file.name) : file.name)
    e.target.value = ""
  }

  function handleBuilderDirChange(dir: string) {
    setBuilderDir(dir)
    if (pickedFileName) setDatabase(buildPath(dir, pickedFileName))
  }

  function dismissBuilder() {
    setPickedFileName(null)
    setBuilderDir("")
  }

  function handleTypeChange(val: string) {
    const newType = val as ConnectionType
    setType(newType)
    if (!isEditing) setPort(DEFAULT_PORTS[newType])
    setFirebirdMode("fields")
    setFirebirdUrl("")
    setUrlParseError("")
  }

  function handleFirebirdModeChange(mode: FirebirdMode) {
    setFirebirdMode(mode)
    setUrlParseError("")
    if (mode === "url" && host) {
      const isLocal = host === "localhost" || host === "127.0.0.1"
      setFirebirdUrl(isLocal ? `/${database}` : `${host}:${port}/${database}`)
    }
  }

  function handleUrlChange(val: string) {
    setFirebirdUrl(val)
    setUrlParseError("")
    if (val.trim()) {
      const parsed = parseFirebirdUrl(val)
      if (!parsed.error) {
        setHost(parsed.host)
        setPort(parsed.port)
        setDatabase(parsed.database)
        // Mantem o wizard alinhado com o que o usuario digitou na URL.
        if (parsed.scenario && parsed.scenario !== firebirdScenario) {
          setFirebirdScenario(parsed.scenario)
        }
      }
    }
  }

  /** Host bundled correspondente a versao escolhida. */
  function bundledHostFor(version: FirebirdVersion): string {
    return version === "2.5" ? "firebird25" : "firebird30"
  }

  /** Aplica os defaults do cenario aos campos host/port. Preserva
   * username/password/name/database (apenas sobrescreve se database era
   * tipico do cenario anterior — caso contrario respeita o que o usuario
   * digitou). */
  function applyScenarioDefaults(scenario: FirebirdScenario) {
    if (scenario === "bundled") {
      setHost(bundledHostFor(firebirdVersion))
      setPort(3050)
    } else if (scenario === "windows-host") {
      setHost("host.docker.internal")
      setPort(3050)
    } else {
      // remote-server: limpa o host se vinha de um cenario com auto-fill
      // para o usuario nao confundir com um placeholder.
      const h = host.trim().toLowerCase()
      if (
        h === "host.docker.internal" ||
        h === "firebird25" ||
        h === "firebird30"
      ) {
        setHost("")
      }
    }
  }

  function handleScenarioChange(next: FirebirdScenario) {
    setFirebirdScenario(next)
    applyScenarioDefaults(next)
  }

  // Quando muda a versao FB no cenario bundled, sincroniza o host
  // (firebird25 <-> firebird30). Nao mexe nos demais cenarios.
  useEffect(() => {
    if (!isFirebird) return
    if (firebirdScenario !== "bundled") return
    const expected = bundledHostFor(firebirdVersion)
    if (host !== expected) setHost(expected)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [firebirdVersion, firebirdScenario, isFirebird])

  /** Monta extra_params do Firebird preservando chaves existentes da conexao
   * (ex: fb_library_name custom) e gravando firebird_version conforme a
   * escolha do usuario. "auto" remove a chave para o backend usar o default. */
  function buildFirebirdExtraParams(): Record<string, unknown> | null {
    const baseParams: Record<string, unknown> = connection?.extra_params
      ? { ...connection.extra_params }
      : {}
    if (firebirdVersion === "auto") {
      delete baseParams.firebird_version
    } else {
      baseParams.firebird_version = firebirdVersion
    }
    return Object.keys(baseParams).length > 0 ? baseParams : null
  }

  /** Resolve host/port/database considerando o modo URL do Firebird. */
  function resolveTargetFields():
    | { host: string; port: number; database: string }
    | { error: string } {
    let resolvedHost = host
    let resolvedPort = port
    let resolvedDatabase = database

    if (isFirebird && firebirdMode === "url") {
      const parsed = parseFirebirdUrl(firebirdUrl)
      if (parsed.error) return { error: parsed.error }
      resolvedHost = parsed.host
      resolvedPort = parsed.port
      resolvedDatabase = parsed.database
    }

    if (!resolvedHost.trim()) return { error: "Informe o host." }
    if (!resolvedDatabase.trim())
      return {
        error: isFirebird
          ? "Informe o caminho do arquivo .fdb."
          : "Informe o banco de dados.",
      }
    return {
      host: resolvedHost.trim(),
      port: resolvedPort,
      database: resolvedDatabase.trim(),
    }
  }

  /** Habilita o botao "Testar" quando ha campos minimos preenchidos.
   * Para Firebird, aplica validacoes especificas do cenario selecionado. */
  const canTest = (() => {
    if (testing || loading) return false
    if (!username.trim()) return false
    if (!isEditing && !password) return false
    if (isFirebird && firebirdMode === "url") return firebirdUrl.trim().length > 0

    const dbTrim = database.trim()
    const hostTrim = host.trim()
    if (!hostTrim || !dbTrim) return false

    if (isFirebird) {
      if (firebirdScenario === "bundled") {
        return /\.fdb$/i.test(dbTrim)
      }
      if (firebirdScenario === "windows-host") {
        return /^[A-Za-z]:[\\/]/.test(dbTrim)
      }
      // remote-server: host obrigatorio (ja validado), nada alem disso.
      return true
    }
    return true
  })()

  async function handleTest() {
    setError("")
    setDiagnosticSteps([])
    setTesting(true)
    try {
      if (isEditing && connection) {
        // Modo edicao: para Firebird, usa o pipeline de 4 etapas via
        // /connections/{id}/diagnose. Para outros tipos, o backend
        // retorna 400 e caimos no /connections/{id}/test legacy (1 step).
        try {
          const report = await diagnoseConnectionById(connection.id)
          setDiagnosticSteps(report.steps)
          return
        } catch {
          // Fallback intencional: cobre nao-Firebird (400) e qualquer
          // outro erro — pior caso, mostra 1 step com a mensagem do
          // backend, sem perder a informacao do erro real.
          const result = await testConnection(connection.id)
          setDiagnosticSteps([
            {
              stage: "test",
              ok: result.success,
              latency_ms: null,
              error_class: result.success ? null : "unknown",
              error_msg: result.success ? null : result.message,
              hint: result.success ? null : result.message,
            },
          ])
          return
        }
      }

      // Modo criacao: testa o payload atual sem persistir.
      const target = resolveTargetFields()
      if ("error" in target) {
        setError(target.error)
        return
      }
      const extraParams = isFirebird ? buildFirebirdExtraParams() : null
      const report = await diagnoseConnectionPayload({
        type,
        host: target.host,
        port: target.port,
        database: target.database,
        username: username.trim(),
        password,
        extra_params: extraParams,
      })
      setDiagnosticSteps(report.steps)
    } catch (err) {
      toast.error(
        "Falha na conexão",
        err instanceof Error ? err.message : "Erro ao testar conexão.",
      )
    } finally {
      setTesting(false)
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError("")
    setUrlParseError("")

    if (!name.trim()) {
      setError("Informe o nome da conexão.")
      return
    }

    // Resolve host / port / database finais
    let resolvedHost = host
    let resolvedPort = port
    let resolvedDatabase = database

    // Firebird em modo URL
    if (isFirebird && firebirdMode === "url") {
      if (!firebirdUrl.trim()) {
        setUrlParseError("Informe a URL de conexão.")
        return
      }
      const parsed = parseFirebirdUrl(firebirdUrl)
      if (parsed.error) {
        setUrlParseError(parsed.error)
        return
      }
      resolvedHost = parsed.host
      resolvedPort = parsed.port
      resolvedDatabase = parsed.database
    }

    if (!resolvedHost.trim()) {
      setError("Informe o host.")
      return
    }
    if (!resolvedDatabase.trim()) {
      setError(isFirebird ? "Informe o caminho do arquivo .fdb." : "Informe o banco de dados.")
      return
    }
    if (!username.trim()) {
      setError("Informe o usuário.")
      return
    }
    if (!isEditing && !password) {
      setError("Informe a senha.")
      return
    }

    const parsedSchemas = includeSchemasRaw
      .split(",")
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean)
    const includeSchemas = parsedSchemas.length > 0 ? parsedSchemas : null

    setLoading(true)
    try {
      if (isEditing) {
        const payload: UpdateConnectionPayload = {
          name: name.trim(),
          player_id: selectedPlayerId,
          host: resolvedHost.trim(),
          port: resolvedPort,
          database: resolvedDatabase.trim(),
          username: username.trim(),
          include_schemas: includeSchemas,
          is_public: isPublic,
        }
        if (isFirebird) payload.extra_params = buildFirebirdExtraParams()
        if (password) payload.password = password
        await onSubmit(payload)
      } else {
        const payload: CreateConnectionPayload = {
          name: name.trim(),
          type,
          player_id: selectedPlayerId,
          host: resolvedHost.trim(),
          port: resolvedPort,
          database: resolvedDatabase.trim(),
          username: username.trim(),
          password,
          include_schemas: includeSchemas,
          is_public: isPublic,
        }
        if (isFirebird) payload.extra_params = buildFirebirdExtraParams()
        if (scope === "space" && workspaceId) {
          payload.workspace_id = workspaceId
        } else if (projectId) {
          payload.project_id = projectId
        } else {
          setError("Nenhum workspace ou projeto selecionado.")
          return
        }
        await onSubmit(payload)
      }
    } catch (err) {
      toast.error("Erro ao salvar", err instanceof Error ? err.message : "Erro ao salvar conexão.")
    } finally {
      setLoading(false)
    }
  }

  if (!open) return null

  const inputClass =
    "h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground outline-none transition focus:ring-2 focus:ring-ring placeholder:text-muted-foreground disabled:opacity-60"

  const databaseLabel = isFirebird ? "Caminho do arquivo .fdb" : "Banco de dados"
  const databasePlaceholder = isFirebird
    ? "Ex: C:\\Shift\\Data\\MYDB.FDB  ou  /opt/shift/data/MYDB.FDB"
    : "Ex: erp_prod"

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-[2px]"
      role="presentation"
      onClick={() => !loading && onOpenChange(false)}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={isEditing ? "Editar conexão" : "Nova conexão"}
        className="flex w-[min(960px,96vw)] max-h-[92vh] flex-col rounded-2xl border border-border bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <p className="text-base font-semibold text-foreground">
              {isEditing ? "Editar conexão" : "Nova conexão"}
            </p>
            <p className="text-xs text-muted-foreground">
              {isEditing
                ? "Altere os dados da conexão. Deixe a senha em branco para manter a atual."
                : scope === "space"
                  ? "Conexão compartilhada do workspace — visível em todos os projetos."
                  : "Conexão exclusiva deste projeto."}
            </p>
          </div>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={loading}
            className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-60"
            aria-label="Fechar"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={(e) => void handleSubmit(e)} className="flex min-h-0 flex-1 flex-col">
          <div className="flex-1 overflow-y-auto px-6 py-5">

            {/* Layout em 2 colunas — esquerda: identificacao + credenciais.
                Direita: como conectar (mais denso, dominante). */}
            <div className="grid grid-cols-1 gap-x-6 gap-y-5 md:grid-cols-2">

            {/* ╔═ COLUNA 1 ═══════════════════════════════════════════════ */}
            <div className="space-y-5">

            {/* ── SEÇÃO: Identificação ─────────────────────────────────── */}
            <div className="space-y-3">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
                Identificação
              </p>

              {/* Nome */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Nome *</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Ex: ERP Produção"
                  disabled={loading}
                  className={inputClass}
                />
              </div>

            {/* Sistema */}
            <div className="space-y-1.5">
              <label className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                <Building2 className="size-3.5" />
                Sistema
              </label>
              {playersLoading ? (
                <div className="flex h-9 items-center gap-2 rounded-md border border-input bg-background px-3 text-sm text-muted-foreground">
                  <MorphLoader className="size-3.5" />
                  Carregando sistemas…
                </div>
              ) : (
                <Select
                  value={selectedPlayerId ?? "__none__"}
                  onValueChange={handlePlayerChange}
                  disabled={loading}
                >
                  <SelectTrigger className="w-full bg-background">
                    <SelectValue placeholder="Selecione um sistema (opcional)" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">
                      <span className="text-muted-foreground">Sem sistema</span>
                    </SelectItem>
                    {players.map((p) => (
                      <SelectItem key={p.id} value={p.id}>
                        <span>{p.name}</span>
                        <span className="ml-2 text-[10px] text-muted-foreground">
                          ({p.database_type})
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              {selectedPlayer && (
                <p className="text-[11px] text-muted-foreground">
                  Tipo de banco:{" "}
                  <span className="font-medium text-foreground">{selectedPlayer.database_type}</span>
                </p>
              )}
              {players.length === 0 && !playersLoading && (
                <p className="text-[11px] text-muted-foreground">
                  Nenhum sistema cadastrado no workspace. Cadastre em{" "}
                  <span className="font-medium">Configurações → Sistemas</span>.
                </p>
              )}
            </div>

            {/* Visibilidade */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Visibilidade</label>
              <div className="inline-flex w-full items-center rounded-md border border-border bg-background p-1">
                <button
                  type="button"
                  onClick={() => setIsPublic(true)}
                  disabled={loading}
                  className={`flex flex-1 items-center justify-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                    isPublic
                      ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Eye className="size-3.5" />
                  Pública
                </button>
                <button
                  type="button"
                  onClick={() => setIsPublic(false)}
                  disabled={loading}
                  className={`flex flex-1 items-center justify-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                    !isPublic
                      ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <EyeOff className="size-3.5" />
                  Privada
                </button>
              </div>
              <p className="text-[11px] text-muted-foreground">
                {isPublic
                  ? `Visível para todos os membros do ${scope === "space" ? "workspace" : "projeto"}.`
                  : "Visível apenas para você."}
              </p>
            </div>

            {/* Tipo de banco (só no criar) */}
            {!isEditing && (
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">
                  Tipo de banco *
                </label>
                <Select value={type} onValueChange={handleTypeChange}>
                  <SelectTrigger className="w-full bg-background">
                    <SelectValue placeholder="Selecione o tipo" />
                  </SelectTrigger>
                  <SelectContent>
                    {CONNECTION_TYPES.map((t) => (
                      <SelectItem key={t.value} value={t.value}>
                        {t.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            </div>
            {/* ── /SEÇÃO Identificação ─────────────────────────────────── */}

            {/* ── SEÇÃO: Credenciais (coluna 1) ────────────────────────── */}
            <div className="space-y-3">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
                Credenciais
              </p>
              <div className="grid grid-cols-2 gap-3">
                {/* Usuário */}
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">Usuário *</label>
                  <input
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="Ex: sysdba"
                    disabled={loading}
                    className={inputClass}
                  />
                </div>
                {/* Senha */}
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">
                    Senha {isEditing ? <span className="text-muted-foreground/60">(em branco mantém)</span> : "*"}
                  </label>
                  <div className="relative">
                    <input
                      type={showPassword ? "text" : "password"}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder={isEditing ? "••••••••" : "Senha"}
                      disabled={loading}
                      className={`${inputClass} pr-10`}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((v) => !v)}
                      tabIndex={-1}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                      aria-label={showPassword ? "Ocultar senha" : "Mostrar senha"}
                    >
                      {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                    </button>
                  </div>
                </div>
              </div>
            </div>
            {/* ── /SEÇÃO Credenciais ──────────────────────────────────── */}

            </div>
            {/* ╚═ /COLUNA 1 ════════════════════════════════════════════ */}

            {/* ╔═ COLUNA 2 ═══════════════════════════════════════════════ */}
            <div className="space-y-5">

            {/* ── SEÇÃO: Como conectar ─────────────────────────────────── */}
            <div className="space-y-3">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
                Como conectar
              </p>

            {/* ── Firebird: wizard de cenário + URL/Campos ── */}
            {isFirebird && (
              <div className="space-y-3">
                {/* Wizard de cenário — direciona como o backend vai conectar */}
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">
                    Como o Firebird está disponível?
                  </label>
                  <FirebirdScenarioSelector
                    value={firebirdScenario}
                    onChange={handleScenarioChange}
                    disabled={loading}
                  />
                </div>

                {firebirdScenario === "bundled" && (
                  <p className="text-[11px] leading-relaxed text-muted-foreground">
                    Coloque o <span className="font-mono text-foreground/90">.fdb</span> em{" "}
                    <span className="font-mono text-foreground/90">C:\Shift\Data</span>{" "}
                    <span className="text-muted-foreground/60">(Windows)</span> ou{" "}
                    <span className="font-mono text-foreground/90">/opt/shift/data</span>{" "}
                    <span className="text-muted-foreground/60">(Linux)</span>. Suba o stack com{" "}
                    <span className="font-mono text-foreground/90">
                      docker compose --profile firebird-legacy up -d
                    </span>
                    .
                  </p>
                )}
                {firebirdScenario === "windows-host" && (
                  <p className="text-[11px] leading-relaxed text-muted-foreground">
                    Garanta que o serviço Firebird está rodando e libere a porta 3050 no Firewall:{" "}
                    <span className="font-mono text-foreground/90">
                      New-NetFirewallRule -DisplayName Firebird-3050 -Direction Inbound -Protocol TCP -LocalPort 3050 -Action Allow
                    </span>
                  </p>
                )}
                {firebirdScenario === "remote-server" && (
                  <p className="text-[11px] leading-relaxed text-muted-foreground">
                    Informe IP ou hostname do servidor Firebird na rede. O caminho do arquivo deve ser{" "}
                    <span className="font-medium text-foreground/90">conforme visto pelo servidor</span>.
                  </p>
                )}

                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-muted-foreground">
                      Versão Firebird
                    </label>
                    <Select
                      value={firebirdVersion}
                      onValueChange={(v) => setFirebirdVersion(v as FirebirdVersion)}
                      disabled={loading}
                    >
                      <SelectTrigger className="w-full bg-background">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {FIREBIRD_VERSIONS.map((v) => (
                          <SelectItem key={v.value} value={v.value}>
                            {v.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-muted-foreground">
                      Modo de entrada
                    </label>
                    <div className="inline-flex h-9 w-full items-center rounded-md border border-border bg-background p-1">
                      <button
                        type="button"
                        onClick={() => handleFirebirdModeChange("fields")}
                        disabled={loading}
                        className={`flex-1 rounded px-2 py-1 text-xs font-medium transition-colors ${
                          firebirdMode === "fields"
                            ? "bg-accent text-foreground"
                            : "text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        Campos
                      </button>
                      <button
                        type="button"
                        onClick={() => handleFirebirdModeChange("url")}
                        disabled={loading}
                        className={`flex-1 rounded px-2 py-1 text-xs font-medium transition-colors ${
                          firebirdMode === "url"
                            ? "bg-accent text-foreground"
                            : "text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        URL
                      </button>
                    </div>
                  </div>
                </div>
                {firebirdVersion === "auto" && (
                  <p className="text-[11px] italic text-muted-foreground">
                    Auto-detectar lê o cabeçalho do <span className="font-mono">.fdb</span> e escolhe
                    o servidor embutido compatível (FB 2.5 ou 3.0+).
                  </p>
                )}

                {firebirdMode === "url" ? (
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-muted-foreground">
                      URL de conexão *
                    </label>
                    <input
                      type="text"
                      value={firebirdUrl}
                      onChange={(e) => handleUrlChange(e.target.value)}
                      placeholder="Ex: 192.168.1.1:3050/D:\Data\MYDB.FDB"
                      disabled={loading}
                      className={inputClass}
                    />
                    <div className="space-y-1 rounded-md border border-border bg-background/50 px-3 py-2 text-[11px] text-muted-foreground">
                      <p className="font-medium text-foreground/80">Formatos aceitos:</p>
                      <p>
                        <span className="font-mono text-foreground/70">
                          192.168.1.1:3050/C:\Sistemas\MYDB.FDB
                        </span>{" "}
                        — remoto
                      </p>
                      <p>
                        <span className="font-mono text-foreground/70">
                          /C:\Shift\Data\MYDB.FDB
                        </span>{" "}
                        — bundled (Windows, pasta padrão Shift)
                      </p>
                      <p>
                        <span className="font-mono text-foreground/70">
                          /opt/shift/data/MYDB.FDB
                        </span>{" "}
                        — bundled (Linux, pasta padrão Shift)
                      </p>
                    </div>
                    {firebirdUrl.trim() &&
                      !urlParseError &&
                      (() => {
                        const p = parseFirebirdUrl(firebirdUrl)
                        if (p.error || !p.database) return null
                        return (
                          <div className="flex flex-wrap gap-x-4 gap-y-1 rounded-md border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-[11px]">
                            <span className="text-muted-foreground">
                              Host:{" "}
                              <span className="font-medium text-foreground">
                                {p.host === "localhost" ? "localhost (local)" : p.host}
                              </span>
                            </span>
                            <span className="text-muted-foreground">
                              Porta:{" "}
                              <span className="font-medium text-foreground">{p.port}</span>
                            </span>
                            <span className="text-muted-foreground">
                              Caminho:{" "}
                              <span className="font-medium text-foreground">{p.database}</span>
                            </span>
                          </div>
                        )
                      })()}
                    {urlParseError && (
                      <p className="text-[11px] text-destructive">{urlParseError}</p>
                    )}
                  </div>
                ) : (
                  /* Modo Campos — host + porta abaixo, caminho com path builder */
                  <>
                    <div className="grid grid-cols-[1fr_100px] gap-3">
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between">
                          <label className="text-xs font-medium text-muted-foreground">
                            Host *
                          </label>
                          {firebirdScenario === "bundled" && (
                            <span className="inline-flex items-center rounded-sm bg-emerald-500/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-emerald-600 dark:text-emerald-400">
                              Embutido
                            </span>
                          )}
                          {firebirdScenario === "windows-host" && (
                            <span className="inline-flex items-center rounded-sm bg-emerald-500/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-emerald-600 dark:text-emerald-400">
                              Host Docker
                            </span>
                          )}
                        </div>
                        <input
                          type="text"
                          value={host}
                          onChange={(e) => setHost(e.target.value)}
                          placeholder={
                            firebirdScenario === "remote-server"
                              ? "Ex: 192.168.1.100"
                              : "Auto-preenchido"
                          }
                          disabled={loading}
                          readOnly={firebirdScenario !== "remote-server"}
                          aria-readonly={firebirdScenario !== "remote-server"}
                          className={`${inputClass} ${
                            firebirdScenario !== "remote-server"
                              ? "cursor-not-allowed bg-muted/40 text-foreground/70"
                              : ""
                          }`}
                        />
                      </div>
                      <div className="space-y-1.5">
                        <label className="text-xs font-medium text-muted-foreground">
                          Porta *
                        </label>
                        <input
                          type="number"
                          value={port}
                          onChange={(e) => setPort(Number(e.target.value))}
                          min={1}
                          max={65535}
                          disabled={loading}
                          readOnly={firebirdScenario === "bundled"}
                          aria-readonly={firebirdScenario === "bundled"}
                          className={`${inputClass} ${
                            firebirdScenario === "bundled"
                              ? "cursor-not-allowed bg-muted/40 text-foreground/70"
                              : ""
                          }`}
                        />
                      </div>
                    </div>

                    <div className="space-y-1.5">
                      <label className="text-xs font-medium text-muted-foreground">
                        Caminho do arquivo .fdb *
                      </label>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={database}
                          onChange={(e) => { setDatabase(e.target.value); dismissBuilder() }}
                          placeholder={
                            firebirdScenario === "bundled"
                              ? "Ex: C:\\Shift\\Data\\EMPRESA.FDB  ou  /opt/shift/data/EMPRESA.FDB"
                              : "Ex: C:\\Sistemas\\ERP\\EMPRESA.FDB (path do servidor)"
                          }
                          disabled={loading}
                          className={inputClass}
                        />
                        <button
                          type="button"
                          onClick={() => fileInputRef.current?.click()}
                          disabled={loading}
                          title="Selecionar arquivo para obter o nome"
                          className="inline-flex h-9 items-center justify-center rounded-md border border-border bg-background px-3 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
                        >
                          <FolderOpen className="size-4" />
                        </button>
                        <input
                          ref={fileInputRef}
                          type="file"
                          accept=".fdb,.gdb"
                          className="hidden"
                          onChange={handleFileInputChange}
                        />
                      </div>

                      {/* Builder inline — aparece após escolher arquivo */}
                      {pickedFileName && (
                        <div className="rounded-md border border-border bg-muted/40 p-3 space-y-2">
                          <div className="flex items-center justify-between">
                            <p className="text-[11px] font-medium text-foreground/80">
                              Arquivo selecionado:{" "}
                              <span className="font-mono text-foreground">{pickedFileName}</span>
                            </p>
                            <button
                              type="button"
                              onClick={dismissBuilder}
                              className="text-muted-foreground hover:text-foreground"
                              title="Fechar"
                            >
                              <X className="size-3.5" />
                            </button>
                          </div>
                          {!builderDir && (
                            <p className="text-[11px] text-muted-foreground">
                              O navegador informa apenas o nome do arquivo. Informe abaixo o diretório
                              absoluto onde ele existe no servidor.
                            </p>
                          )}
                          <div className="space-y-1">
                            <label className="text-[11px] text-muted-foreground">
                              Diretório no servidor onde o arquivo está:
                            </label>
                            <input
                              type="text"
                              value={builderDir}
                              onChange={(e) => handleBuilderDirChange(e.target.value)}
                              placeholder={
                                firebirdScenario === "bundled"
                                  ? "Ex: C:\\Shift\\Data  ou  /opt/shift/data"
                                  : "Ex: C:\\Sistemas\\ERP  (path no servidor remoto)"
                              }
                              disabled={loading}
                              className={inputClass}
                              autoFocus
                            />
                          </div>
                          {database && (
                            <p className="text-[11px] text-muted-foreground">
                              Caminho completo:{" "}
                              <span className={`font-mono font-medium ${!database.includes("\\") && !database.includes("/") ? "text-amber-500" : "text-emerald-500"}`}>
                                {database}
                              </span>
                            </p>
                          )}
                        </div>
                      )}

                      {!pickedFileName && firebirdScenario === "bundled" && (
                        <p className="text-[11px] text-muted-foreground">
                          Coloque o <span className="font-mono text-foreground/70">.fdb</span> em{" "}
                          <span className="font-mono text-foreground">C:\Shift\Data</span>{" "}
                          (Windows) ou{" "}
                          <span className="font-mono text-foreground">/opt/shift/data</span>{" "}
                          (Linux) e informe o caminho absoluto.
                        </p>
                      )}

                      {!pickedFileName && firebirdScenario !== "bundled" && (
                        <p className="text-[11px] text-muted-foreground">
                          Informe o <span className="font-medium text-foreground">caminho absoluto</span> conforme o servidor remoto enxerga
                          (ex: <span className="font-mono text-foreground/70">C:\Sistemas\ERP\EMPRESA.FDB</span>).
                        </p>
                      )}

                      {!pickedFileName && database.trim() && !database.includes("\\") && !database.includes("/") && (
                        <p className="text-[11px] text-amber-500">
                          ⚠ Parece que está faltando o diretório. Informe o caminho completo (ex:{" "}
                          <span className="font-mono">D:\Data\{database.trim()}</span>).
                        </p>
                      )}
                    </div>
                  </>
                )}
              </div>
            )}

            {/* ── Host + Porta (não-Firebird) ── */}
            {!isFirebird && (
              <div className="grid grid-cols-[1fr_100px] gap-3">
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">Host *</label>
                  <input
                    type="text"
                    value={host}
                    onChange={(e) => setHost(e.target.value)}
                    placeholder="Ex: db.empresa.com"
                    disabled={loading}
                    className={inputClass}
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">Porta *</label>
                  <input
                    type="number"
                    value={port}
                    onChange={(e) => setPort(Number(e.target.value))}
                    min={1}
                    max={65535}
                    disabled={loading}
                    className={inputClass}
                  />
                </div>
              </div>
            )}

            {/* Banco de dados (não-Firebird — Firebird já mostra no bloco acima) */}
            {!isFirebird && (
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">
                  {databaseLabel} *
                </label>
                <input
                  type="text"
                  value={database}
                  onChange={(e) => setDatabase(e.target.value)}
                  placeholder={databasePlaceholder}
                  disabled={loading}
                  className={inputClass}
                />
              </div>
            )}

            {/* Schemas adicionais — útil para Oracle com múltiplos schemas */}
            {!isFirebird && (
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">
                  Schemas adicionais
                </label>
                <input
                  type="text"
                  value={includeSchemasRaw}
                  onChange={(e) => setIncludeSchemasRaw(e.target.value)}
                  placeholder="Ex: VIASOFTBASE, VIASOFTCTB"
                  disabled={loading}
                  className={inputClass}
                />
                <p className="text-[11px] italic text-muted-foreground">
                  Separe por vírgula. As tabelas aparecerão como{" "}
                  <span className="font-mono">SCHEMA.TABELA</span> no catálogo. Útil para Oracle.
                </p>
              </div>
            )}
            </div>
            {/* ── /SEÇÃO Como conectar ─────────────────────────────────── */}

            </div>
            {/* ╚═ /COLUNA 2 ════════════════════════════════════════════ */}

            </div>
            {/* /grid 2-cols */}

            {/* Erro de validação do form (não é erro de teste) */}
            {error && (
              <p className="mt-5 rounded-md border border-destructive/20 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
                {error}
              </p>
            )}

            {/* Resultado do teste de conexão */}
            {(diagnosticSteps.length > 0 || testing) && (
              <div className="mt-5 space-y-2 border-t border-border pt-4">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
                  Resultado do teste
                </p>
                <DiagnosticPanel steps={diagnosticSteps} running={testing} />
                {isFirebird && (() => {
                  const failure = diagnosticSteps.find((s) => !s.ok)
                  if (!failure) return null
                  const hint = scenarioContextualHint(firebirdScenario, failure.error_class, database)
                  if (!hint) return null
                  return (
                    <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[12px] text-amber-700 dark:text-amber-400">
                      <span className="font-medium">Dica para este cenário: </span>
                      {hint}
                    </div>
                  )
                })()}
              </div>
            )}

          </div>

          {/* Footer fixo */}
          <div className="flex items-center justify-between gap-2 border-t border-border px-5 py-3">
            <button
              type="button"
              onClick={() => void handleTest()}
              disabled={!canTest}
              title={
                canTest
                  ? "Testar conexão"
                  : "Preencha host, banco, usuário e senha para testar"
              }
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-3 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
            >
              {testing ? <MorphLoader className="size-3.5" /> : <Play className="size-3.5" />}
              Testar conexão
            </button>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onOpenChange(false)}
                disabled={loading}
                className="h-8 rounded-md px-4 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={loading}
                className="inline-flex h-8 items-center gap-1.5 rounded-md bg-foreground px-4 text-sm font-semibold text-background transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {loading && <MorphLoader className="size-3.5" />}
                {isEditing ? "Salvar" : "Criar"}
              </button>
            </div>
          </div>
        </form>
      </div>

    </div>
  )
}
