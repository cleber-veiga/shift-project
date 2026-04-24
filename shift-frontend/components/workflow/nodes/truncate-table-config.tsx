"use client"

import { useEffect, useState } from "react"
import { AlertTriangle, ChevronDown, Database, Loader2, Search } from "lucide-react"
import { cn } from "@/lib/utils"
import { useDashboard } from "@/lib/context/dashboard-context"
import {
  listWorkspaceConnections,
  getConnectionSchema,
  type Connection,
  type SchemaTable,
} from "@/lib/auth"
import { ConnectionField } from "@/components/workflow/connection-field"

// ── DB labels (reused pattern) ───────────────────────────────────────────────

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

interface TruncateTableConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

// ── Component ────────────────────────────────────────────────────────────────

export function TruncateTableConfig({ data, onUpdate }: TruncateTableConfigProps) {
  const { selectedWorkspace } = useDashboard()

  // Connections
  const [connections, setConnections] = useState<Connection[]>([])
  const [connectionsLoading, setConnectionsLoading] = useState(false)
  const [showConnectionPicker, setShowConnectionPicker] = useState(false)
  const [connectionSearch, setConnectionSearch] = useState("")

  // Tables
  const [tables, setTables] = useState<SchemaTable[]>([])
  const [tablesLoading, setTablesLoading] = useState(false)
  const [showTablePicker, setShowTablePicker] = useState(false)
  const [tableSearch, setTableSearch] = useState("")

  const selectedConnectionId = (data.connection_id as string) ?? ""
  const selectedConnection = connections.find((c) => c.id === selectedConnectionId) ?? null
  const selectedTable = (data.target_table as string) ?? ""
  const mode = (data.mode as string) ?? "truncate"
  const whereClause = (data.where_clause as string) ?? ""

  // Load connections
  useEffect(() => {
    if (!selectedWorkspace?.id) return
    setConnectionsLoading(true)
    listWorkspaceConnections(selectedWorkspace.id, { size: 200 })
      .then((r) => setConnections(r.items))
      .catch(() => setConnections([]))
      .finally(() => setConnectionsLoading(false))
  }, [selectedWorkspace?.id])

  // Load tables when connection changes
  useEffect(() => {
    if (!selectedConnectionId) { setTables([]); return }
    setTablesLoading(true)
    getConnectionSchema(selectedConnectionId)
      .then((schema) => setTables(schema.tables ?? []))
      .catch(() => setTables([]))
      .finally(() => setTablesLoading(false))
  }, [selectedConnectionId])

  function selectConnection(conn: Connection) {
    onUpdate({
      ...data,
      connection_id: conn.id,
      connection_name: conn.name,
      target_table: "",
      label: `Limpar: ${conn.name}`,
    })
    setShowConnectionPicker(false)
    setConnectionSearch("")
  }

  function selectTable(tableName: string) {
    onUpdate({ ...data, target_table: tableName })
    setShowTablePicker(false)
    setTableSearch("")
  }

  const filteredConnections = connectionSearch
    ? connections.filter(
        (c) =>
          c.name.toLowerCase().includes(connectionSearch.toLowerCase()) ||
          c.type.toLowerCase().includes(connectionSearch.toLowerCase()),
      )
    : connections

  const filteredTables = tableSearch
    ? tables.filter((t) => t.name.toLowerCase().includes(tableSearch.toLowerCase()))
    : tables

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
            onClick={() => setShowConnectionPicker(!showConnectionPicker)}
            className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 text-xs transition-colors hover:bg-muted/50"
          >
            {connectionsLoading ? (
              <span className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" /> Carregando...
              </span>
            ) : selectedConnection ? (
              <span className="flex items-center gap-2">
                <span className={cn("rounded px-1.5 py-0.5 text-[9px] font-bold uppercase", DB_COLORS[selectedConnection.type] ?? "text-muted-foreground bg-muted")}>
                  {(DB_LABELS[selectedConnection.type] ?? selectedConnection.type).slice(0, 2)}
                </span>
                <span className="font-medium text-foreground">{selectedConnection.name}</span>
                {selectedConnection.host && (
                  <span className="text-muted-foreground">{selectedConnection.host}{selectedConnection.port ? `:${selectedConnection.port}` : ""}</span>
                )}
              </span>
            ) : (
              <span className="text-muted-foreground">Selecionar conexão...</span>
            )}
            <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
          </button>

          {showConnectionPicker && (
            <div className="absolute left-0 top-full z-30 mt-1 max-h-[200px] w-full overflow-y-auto rounded-md border border-border bg-popover shadow-lg">
              <div className="sticky top-0 border-b border-border bg-popover p-1.5">
                <div className="flex items-center gap-1.5 rounded-md border border-input bg-background px-2">
                  <Search className="size-3 text-muted-foreground" />
                  <input
                    type="text"
                    value={connectionSearch}
                    onChange={(e) => setConnectionSearch(e.target.value)}
                    placeholder="Buscar conexão..."
                    className="h-7 flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
                    autoFocus
                  />
                </div>
              </div>
              {filteredConnections.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => selectConnection(c)}
                  className={cn(
                    "flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition-colors hover:bg-muted",
                    c.id === selectedConnectionId && "bg-accent",
                  )}
                >
                  <span className={cn("rounded px-1.5 py-0.5 text-[9px] font-bold uppercase", DB_COLORS[c.type] ?? "text-muted-foreground bg-muted")}>
                    {(DB_LABELS[c.type] ?? c.type).slice(0, 2)}
                  </span>
                  <span className="font-medium">{c.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </ConnectionField>

      {/* ── Table selector ── */}
      {selectedConnectionId && (
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Tabela
          </label>
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowTablePicker(!showTablePicker)}
              className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 text-xs transition-colors hover:bg-muted/50"
            >
              {tablesLoading ? (
                <span className="flex items-center gap-2 text-muted-foreground">
                  <Loader2 className="size-3.5 animate-spin" /> Carregando tabelas...
                </span>
              ) : selectedTable ? (
                <span className="flex items-center gap-2">
                  <Database className="size-3 text-muted-foreground" />
                  <span className="font-medium text-foreground">{selectedTable}</span>
                </span>
              ) : (
                <span className="text-muted-foreground">Selecionar tabela...</span>
              )}
              <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
            </button>

            {showTablePicker && (
              <div className="absolute left-0 top-full z-30 mt-1 max-h-[200px] w-full overflow-y-auto rounded-md border border-border bg-popover shadow-lg">
                <div className="sticky top-0 border-b border-border bg-popover p-1.5">
                  <div className="flex items-center gap-1.5 rounded-md border border-input bg-background px-2">
                    <Search className="size-3 text-muted-foreground" />
                    <input
                      type="text"
                      value={tableSearch}
                      onChange={(e) => setTableSearch(e.target.value)}
                      placeholder="Buscar tabela..."
                      className="h-7 flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
                      autoFocus
                    />
                  </div>
                </div>
                {filteredTables.map((t) => {
                  const qualifiedName = t.schema ? `${t.schema}.${t.name}` : t.name
                  return (
                  <button
                    key={qualifiedName}
                    type="button"
                    onClick={() => selectTable(qualifiedName)}
                    className={cn(
                      "flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition-colors hover:bg-muted",
                      selectedTable === qualifiedName && "bg-accent",
                    )}
                  >
                    <Database className="size-3 text-muted-foreground" />
                    <span>{t.schema ? `${t.schema}.${t.name}` : t.name}</span>
                    <span className="ml-auto text-[10px] text-muted-foreground">{t.columns.length} cols</span>
                  </button>
                  )
                })}
                {!tablesLoading && filteredTables.length === 0 && (
                  <p className="px-3 py-2 text-[10px] text-muted-foreground">Nenhuma tabela encontrada.</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Mode selector ── */}
      {selectedTable && (
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Modo
          </label>
          <div className="flex gap-1">
            <button
              type="button"
              onClick={() => onUpdate({ ...data, mode: "truncate" })}
              className={cn(
                "flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                mode === "truncate"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:text-foreground",
              )}
            >
              TRUNCATE
            </button>
            <button
              type="button"
              onClick={() => onUpdate({ ...data, mode: "delete" })}
              className={cn(
                "flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                mode === "delete"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:text-foreground",
              )}
            >
              DELETE
            </button>
          </div>
          <p className="text-[10px] text-muted-foreground">
            {mode === "truncate"
              ? "Remove todos os registros de forma rápida (sem log individual)."
              : "Remove registros com possibilidade de filtro WHERE."}
          </p>
        </div>
      )}

      {/* ── WHERE clause (delete mode only) ── */}
      {selectedTable && mode === "delete" && (
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            WHERE <span className="normal-case font-normal">(opcional)</span>
          </label>
          <input
            type="text"
            value={whereClause}
            onChange={(e) => onUpdate({ ...data, where_clause: e.target.value })}
            placeholder="ex: ORIGEM = 'MIGRAÇÃO'"
            className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
          />
          <p className="text-[10px] text-muted-foreground">
            Deixe vazio para apagar todos os registros.
          </p>
        </div>
      )}

      {/* ── Warning ── */}
      {selectedTable && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-500" />
          <div>
            <p className="text-xs font-medium text-amber-600 dark:text-amber-400">Atenção</p>
            <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
              {mode === "truncate"
                ? `Todos os registros da tabela "${selectedTable}" serão removidos permanentemente.`
                : whereClause
                  ? `Registros onde ${whereClause} serão removidos da tabela "${selectedTable}".`
                  : `Todos os registros da tabela "${selectedTable}" serão removidos.`}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
