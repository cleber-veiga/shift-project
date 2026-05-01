"use client"

import { useEffect, useState } from "react"
import { ChevronDown, Database, Search } from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import { cn } from "@/lib/utils"
import { useDashboard } from "@/lib/context/dashboard-context"
import {
  listWorkspaceConnections,
  getConnectionSchema,
  type Connection,
  type SchemaTable,
} from "@/lib/auth"
import { ConnectionField } from "@/components/workflow/connection-field"

// ── DB labels ────────────────────────────────────────────────────────────────

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

type WriteDisposition = "append" | "replace" | "merge"

const WRITE_LABELS: Record<WriteDisposition, string> = {
  append: "Append",
  replace: "Replace",
  merge: "Merge",
}

const WRITE_DESCRIPTIONS: Record<WriteDisposition, string> = {
  append: "Insere os registros sem modificar os existentes",
  replace: "Remove todos os registros e reinsere (TRUNCATE + INSERT)",
  merge: "Atualiza existentes e insere novos com base em colunas-chave",
}

// ── Props ────────────────────────────────────────────────────────────────────

interface LoadNodeConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

// ── Component ────────────────────────────────────────────────────────────────

export function LoadNodeConfig({ data, onUpdate }: LoadNodeConfigProps) {
  const { selectedWorkspace } = useDashboard()

  const [connections, setConnections] = useState<Connection[]>([])
  const [connectionsLoading, setConnectionsLoading] = useState(false)
  const [showConnectionPicker, setShowConnectionPicker] = useState(false)
  const [connectionSearch, setConnectionSearch] = useState("")

  const [tables, setTables] = useState<SchemaTable[]>([])
  const [tablesLoading, setTablesLoading] = useState(false)
  const [showTablePicker, setShowTablePicker] = useState(false)
  const [tableSearch, setTableSearch] = useState("")

  const selectedConnectionId = (data.connection_id as string) ?? ""
  const selectedConnection = connections.find((c) => c.id === selectedConnectionId) ?? null
  const selectedTable = (data.target_table as string) ?? ""
  const writeDisposition = ((data.write_disposition as WriteDisposition) ?? "append")
  const mergeKeys: string[] = Array.isArray(data.merge_keys) ? (data.merge_keys as string[]) : []

  const allColumns = tables
    .find((t) => (t.schema ? `${t.schema}.${t.name}` : t.name) === selectedTable || t.name === selectedTable)
    ?.columns?.map((c) => c.name) ?? []

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
      merge_keys: [],
      label: `Destino SQL: ${conn.name}`,
    })
    setShowConnectionPicker(false)
    setConnectionSearch("")
  }

  function selectTable(tableName: string) {
    onUpdate({ ...data, target_table: tableName, merge_keys: [] })
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
    ? tables.filter((t) => {
        const qualified = t.schema ? `${t.schema}.${t.name}` : t.name
        return qualified.toLowerCase().includes(tableSearch.toLowerCase())
      })
    : tables

  return (
    <div className="space-y-4">

      {/* ── Conexão ── */}
      <ConnectionField
        value={selectedConnectionId}
        onChange={(v) =>
          onUpdate({ ...data, connection_id: v, connection_name: v.startsWith("{{") ? v : data.connection_name })
        }
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
                <MorphLoader className="size-3.5" /> Carregando...
              </span>
            ) : selectedConnection ? (
              <span className="flex items-center gap-2">
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[9px] font-bold uppercase",
                    DB_COLORS[selectedConnection.type] ?? "text-muted-foreground bg-muted",
                  )}
                >
                  {(DB_LABELS[selectedConnection.type] ?? selectedConnection.type).slice(0, 2)}
                </span>
                <span className="font-medium text-foreground">{selectedConnection.name}</span>
                {selectedConnection.host && (
                  <span className="text-muted-foreground">
                    {selectedConnection.host}
                    {selectedConnection.port ? `:${selectedConnection.port}` : ""}
                  </span>
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
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 text-[9px] font-bold uppercase",
                      DB_COLORS[c.type] ?? "text-muted-foreground bg-muted",
                    )}
                  >
                    {(DB_LABELS[c.type] ?? c.type).slice(0, 2)}
                  </span>
                  <span className="font-medium">{c.name}</span>
                </button>
              ))}
              {!connectionsLoading && filteredConnections.length === 0 && (
                <p className="px-3 py-2 text-[10px] text-muted-foreground">Nenhuma conexão encontrada.</p>
              )}
            </div>
          )}
        </div>
      </ConnectionField>

      {/* ── Tabela destino ── */}
      {selectedConnectionId && (
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Tabela destino
          </label>
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowTablePicker(!showTablePicker)}
              className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 text-xs transition-colors hover:bg-muted/50"
            >
              {tablesLoading ? (
                <span className="flex items-center gap-2 text-muted-foreground">
                  <MorphLoader className="size-3.5" /> Carregando tabelas...
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
                  const qualified = t.schema ? `${t.schema}.${t.name}` : t.name
                  return (
                    <button
                      key={qualified}
                      type="button"
                      onClick={() => selectTable(qualified)}
                      className={cn(
                        "flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition-colors hover:bg-muted",
                        selectedTable === qualified && "bg-accent",
                      )}
                    >
                      <Database className="size-3 text-muted-foreground" />
                      <span>{qualified}</span>
                      <span className="ml-auto text-[10px] text-muted-foreground">
                        {t.columns.length} cols
                      </span>
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

      {/* ── Modo de escrita ── */}
      {selectedTable && (
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Modo de escrita
          </label>
          <div className="grid grid-cols-3 gap-0.5 rounded-lg bg-muted p-0.5">
            {(["append", "replace", "merge"] as WriteDisposition[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => onUpdate({ ...data, write_disposition: m, merge_keys: [] })}
                className={cn(
                  "rounded-md py-1.5 text-[11px] font-semibold transition-all",
                  writeDisposition === m
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {WRITE_LABELS[m]}
              </button>
            ))}
          </div>
          <p className="text-[10px] text-muted-foreground">
            {WRITE_DESCRIPTIONS[writeDisposition]}
          </p>
        </div>
      )}

      {/* ── Merge keys (apenas no modo merge) ── */}
      {selectedTable && writeDisposition === "merge" && (
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Colunas-chave do merge
          </label>
          {allColumns.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {allColumns.map((col) => {
                const active = mergeKeys.includes(col)
                return (
                  <button
                    key={col}
                    type="button"
                    onClick={() => {
                      const next = active
                        ? mergeKeys.filter((k) => k !== col)
                        : [...mergeKeys, col]
                      onUpdate({ ...data, merge_keys: next })
                    }}
                    className={cn(
                      "inline-flex h-6 items-center gap-1 rounded-md border px-2 text-[10px] font-medium transition-colors",
                      active
                        ? "border-primary/30 bg-primary/10 text-primary"
                        : "border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                  >
                    {active && <span className="size-1.5 rounded-full bg-primary" />}
                    {col}
                  </button>
                )
              })}
            </div>
          ) : (
            <input
              type="text"
              value={mergeKeys.join(", ")}
              onChange={(e) =>
                onUpdate({
                  ...data,
                  merge_keys: e.target.value.split(",").map((k) => k.trim()).filter(Boolean),
                })
              }
              placeholder="id, codigo"
              className="h-8 w-full rounded-md border border-input bg-background px-2.5 font-mono text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
            />
          )}
          <p className="text-[10px] text-muted-foreground">
            {mergeKeys.length > 0
              ? `Registros com mesmo [${mergeKeys.join(", ")}] serão atualizados; demais, inseridos.`
              : "Selecione as colunas que identificam unicamente cada registro."}
          </p>
        </div>
      )}
    </div>
  )
}
