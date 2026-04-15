"use client"

import { useEffect, useMemo, useState } from "react"
import { ArrowRight, ChevronDown, Database, Loader2, Search, Sparkles, Trash2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { useDashboard } from "@/lib/context/dashboard-context"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"
import {
  listWorkspaceConnections,
  getConnectionSchema,
  type Connection,
  type SchemaTable,
} from "@/lib/auth"

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

// ── Types ────────────────────────────────────────────────────────────────────

interface ColumnMap {
  source: string   // upstream column name
  target: string   // destination table column name
}

interface BulkInsertConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

// ── Component ────────────────────────────────────────────────────────────────

export function BulkInsertConfig({ data, onUpdate }: BulkInsertConfigProps) {
  const { selectedWorkspace } = useDashboard()
  const upstreamFields = useUpstreamFields()

  // Connections
  const [connections, setConnections] = useState<Connection[]>([])
  const [connectionsLoading, setConnectionsLoading] = useState(false)
  const [showConnectionPicker, setShowConnectionPicker] = useState(false)
  const [connectionSearch, setConnectionSearch] = useState("")

  // Tables + schema
  const [tables, setTables] = useState<SchemaTable[]>([])
  const [tablesLoading, setTablesLoading] = useState(false)
  const [showTablePicker, setShowTablePicker] = useState(false)
  const [tableSearch, setTableSearch] = useState("")

  const selectedConnectionId = (data.connection_id as string) ?? ""
  const selectedConnection = connections.find((c) => c.id === selectedConnectionId) ?? null
  const selectedTableName = (data.target_table as string) ?? ""
  const batchSize = (data.batch_size as number) ?? 1000
  const columnMapping: ColumnMap[] = Array.isArray(data.column_mapping)
    ? (data.column_mapping as ColumnMap[])
    : []

  // Get columns for selected table
  const targetColumns = useMemo(() => {
    if (!selectedTableName) return []
    const table = tables.find(
      (t) => (t.schema ? `${t.schema}.${t.name}` : t.name) === selectedTableName || t.name === selectedTableName,
    )
    return table?.columns?.map((c) => c.name) ?? []
  }, [tables, selectedTableName])

  // Load connections
  useEffect(() => {
    if (!selectedWorkspace?.id) return
    setConnectionsLoading(true)
    listWorkspaceConnections(selectedWorkspace.id)
      .then(setConnections)
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
      column_mapping: [],
      label: `Insert: ${conn.name}`,
    })
    setShowConnectionPicker(false)
    setConnectionSearch("")
  }

  function selectTable(tableName: string) {
    onUpdate({ ...data, target_table: tableName, column_mapping: [] })
    setShowTablePicker(false)
    setTableSearch("")
  }

  function setMapping(next: ColumnMap[]) {
    onUpdate({ ...data, column_mapping: next })
  }

  function updateMappingTarget(index: number, target: string) {
    const next = columnMapping.map((m, i) => (i === index ? { ...m, target } : m))
    setMapping(next)
  }

  function removeMapping(index: number) {
    setMapping(columnMapping.filter((_, i) => i !== index))
  }

  function addMapping() {
    setMapping([...columnMapping, { source: "", target: "" }])
  }

  function autoMap() {
    // Match upstream fields to target columns by exact name (case-insensitive)
    const targetSet = new Set(targetColumns.map((c) => c.toLowerCase()))
    const mapped = new Set(columnMapping.map((m) => m.source.toLowerCase()))
    const newMaps: ColumnMap[] = [...columnMapping]

    for (const src of upstreamFields) {
      if (mapped.has(src.toLowerCase())) continue
      const match = targetColumns.find((t) => t.toLowerCase() === src.toLowerCase())
      if (match) {
        newMaps.push({ source: src, target: match })
        mapped.add(src.toLowerCase())
      }
    }

    // Also add unmapped upstream fields that have target columns with similar names
    if (newMaps.length === columnMapping.length) {
      // No exact matches found — add all upstream as blank-target for manual mapping
      for (const src of upstreamFields) {
        if (!mapped.has(src.toLowerCase())) {
          newMaps.push({ source: src, target: "" })
        }
      }
    }

    setMapping(newMaps)
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

  const usedTargets = new Set(columnMapping.map((m) => m.target))
  const usedSources = new Set(columnMapping.map((m) => m.source))

  return (
    <div className="space-y-4">

      {/* ── Connection selector ── */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Conexão
        </label>
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
      </div>

      {/* ── Table selector ── */}
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
                  <Loader2 className="size-3.5 animate-spin" /> Carregando tabelas...
                </span>
              ) : selectedTableName ? (
                <span className="flex items-center gap-2">
                  <Database className="size-3 text-muted-foreground" />
                  <span className="font-medium text-foreground">{selectedTableName}</span>
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
                {filteredTables.map((t) => (
                  <button
                    key={t.name}
                    type="button"
                    onClick={() => selectTable(t.schema ? `${t.schema}.${t.name}` : t.name)}
                    className={cn(
                      "flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition-colors hover:bg-muted",
                      selectedTableName === (t.schema ? `${t.schema}.${t.name}` : t.name) && "bg-accent",
                    )}
                  >
                    <Database className="size-3 text-muted-foreground" />
                    <span>{t.schema ? `${t.schema}.${t.name}` : t.name}</span>
                    <span className="ml-auto text-[10px] text-muted-foreground">{t.columns.length} cols</span>
                  </button>
                ))}
                {!tablesLoading && filteredTables.length === 0 && (
                  <p className="px-3 py-2 text-[10px] text-muted-foreground">Nenhuma tabela encontrada.</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Column mapping ── */}
      {selectedTableName && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Mapeamento de colunas
            </label>
            <button
              type="button"
              onClick={autoMap}
              className="flex items-center gap-1 text-[10px] font-medium text-primary transition-colors hover:text-primary/80"
            >
              <Sparkles className="size-3" />
              Auto mapear
            </button>
          </div>

          {/* Header */}
          <div className="flex items-center gap-2 px-1 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/60">
            <span className="flex-1">Origem (upstream)</span>
            <span className="w-5" />
            <span className="flex-1">Destino (tabela)</span>
            <span className="w-7" />
          </div>

          {/* Rows */}
          <div className="space-y-1.5">
            {columnMapping.map((m, i) => (
              <div key={i} className="flex items-center gap-2">
                {/* Source select */}
                <select
                  value={m.source}
                  onChange={(e) => {
                    const next = columnMapping.map((mm, ii) =>
                      ii === i ? { ...mm, source: e.target.value } : mm,
                    )
                    setMapping(next)
                  }}
                  className={cn(
                    "h-7 flex-1 rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary",
                    m.source ? "text-foreground" : "text-muted-foreground",
                  )}
                >
                  <option value="">Selecionar...</option>
                  {upstreamFields.map((f, fi) => (
                    <option
                      key={`${f}-${fi}`}
                      value={f}
                      disabled={usedSources.has(f) && f !== m.source}
                    >
                      {f}
                    </option>
                  ))}
                </select>

                <ArrowRight className="size-3.5 shrink-0 text-muted-foreground/40" />

                {/* Target select */}
                <select
                  value={m.target}
                  onChange={(e) => updateMappingTarget(i, e.target.value)}
                  className={cn(
                    "h-7 flex-1 rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary",
                    m.target ? "text-foreground" : "text-muted-foreground",
                  )}
                >
                  <option value="">Selecionar...</option>
                  {targetColumns.map((c, ci) => (
                    <option
                      key={`${c}-${ci}`}
                      value={c}
                      disabled={usedTargets.has(c) && c !== m.target}
                    >
                      {c}
                    </option>
                  ))}
                </select>

                <button
                  type="button"
                  onClick={() => removeMapping(i)}
                  className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                >
                  <Trash2 className="size-3" />
                </button>
              </div>
            ))}
          </div>

          {/* Add mapping button */}
          <button
            type="button"
            onClick={addMapping}
            className="flex w-full items-center justify-center gap-1.5 rounded-md border-2 border-dashed border-border py-2 text-[11px] font-medium text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
          >
            + Adicionar coluna
          </button>
        </div>
      )}

      {/* ── Batch size ── */}
      {selectedTableName && (
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Batch size
          </label>
          <input
            type="number"
            value={batchSize}
            onChange={(e) => onUpdate({ ...data, batch_size: parseInt(e.target.value, 10) || 1000 })}
            min={1}
            max={10000}
            className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
          />
          <p className="text-[10px] text-muted-foreground">
            Número de registros por lote de INSERT.
          </p>
        </div>
      )}
    </div>
  )
}
