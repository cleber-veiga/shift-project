"use client"

import { useCallback, useEffect, useState } from "react"
import { ChevronDown, Database, ExternalLink, FileSearch, Plug2, Search, Trash2, Zap } from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import { cn } from "@/lib/utils"
import { useDashboard } from "@/lib/context/dashboard-context"
import {
  listWorkspaceConnections,
  listSavedQueries,
  type Connection,
  type SavedQuery,
} from "@/lib/auth"
import { ConnectionField } from "@/components/workflow/connection-field"
import { deleteExtractCache } from "@/lib/api/executions"

// ── Database type labels ─────────────────────────────────────────────────────

const DB_LABELS: Record<string, string> = {
  oracle: "Oracle",
  postgresql: "PostgreSQL",
  firebird: "Firebird",
  sqlserver: "SQL Server",
  mysql: "MySQL",
}

const DB_COLORS: Record<string, string> = {
  oracle: "text-red-500 bg-red-500/10",
  postgresql: "text-blue-500 bg-blue-500/10",
  firebird: "text-orange-500 bg-orange-500/10",
  sqlserver: "text-indigo-500 bg-indigo-500/10",
  mysql: "text-cyan-500 bg-cyan-500/10",
}

// ── Props ────────────────────────────────────────────────────────────────────

interface SqlDatabaseConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

// ── Component ────────────────────────────────────────────────────────────────

