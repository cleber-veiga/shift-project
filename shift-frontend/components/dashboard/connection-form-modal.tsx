"use client"

import { useEffect, useRef, useState } from "react"
import { X, Play, Eye, EyeOff, Building2, FolderOpen } from "lucide-react"
import type {
  Connection,
  ConnectionType,
  CreateConnectionPayload,
  UpdateConnectionPayload,
  WorkspacePlayer,
  WorkspacePlayerDatabaseType,
} from "@/lib/auth"
import { testConnection, listWorkspacePlayers } from "@/lib/auth"
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

/** Mapeia o database_type do concorrente para o ConnectionType da conexão */
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
    return { host: "localhost", port: 3050, database }
  }

  const slashIdx = url.indexOf("/")
  if (slashIdx === -1) {
    const looksLikePath =
      /^[a-zA-Z]:[\\\/]/.test(url) || url.includes("\\") || url.includes("/")
    if (looksLikePath) return { host: "localhost", port: 3050, database: url }
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
  if (colonIdx === -1) return { host: hostPart, port: 3050, database }

  const portStr = hostPart.slice(colonIdx + 1)
  const port = parseInt(portStr, 10)
  if (isNaN(port) || port < 1 || port > 65535)
    return { host: "", port: 3050, database: "", error: `Porta inválida: ${portStr}` }

  return { host: hostPart.slice(0, colonIdx), port, database }
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

  // ── Concorrente (player) ──
  const [players, setPlayers] = useState<WorkspacePlayer[]>([])
  const [playersLoading, setPlayersLoading] = useState(false)
  const [selectedPlayerId, setSelectedPlayerId] = useState<string | null>(null)

  // ── Firebird: modo de entrada (só quando sem player) ──
  const [firebirdMode, setFirebirdMode] = useState<FirebirdMode>("fields")
  const [firebirdUrl, setFirebirdUrl] = useState("")
  const [urlParseError, setUrlParseError] = useState("")

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
    }
    setError("")
    setUrlParseError("")
    setShowPassword(false)
    setPickedFileName(null)
    setBuilderDir("")
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
    // Sugere o tipo de banco do concorrente (usuário pode alterar)
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
      }
    }
  }

  async function handleTest() {
    if (!connection) return
    setTesting(true)
    try {
      const result = await testConnection(connection.id)
      if (result.success) {
        toast.success("Conexão bem-sucedida", result.message)
      } else {
        toast.error("Falha na conexão", result.message)
      }
    } catch (err) {
      toast.error("Falha na conexão", err instanceof Error ? err.message : "Erro ao testar conexão.")
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
    ? "Ex: D:\\Data\\MYDB.FDB ou /opt/firebird/MYDB.FDB"
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
        className="flex w-[min(580px,96vw)] max-h-[90vh] flex-col rounded-2xl border border-border bg-card shadow-2xl"
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
          <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">

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

            {/* Concorrente */}
            <div className="space-y-1.5">
              <label className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                <Building2 className="size-3.5" />
                Concorrente
              </label>
              {playersLoading ? (
                <div className="flex h-9 items-center gap-2 rounded-md border border-input bg-background px-3 text-sm text-muted-foreground">
                  <MorphLoader className="size-3.5" />
                  Carregando concorrentes…
                </div>
              ) : (
                <Select
                  value={selectedPlayerId ?? "__none__"}
                  onValueChange={handlePlayerChange}
                  disabled={loading}
                >
                  <SelectTrigger className="w-full bg-background">
                    <SelectValue placeholder="Selecione um concorrente (opcional)" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">
                      <span className="text-muted-foreground">Sem concorrente</span>
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
                  Nenhum concorrente cadastrado no workspace. Cadastre em{" "}
                  <span className="font-medium">Configurações → Concorrentes</span>.
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

            {/* ── Firebird: toggle URL / Campos ── */}
            {isFirebird && (
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">
                    Modo de conexão
                  </label>
                  <div className="inline-flex w-full items-center rounded-md border border-border bg-background p-1">
                    <button
                      type="button"
                      onClick={() => handleFirebirdModeChange("fields")}
                      disabled={loading}
                      className={`flex-1 rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                        firebirdMode === "fields"
                          ? "bg-accent text-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      Por Campos (Host + Caminho)
                    </button>
                    <button
                      type="button"
                      onClick={() => handleFirebirdModeChange("url")}
                      disabled={loading}
                      className={`flex-1 rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                        firebirdMode === "url"
                          ? "bg-accent text-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      Por URL
                    </button>
                  </div>
                </div>

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
                          192.168.1.1:3050/D:\Data\MYDB.FDB
                        </span>{" "}
                        — remoto
                      </p>
                      <p>
                        <span className="font-mono text-foreground/70">
                          /opt/firebird/MYDB.FDB
                        </span>{" "}
                        — local (servidor)
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
                        <label className="text-xs font-medium text-muted-foreground">Host *</label>
                        <input
                          type="text"
                          value={host}
                          onChange={(e) => setHost(e.target.value)}
                          placeholder="Ex: 192.168.1.100 ou localhost"
                          disabled={loading}
                          className={inputClass}
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
                          className={inputClass}
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
                          placeholder="Ex: D:\Data\EMPRESA.FDB  ou  /opt/firebird/EMPRESA.FDB"
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
                              placeholder="Ex: D:\Firebird\Data  ou  /opt/firebird/databases"
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

                      {!pickedFileName && (
                        <p className="text-[11px] text-muted-foreground">
                          Informe o <span className="font-medium text-foreground">caminho absoluto</span> no servidor.
                          Windows: <span className="font-mono text-foreground/70">D:\Data\EMPRESA.FDB</span> —
                          Linux: <span className="font-mono text-foreground/70">/opt/firebird/EMPRESA.FDB</span>
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
                <p className="text-[11px] text-muted-foreground">
                  Separe por vírgula. As tabelas desses schemas aparecerão como{" "}
                  <span className="font-mono text-foreground/70">SCHEMA.TABELA</span> no catálogo.
                  Útil no Oracle quando o usuário conectado acessa tabelas de outros schemas.
                </p>
              </div>
            )}

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
                Senha {isEditing ? "(deixe em branco para manter)" : "*"}
              </label>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={isEditing ? "••••••••" : "Senha de acesso"}
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

            {/* Erro */}
            {error && (
              <p className="rounded-md border border-destructive/20 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
                {error}
              </p>
            )}

          </div>

          {/* Footer fixo */}
          <div className="flex items-center justify-between gap-2 border-t border-border px-5 py-3">
            {/* Testar (só no editar) */}
            {isEditing ? (
              <button
                type="button"
                onClick={() => void handleTest()}
                disabled={loading || testing}
                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-3 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
              >
                {testing ? <MorphLoader className="size-3.5" /> : <Play className="size-3.5" />}
                Testar conexão
              </button>
            ) : (
              <span />
            )}

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
