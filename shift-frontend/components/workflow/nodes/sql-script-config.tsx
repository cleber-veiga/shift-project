"use client"

import { useEffect, useMemo, useState } from "react"
import { ChevronDown, Loader2, Plus, Search, Trash2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { useDashboard } from "@/lib/context/dashboard-context"
import { useUpstreamFields, useUpstreamOutputs } from "@/lib/workflow/upstream-fields-context"
import { listWorkspaceConnections, type Connection } from "@/lib/auth"
import { ConnectionField } from "@/components/workflow/connection-field"
import { ValueInput } from "@/components/workflow/value-input"
import {
  type ParameterValue,
  type UpstreamField,
  createFixed,
  migrateLegacySqlParameter,
  isParameterValue,
} from "@/lib/workflow/parameter-value"

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

type ScriptMode = "query" | "execute" | "execute_many"

interface OutputColumn {
  name: string
  type: string
}

interface ParameterRow {
  name: string
  // For query/execute: a ParameterValue. For execute_many: mode="fixed", value=column name.
  value: ParameterValue
}

interface SqlScriptConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function parametersToRows(
  parameters: Record<string, unknown> | undefined,
): ParameterRow[] {
  if (!parameters) return []
  return Object.entries(parameters).map(([name, raw]) => ({
    name,
    value: migrateLegacySqlParameter(raw),
  }))
}

/**
 * Serialise rows back to the parameters dict.
 * - execute_many: write plain string (column name) for backend compatibility
 * - query/execute: write ParameterValue object (new format)
 */
function rowsToParameters(
  rows: ParameterRow[],
  mode: ScriptMode,
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const row of rows) {
    const key = row.name.trim()
    if (!key) continue
    if (mode === "execute_many") {
      // execute_many values are column name strings
      out[key] = row.value.mode === "fixed" ? row.value.value : ""
    } else {
      out[key] = row.value
    }
  }
  return out
}

// ── Component ─────────────────────────────────────────────────────────────────