export function SqlDatabaseConfig({ data, onUpdate }: SqlDatabaseConfigProps) {
  const { selectedWorkspace } = useDashboard()

  // Connections
  const [connections, setConnections] = useState<Connection[]>([])
  const [connectionsLoading, setConnectionsLoading] = useState(false)
  const [showConnectionPicker, setShowConnectionPicker] = useState(false)
  const [connectionSearch, setConnectionSearch] = useState("")

  // Saved queries
  const [savedQueries, setSavedQueries] = useState<SavedQuery[]>([])
  const [queriesLoading, setQueriesLoading] = useState(false)
  const [showQueryPicker, setShowQueryPicker] = useState(false)
  const [querySearch, setQuerySearch] = useState("")

  // SQL mode: "custom" or "saved"
  const [sqlMode, setSqlMode] = useState<"custom" | "saved">(
    (data.saved_query_id as string) ? "saved" : "custom"
  )

  const selectedConnectionId = (data.connection_id as string) ?? ""
  const selectedConnection = connections.find((c) => c.id === selectedConnectionId) ?? null
  const selectedQueryId = (data.saved_query_id as string) ?? ""
  const selectedQuery = savedQueries.find((q) => q.id === selectedQueryId) ?? null

  // Load connections
  useEffect(() => {
    if (!selectedWorkspace?.id) return
    setConnectionsLoading(true)
    listWorkspaceConnections(selectedWorkspace.id, { size: 200 })
      .then((r) => setConnections(r.items))
      .catch(() => setConnections([]))
      .finally(() => setConnectionsLoading(false))
  }, [selectedWorkspace?.id])

  // Load saved queries when connection changes
  useEffect(() => {
    if (!selectedConnectionId) {
      setSavedQueries([])
      return
    }
    setQueriesLoading(true)
    listSavedQueries(selectedConnectionId, { size: 200 })
      .then((r) => setSavedQueries(r.items))
      .catch(() => setSavedQueries([]))
      .finally(() => setQueriesLoading(false))
  }, [selectedConnectionId])

  function selectConnection(conn: Connection) {
    onUpdate({
      ...data,
      connection_id: conn.id,
      connection_name: conn.name,
      saved_query_id: undefined,
      query: "",
      label: `SQL: ${conn.name}`,
    })
    setShowConnectionPicker(false)
    setConnectionSearch("")
    setSqlMode("custom")
  }

  function selectSavedQuery(sq: SavedQuery) {
    onUpdate({
      ...data,
      saved_query_id: sq.id,
      query: sq.query,
      label: `SQL: ${sq.name}`,
    })
    setShowQueryPicker(false)
    setQuerySearch("")
  }

  const filteredConnections = connectionSearch.trim()
    ? connections.filter(
        (c) =>
          c.name.toLowerCase().includes(connectionSearch.toLowerCase()) ||
          c.type.toLowerCase().includes(connectionSearch.toLowerCase()) ||
          (c.host ?? "").toLowerCase().includes(connectionSearch.toLowerCase())
      )
    : connections

  const filteredQueries = querySearch.trim()
    ? savedQueries.filter(
        (q) =>
          q.name.toLowerCase().includes(querySearch.toLowerCase()) ||
          (q.description ?? "").toLowerCase().includes(querySearch.toLowerCase())
      )
    : savedQueries

  return (
    <div className="space-y-4">
      {/* ── Connection selector ── */}
      <ConnectionField
        value={(data.connection_id as string) ?? ""}
        onChange={(v) => onUpdate({ ...data, connection_id: v, connection_name: v.startsWith("{{") ? v : data.connection_name })}
        label="Conexão"
      >
        <div className="relative">
          <button
            type="button"
            onClick={() => setShowConnectionPicker((v) => !v)}
            className={cn(
              "flex h-9 w-full items-center gap-2 rounded-md border px-2.5 text-left text-xs transition-colors",
              selectedConnection
                ? "border-input bg-background text-foreground"
                : "border-dashed border-border bg-muted/20 text-muted-foreground"
            )}
          >
            {connectionsLoading ? (
              <MorphLoader className="size-3.5" />
            ) : selectedConnection ? (
              <>
                <div className={cn("flex size-5 shrink-0 items-center justify-center rounded text-[9px] font-bold", DB_COLORS[selectedConnection.type] ?? "bg-muted text-muted-foreground")}>
                  {selectedConnection.type.slice(0, 2).toUpperCase()}
                </div>
                <span className="truncate font-medium">{selectedConnection.name}</span>
                <span className="ml-auto text-[10px] text-muted-foreground">{selectedConnection.host}:{selectedConnection.port}</span>
              </>
            ) : (
              <>
                <Plug2 className="size-3.5" />
                <span>Selecionar conexão...</span>
              </>
            )}
            <ChevronDown className={cn("ml-auto size-3 shrink-0 transition-transform", showConnectionPicker && "rotate-180")} />
          </button>

          {/* Connection dropdown */}
          {showConnectionPicker && (
            <div className="absolute left-0 right-0 top-10 z-30 max-h-64 overflow-hidden rounded-lg border border-border bg-card shadow-lg">
              <div className="border-b border-border p-2">
                <label className="flex h-7 items-center gap-1.5 rounded-md border border-input bg-background px-2">
                  <Search className="size-3 text-muted-foreground" />
                  <input
                    autoFocus
                    type="text"
                    value={connectionSearch}
                    onChange={(e) => setConnectionSearch(e.target.value)}
                    placeholder="Buscar conexão..."
                    className="w-full bg-transparent text-[11px] text-foreground outline-none placeholder:text-muted-foreground"
                  />
                </label>
              </div>
              <div className="max-h-48 overflow-y-auto p-1">
                {filteredConnections.length === 0 ? (
                  <p className="px-2 py-3 text-center text-[11px] text-muted-foreground">Nenhuma conexão encontrada</p>
                ) : (
                  filteredConnections.map((conn) => (
                    <button
                      key={conn.id}
                      type="button"
                      onClick={() => selectConnection(conn)}
                      className={cn(
                        "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-muted/60",
                        conn.id === selectedConnectionId && "bg-primary/5"
                      )}
                    >
                      <div className={cn("flex size-6 shrink-0 items-center justify-center rounded text-[9px] font-bold", DB_COLORS[conn.type] ?? "bg-muted text-muted-foreground")}>
                        {conn.type.slice(0, 2).toUpperCase()}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium text-foreground">{conn.name}</p>
                        <p className="truncate text-[10px] text-muted-foreground">
                          {DB_LABELS[conn.type] ?? conn.type} - {conn.host}:{conn.port}/{conn.database}
                        </p>
                      </div>
                    </button>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      </ConnectionField>

      {/* ── SQL section (only when connection is selected) ── */}
      {selectedConnectionId && (
        <>
          {/* Mode toggle */}
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Consulta SQL
            </label>
            <div className="flex rounded-md border border-border bg-background p-0.5">
              <button
                type="button"
                onClick={() => setSqlMode("custom")}
                className={cn(
                  "flex-1 rounded px-2 py-1 text-[11px] font-medium transition-colors",
                  sqlMode === "custom" ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground"
                )}
              >
                SQL Personalizado
              </button>
              <button
                type="button"
                onClick={() => setSqlMode("saved")}
                className={cn(
                  "flex-1 rounded px-2 py-1 text-[11px] font-medium transition-colors",
                  sqlMode === "saved" ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground"
                )}
              >
                Queries Salvas {savedQueries.length > 0 && `(${savedQueries.length})`}
              </button>
            </div>
          </div>

          {sqlMode === "custom" ? (
            /* Custom SQL textarea */
            <div className="space-y-1.5">
              <textarea
                value={(data.query as string) ?? ""}
                onChange={(e) => onUpdate({ ...data, query: e.target.value, saved_query_id: undefined })}
                placeholder="SELECT * FROM tabela WHERE ..."
                rows={6}
                className="w-full rounded-md border border-input bg-background px-2.5 py-2 font-mono text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
              />
            </div>
          ) : (
            /* Saved query picker */
            <div className="space-y-2">
              {queriesLoading ? (
                <div className="flex h-16 items-center justify-center gap-2 text-[11px] text-muted-foreground">
                  <MorphLoader className="size-3.5" />
                  Carregando queries...
                </div>
              ) : savedQueries.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border bg-muted/20 p-3 text-center">
                  <FileSearch className="mx-auto size-5 text-muted-foreground/50" />
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    Nenhuma query salva para esta conexão.
                  </p>
                  <p className="text-[10px] text-muted-foreground/70">
                    Use o Playground para salvar queries reutilizáveis.
                  </p>
                </div>
              ) : (
                <>
                  {/* Search saved queries */}
                  {savedQueries.length > 3 && (
                    <label className="flex h-7 items-center gap-1.5 rounded-md border border-input bg-background px-2">
                      <Search className="size-3 text-muted-foreground" />
                      <input
                        type="text"
                        value={querySearch}
                        onChange={(e) => setQuerySearch(e.target.value)}
                        placeholder="Buscar query..."
                        className="w-full bg-transparent text-[11px] text-foreground outline-none placeholder:text-muted-foreground"
                      />
                    </label>
                  )}

                  <div className="max-h-48 space-y-1 overflow-y-auto">
                    {filteredQueries.map((sq) => {
                      const isSelected = sq.id === selectedQueryId
                      return (
                        <button
                          key={sq.id}
                          type="button"
                          onClick={() => selectSavedQuery(sq)}
                          className={cn(
                            "flex w-full flex-col gap-0.5 rounded-md border-2 px-2.5 py-2 text-left transition-all",
                            isSelected
                              ? "border-primary bg-primary/5"
                              : "border-transparent bg-background hover:border-border hover:bg-muted/30"
                          )}
                        >
                          <p className="text-xs font-medium text-foreground">{sq.name}</p>
                          {sq.description && (
                            <p className="text-[10px] text-muted-foreground">{sq.description}</p>
                          )}
                          <pre className="mt-1 max-h-12 overflow-hidden truncate rounded bg-muted/50 px-1.5 py-1 font-mono text-[10px] text-muted-foreground">
                            {sq.query.slice(0, 120)}{sq.query.length > 120 ? "..." : ""}
                          </pre>
                        </button>
                      )
                    })}
                  </div>
                </>
              )}

              {/* Show active query in readonly editor */}
              {selectedQuery && (
                <div className="space-y-1">
                  <label className="text-[10px] font-medium text-muted-foreground">SQL da query selecionada:</label>
                  <textarea
                    readOnly
                    value={selectedQuery.query}
                    rows={4}
                    className="w-full rounded-md border border-input bg-muted/30 px-2.5 py-2 font-mono text-xs text-foreground/80 outline-none"
                  />
                </div>
              )}
            </div>
          )}

          {/* Chunk size */}
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Chunk Size
            </label>
            <input
              type="number"
              value={String((data.chunk_size as number) ?? 1000)}
              onChange={(e) => onUpdate({ ...data, chunk_size: Number(e.target.value) })}
              placeholder="1000"
              className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
            />
          </div>

          {/* Max rows */}
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Max Rows{" "}
              <span className="normal-case font-normal text-muted-foreground/60">(vazio = sem limite)</span>
            </label>
            <input
              type="number"
              value={(data.max_rows as number) ?? ""}
              onChange={(e) => onUpdate({ ...data, max_rows: e.target.value ? Number(e.target.value) : null })}
              placeholder="Sem limite"
              className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
            />
          </div>

          {/* ── Cache de extração (Sprint 4.4) ── */}
          <CacheSection nodeType="sql_database" data={data} onUpdate={onUpdate} />
        </>
      )}
    </div>
  )
}

// ── Cache section — reutilizavel por qualquer no de extracao ─────────────────

export interface CacheSectionProps {
  nodeType: string
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

export function CacheSection({ nodeType, data, onUpdate }: CacheSectionProps) {
  const cacheEnabled = Boolean(data.cache_enabled)
  const ttl = (data.cache_ttl_seconds as number) ?? 300
  const [clearing, setClearing] = useState(false)
  const [clearMsg, setClearMsg] = useState<string | null>(null)

  const handleClearCache = async () => {
    setClearing(true)
    setClearMsg(null)
    try {
      // cache_key so e conhecido em runtime; invalida todas entradas do node_type
      const res = await deleteExtractCache({ nodeType })
      setClearMsg(`${res.deleted} entrada(s) removida(s).`)
    } catch {
      setClearMsg("Falha ao limpar cache.")
    } finally {
      setClearing(false)
    }
  }

  return (
    <div className="space-y-2 rounded-md border border-border bg-muted/20 p-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Zap className="size-3.5 text-emerald-500" />
          <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Cache de Extração
          </span>
        </div>
        {/* Toggle */}
        <button
          type="button"
          role="switch"
          aria-checked={cacheEnabled}
          onClick={() => onUpdate({ ...data, cache_enabled: !cacheEnabled })}
          className={cn(
            "relative inline-flex h-4 w-8 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors",
            cacheEnabled ? "bg-emerald-500" : "bg-muted-foreground/30",
          )}
        >
          <span
            className={cn(
              "pointer-events-none inline-block size-3 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out",
              cacheEnabled ? "translate-x-4" : "translate-x-0",
            )}
          />
        </button>
      </div>

      {cacheEnabled && (
        <>
          <p className="text-[10px] text-muted-foreground">
            Quando ativo, o resultado desta extração é reutilizado por execuções posteriores
            enquanto a configuração do nó não mudar e o TTL não expirar.
          </p>

          <div className="space-y-1">
            <label className="text-[11px] font-medium text-muted-foreground">
              TTL (segundos)
            </label>
            <input
              type="number"
              min={10}
              value={ttl}
              onChange={(e) => onUpdate({ ...data, cache_ttl_seconds: Number(e.target.value) || 300 })}
              className="h-7 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleClearCache}
              disabled={clearing}
              className="flex items-center gap-1 rounded border border-border bg-card px-2 py-1 text-[11px] text-red-600 hover:bg-red-500/10 disabled:opacity-60"
            >
              <Trash2 className="size-3" />
              {clearing ? "Limpando…" : "Limpar cache do nó"}
            </button>
            {clearMsg && (
              <span className="text-[11px] text-muted-foreground">{clearMsg}</span>
            )}
          </div>
        </>
      )}
    </div>
  )
}