export function SqlScriptConfig({ data, onUpdate }: SqlScriptConfigProps) {
  const { selectedWorkspace } = useDashboard()
  const upstreamColumnNames = useUpstreamFields()
  const upstreamOutputs = useUpstreamOutputs()

  const [connections, setConnections] = useState<Connection[]>([])
  const [connectionsLoading, setConnectionsLoading] = useState(false)
  const [showConnectionPicker, setShowConnectionPicker] = useState(false)
  const [connectionSearch, setConnectionSearch] = useState("")

  const selectedConnectionId = (data.connection_id as string) ?? ""
  const selectedConnection =
    connections.find((c) => c.id === selectedConnectionId) ?? null

  const script = (data.script as string) ?? ""
  const mode = ((data.mode as ScriptMode) ?? "query") as ScriptMode
  const outputField = (data.output_field as string) ?? "sql_result"
  const timeoutSeconds = (data.timeout_seconds as number) ?? 60

  const [parameters, setParametersState] = useState<ParameterRow[]>(() =>
    parametersToRows(data.parameters as Record<string, unknown> | undefined),
  )

  // Resync when the node data changes externally (import, undo, etc.)
  useEffect(() => {
    const externalRows = parametersToRows(
      data.parameters as Record<string, unknown> | undefined,
    )
    const localPersisted = parameters.filter((p) => p.name.trim() !== "")
    const same =
      externalRows.length === localPersisted.length &&
      externalRows.every((r, i) => r.name === localPersisted[i]?.name)
    if (!same) setParametersState(externalRows)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.parameters])

  const outputSchema: OutputColumn[] = Array.isArray(data.output_schema)
    ? (data.output_schema as OutputColumn[])
    : []

  useEffect(() => {
    if (!selectedWorkspace?.id) return
    setConnectionsLoading(true)
    listWorkspaceConnections(selectedWorkspace.id)
      .then(setConnections)
      .catch(() => setConnections([]))
      .finally(() => setConnectionsLoading(false))
  }, [selectedWorkspace?.id])

  // Build upstreamFields with nodeId prefix for SQL Script parameters.
  // These create {{nodeId.field}} tokens that resolve via upstream_results.
  const upstreamFields = useMemo<UpstreamField[]>(() => {
    const fields: UpstreamField[] = []
    const SKIP = new Set(["node_id", "status", "output_field", "rows_affected", "row_count", "rows_processed"])
    for (const up of upstreamOutputs) {
      if (!up.output) continue
      for (const [key, val] of Object.entries(up.output)) {
        if (SKIP.has(key)) continue
        if (val === null || val === undefined || typeof val === "object") continue
        fields.push({ name: `${up.nodeId}.${key}`, type: typeof val })
      }
    }
    return fields
  }, [upstreamOutputs])

  function update(patch: Record<string, unknown>) {
    onUpdate({ ...data, ...patch })
  }

  function selectConnection(conn: Connection) {
    update({
      connection_id: conn.id,
      connection_name: conn.name,
      label: `SQL Script: ${conn.name}`,
    })
    setShowConnectionPicker(false)
    setConnectionSearch("")
  }

  function setParameters(next: ParameterRow[]) {
    setParametersState(next)
    update({ parameters: rowsToParameters(next, mode) })
  }

  function addParameter() {
    setParameters([...parameters, { name: "", value: createFixed("") }])
  }

  function updateParameterName(index: number, name: string) {
    const next = parameters.map((p, i) => (i === index ? { ...p, name } : p))
    setParameters(next)
  }

  function updateParameterValue(index: number, value: ParameterValue) {
    const next = parameters.map((p, i) => (i === index ? { ...p, value } : p))
    setParameters(next)
  }

  function removeParameter(index: number) {
    setParameters(parameters.filter((_, i) => i !== index))
  }

  function setSchema(next: OutputColumn[]) {
    update({ output_schema: next })
  }

  function addColumn() {
    setSchema([...outputSchema, { name: "", type: "VARCHAR" }])
  }

  function updateColumn(index: number, patch: Partial<OutputColumn>) {
    setSchema(outputSchema.map((c, i) => (i === index ? { ...c, ...patch } : c)))
  }

  function removeColumn(index: number) {
    setSchema(outputSchema.filter((_, i) => i !== index))
  }

  const filteredConnections = connectionSearch
    ? connections.filter(
        (c) =>
          c.name.toLowerCase().includes(connectionSearch.toLowerCase()) ||
          c.type.toLowerCase().includes(connectionSearch.toLowerCase()),
      )
    : connections

  return (
    <div className="space-y-4">
      {/* ── Conexão ── */}
      <ConnectionField
        value={(data.connection_id as string) ?? ""}
        onChange={(v) => update({ connection_id: v, connection_name: v.startsWith("{{") ? v : data.connection_name })}
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
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[9px] font-bold uppercase",
                    DB_COLORS[selectedConnection.type] ??
                      "text-muted-foreground bg-muted",
                  )}
                >
                  {(
                    DB_LABELS[selectedConnection.type] ?? selectedConnection.type
                  ).slice(0, 2)}
                </span>
                <span className="font-medium text-foreground">
                  {selectedConnection.name}
                </span>
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
                <p className="px-3 py-2 text-[10px] text-muted-foreground">
                  Nenhuma conexão encontrada.
                </p>
              )}
            </div>
          )}
        </div>
      </ConnectionField>

      {/* ── Modo ── */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Modo
        </label>
        <select
          value={mode}
          onChange={(e) => update({ mode: e.target.value as ScriptMode })}
          className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
        >
          <option value="query">query — SELECT (materializa em DuckDB)</option>
          <option value="execute">execute — INSERT/UPDATE/DELETE/DDL</option>
          <option value="execute_many">
            execute_many — itera sobre linhas upstream
          </option>
        </select>
      </div>

      {/* ── Script SQL ── */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Script SQL
        </label>
        <textarea
          value={script}
          onChange={(e) => update({ script: e.target.value })}
          placeholder={"SELECT * FROM clientes WHERE cnpj = :cnpj"}
          rows={8}
          spellCheck={false}
          className="w-full rounded-md border border-input bg-background px-2.5 py-2 font-mono text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
        />
        <p className="text-[10px] text-muted-foreground">
          Use bindings nomeados no formato <code>:nome</code>. Interpolação de
          string (<code>{"{var}"}</code>) é bloqueada por segurança.
        </p>
      </div>

      {/* ── Parâmetros ── */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Parâmetros
          </label>
          <button
            type="button"
            onClick={addParameter}
            className="flex items-center gap-1 text-[10px] font-medium text-primary transition-colors hover:text-primary/80"
          >
            <Plus className="size-3" />
            Adicionar
          </button>
        </div>

        {parameters.length === 0 ? (
          <p className="text-[10px] text-muted-foreground">
            Nenhum parâmetro configurado.
          </p>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center gap-2 px-1 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/60">
              <span className="w-24 shrink-0">Nome (:bind)</span>
              <span className="flex-1">
                {mode === "execute_many" ? "Coluna upstream" : "Valor"}
              </span>
              <span className="w-7 shrink-0" />
            </div>

            {parameters.map((p, i) => (
              <div key={i} className="flex items-start gap-2">
                {/* Bind name */}
                <input
                  type="text"
                  value={p.name}
                  onChange={(e) => updateParameterName(i, e.target.value)}
                  placeholder="cnpj"
                  className="h-7 w-24 shrink-0 rounded-md border border-input bg-background px-2 font-mono text-xs outline-none focus:ring-1 focus:ring-primary"
                />

                {/* Value */}
                {mode === "execute_many" ? (
                  // execute_many: bind column name from upstream DuckDB table
                  upstreamColumnNames.length > 0 ? (
                    <select
                      value={p.value.mode === "fixed" ? p.value.value : ""}
                      onChange={(e) =>
                        updateParameterValue(i, createFixed(e.target.value))
                      }
                      className="h-7 flex-1 rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary"
                    >
                      <option value="">Selecionar coluna...</option>
                      {upstreamColumnNames.map((f) => (
                        <option key={f} value={f}>
                          {f}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={p.value.mode === "fixed" ? p.value.value : ""}
                      onChange={(e) =>
                        updateParameterValue(i, createFixed(e.target.value))
                      }
                      placeholder="NOME_COLUNA"
                      className="h-7 flex-1 rounded-md border border-input bg-background px-2 font-mono text-xs outline-none focus:ring-1 focus:ring-primary"
                    />
                  )
                ) : (
                  // query / execute: full ValueInput with chip support
                  <ValueInput
                    value={p.value}
                    onChange={(pv) => updateParameterValue(i, pv)}
                    upstreamFields={upstreamFields}
                    allowTransforms={false}
                    allowVariables={true}
                    useFieldRef={true}
                    size="sm"
                    placeholder="valor ou arraste campo..."
                  />
                )}

                <button
                  type="button"
                  onClick={() => removeParameter(i)}
                  className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                >
                  <Trash2 className="size-3" />
                </button>
              </div>
            ))}

            {mode !== "execute_many" && (
              <p className="text-[10px] text-muted-foreground">
                Arraste um campo do painel esquerdo ou digite um valor fixo.
              </p>
            )}
          </div>
        )}
      </div>

      {/* ── Output schema (apenas query) ── */}
      {mode === "query" && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Schema de saída
            </label>
            <button
              type="button"
              onClick={addColumn}
              className="flex items-center gap-1 text-[10px] font-medium text-primary transition-colors hover:text-primary/80"
            >
              <Plus className="size-3" />
              Adicionar coluna
            </button>
          </div>

          {outputSchema.length === 0 ? (
            <p className="text-[10px] text-muted-foreground">
              Opcional. Declare colunas para validar o retorno e expor o
              mapeamento downstream.
            </p>
          ) : (
            <div className="space-y-1.5">
              <div className="flex items-center gap-2 px-1 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                <span className="flex-1">Nome</span>
                <span className="w-24">Tipo SQL</span>
                <span className="w-7" />
              </div>
              {outputSchema.map((col, i) => (
                <div key={i} className="flex items-center gap-2">
                  <input
                    type="text"
                    value={col.name}
                    onChange={(e) =>
                      updateColumn(i, { name: e.target.value })
                    }
                    placeholder="nome_coluna"
                    className="h-7 flex-1 rounded-md border border-input bg-background px-2 font-mono text-xs outline-none focus:ring-1 focus:ring-primary"
                  />
                  <input
                    type="text"
                    value={col.type}
                    onChange={(e) =>
                      updateColumn(i, { type: e.target.value })
                    }
                    placeholder="VARCHAR"
                    className="h-7 w-24 rounded-md border border-input bg-background px-2 font-mono text-xs outline-none focus:ring-1 focus:ring-primary"
                  />
                  <button
                    type="button"
                    onClick={() => removeColumn(i)}
                    className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2 className="size-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Campo de saída ── */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Campo de saída
        </label>
        <input
          type="text"
          value={outputField}
          onChange={(e) => update({ output_field: e.target.value })}
          placeholder="sql_result"
          className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs outline-none focus:ring-1 focus:ring-primary"
        />
      </div>

      {/* ── Timeout ── */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Timeout (segundos)
        </label>
        <input
          type="number"
          value={timeoutSeconds}
          onChange={(e) =>
            update({
              timeout_seconds: parseInt(e.target.value, 10) || 60,
            })
          }
          min={1}
          max={600}
          className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs outline-none focus:ring-1 focus:ring-primary"
        />
      </div>
    </div>
  )
}
