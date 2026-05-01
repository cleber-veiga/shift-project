"use client"

import { useEffect, useMemo, useState } from "react"
import { ArrowRight, ChevronDown, Database, Search, Sparkles, Trash2 } from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import { cn } from "@/lib/utils"
import { useDashboard } from "@/lib/context/dashboard-context"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"
import {
  listWorkspaceConnections,
  getConnectionSchema,
  type Connection,
  type SchemaTable,
} from "@/lib/auth"
import { ConnectionField } from "@/components/workflow/connection-field"
import {
  type ParameterValue,
  type UpstreamField,
  createFixed,
  createDynamic,
} from "@/lib/workflow/parameter-value"
import { ValueInput } from "@/components/workflow/value-input/ValueInput"

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
  value: ParameterValue  // source expression (upstream column or expression)
  target: string         // destination table column name
}

function normalizeColumnMap(raw: unknown): ColumnMap {
  const m = (raw ?? {}) as Record<string, unknown>
  const target = typeof m.target === "string" ? m.target : ""
  // New format: { value: ParameterValue, target }
  if (m.value && typeof m.value === "object" && "mode" in (m.value as object)) {
    return { value: m.value as ParameterValue, target }
  }
  // Legacy: { source: string, target }
  const src = typeof m.source === "string" ? m.source.trim() : ""
  return {
    value: src ? createDynamic(`{{${src}}}`, []) : createFixed(""),
    target,
  }
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
    ? (data.column_mapping as unknown[]).map(normalizeColumnMap)
    : []

  const upstreamFieldPVs: UpstreamField[] = useMemo(
    () => upstreamFields.map((f) => ({ name: f })),
    [upstreamFields],
  )
  const uniqueColumns: string[] = Array.isArray(data.unique_columns)
    ? (data.unique_columns as string[])
    : []
  const returningColumns: string[] = Array.isArray(data.returning_columns)
    ? (data.returning_columns as string[])
    : []
  const mergeKeys: string[] = Array.isArray(data.merge_keys)
    ? (data.merge_keys as string[])
    : []
  const isUpsert = data.load_strategy === "upsert"

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
    setMapping([...columnMapping, { value: createFixed(""), target: "" }])
  }

  function updateMappingValue(index: number, pv: ParameterValue) {
    const next = columnMapping.map((m, i) => (i === index ? { ...m, value: pv } : m))
    setMapping(next)
  }

  // Normaliza nomes pra match fuzzy: lowercase + remove underscores/hifens/espacos.
  // Isso resolve cliente↔CLIENTE, client_id↔CLIENTID, criado em↔CRIADO_EM, etc.
  function normalize(name: string): string {
    return name.toLowerCase().replace(/[_\-\s]+/g, "")
  }

  function extractSourceField(m: ColumnMap): string {
    if (m.value.mode === "dynamic") {
      const match = m.value.template.match(/^\{\{([^}]+)\}\}$/)
      if (match) {
        // Refs com nodeId.campo — extrai apenas o campo final pro match.
        const parts = match[1].split(".")
        return parts[parts.length - 1].trim()
      }
      return ""
    }
    return m.value.value || ""
  }

  function autoMap() {
    // Diagnostico: se ambos os lados estao vazios, nao tem como casar nada.
    // Logamos pra ajudar a entender por que "clicar Auto mapear nao fez nada".
    if (upstreamFields.length === 0 || targetColumns.length === 0) {
      console.warn(
        "[BulkInsert.autoMap] sem campos para mapear",
        {
          upstreamFields,
          targetColumnsCount: targetColumns.length,
          hint: upstreamFields.length === 0
            ? "Upstream nao expos colunas. Re-execute o workflow apos restart do backend."
            : "Tabela destino nao tem colunas carregadas. Re-selecione a tabela.",
        },
      )
    }

    // Fase 0: limpa linhas totalmente vazias (sem source nem target) — usuario
    // costuma clicar "+ Adicionar coluna" antes do auto-map e essas linhas
    // poluem o resultado.
    const next: ColumnMap[] = columnMapping
      .filter((m) => extractSourceField(m) !== "" || m.target !== "")
      .map((m) => ({ ...m }))

    // Coleta sources ja mapeados (normalizados) pra evitar duplicatas.
    const mappedSourcesNorm = new Set<string>()
    const usedTargetsNorm = new Set<string>()
    for (const m of next) {
      const src = extractSourceField(m)
      if (src) mappedSourcesNorm.add(normalize(src))
      if (m.target) usedTargetsNorm.add(normalize(m.target))
    }

    // Fase 1: preenche target vazio em linhas que ja tem source valido —
    // antes era ignorado, fazendo o usuario abrir cada select manualmente.
    let didFillTarget = false
    for (const m of next) {
      if (m.target) continue
      const src = extractSourceField(m)
      if (!src) continue
      const matched = targetColumns.find(
        (t) => normalize(t) === normalize(src) && !usedTargetsNorm.has(normalize(t)),
      )
      if (matched) {
        m.target = matched
        usedTargetsNorm.add(normalize(matched))
        didFillTarget = true
      }
    }

    // Fase 2: cria novas linhas para campos upstream ainda nao mapeados,
    // casando com colunas destino disponiveis.
    let didAddNew = false
    for (const src of upstreamFields) {
      if (mappedSourcesNorm.has(normalize(src))) continue
      const matched = targetColumns.find(
        (t) => normalize(t) === normalize(src) && !usedTargetsNorm.has(normalize(t)),
      )
      if (matched) {
        next.push({ value: createDynamic(`{{${src}}}`, []), target: matched })
        mappedSourcesNorm.add(normalize(src))
        usedTargetsNorm.add(normalize(matched))
        didAddNew = true
      }
    }

    // Fallback: se nao conseguiu casar nada com a tabela destino, entrega ao
    // usuario uma starter list — todas as colunas upstream restantes como
    // linhas com target vazio pra ele resolver na mao.
    if (!didFillTarget && !didAddNew) {
      for (const src of upstreamFields) {
        if (!mappedSourcesNorm.has(normalize(src))) {
          next.push({ value: createDynamic(`{{${src}}}`, []), target: "" })
          mappedSourcesNorm.add(normalize(src))
        }
      }
    }

    setMapping(next)
  }

  // Drop em "+ Adicionar coluna": cria nova linha ja com source preenchido
  // e tenta casar target automaticamente.
  function handleAddDrop(e: React.DragEvent) {
    e.preventDefault()
    setIsDraggingOverAdd(false)

    const refRaw = e.dataTransfer.getData("application/x-shift-field-ref")
    const field = e.dataTransfer.getData("application/x-shift-field")
    if (!field && !refRaw) return

    // Prefere cross-node reference (nodeId.campo) se disponivel — preserva
    // a origem exata pro template ParameterValue.
    let template = field ? `{{${field}}}` : ""
    let sourceForMatch = field
    if (refRaw) {
      try {
        const ref = JSON.parse(refRaw) as { nodeId: string; field: string }
        template = `{{${ref.field}}}`
        const parts = ref.field.split(".")
        sourceForMatch = parts[parts.length - 1]
      } catch {
        // mantem fallback do field puro
      }
    }
    if (!template) return

    const matchedTarget = sourceForMatch
      ? targetColumns.find(
          (t) =>
            normalize(t) === normalize(sourceForMatch) &&
            !columnMapping.some((m) => normalize(m.target) === normalize(t)),
        ) ?? ""
      : ""

    setMapping([
      ...columnMapping,
      { value: createDynamic(template, []), target: matchedTarget },
    ])
  }

  const [isDraggingOverAdd, setIsDraggingOverAdd] = useState(false)

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

  const usedTargets = new Set(columnMapping.map((m) => m.target))

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
                <MorphLoader className="size-3.5" /> Carregando...
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
                    key={`${t.schema ?? ""}__${t.name}`}
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

      {/* ── Modo de escrita (Insert / Upsert) ── */}
      {selectedTableName && (
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Modo de escrita
          </label>
          <div className="grid grid-cols-2 gap-0.5 rounded-lg bg-muted p-0.5">
            <button
              type="button"
              onClick={() =>
                onUpdate({ ...data, load_strategy: "append_fast", merge_keys: [] })
              }
              className={cn(
                "rounded-md py-1.5 text-[11px] font-semibold transition-all",
                !isUpsert
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              Insert
            </button>
            <button
              type="button"
              onClick={() => onUpdate({ ...data, load_strategy: "upsert" })}
              className={cn(
                "rounded-md py-1.5 text-[11px] font-semibold transition-all",
                isUpsert
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              Upsert
            </button>
          </div>
          <p className="text-[10px] text-muted-foreground">
            {isUpsert
              ? "Atualiza linhas existentes (casadas pela chave) e insere as novas. Compatível com retorno de IDs."
              : "Insere todas as linhas. Falhas de constraint vão para o branch on_error."}
          </p>
        </div>
      )}

      {/* ── Colunas-chave do upsert (so no modo Upsert) ── */}
      {selectedTableName && isUpsert && (
        <div className="space-y-1.5">
          <label className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Colunas-chave do upsert
            <span className="rounded-full bg-amber-500/10 px-1.5 py-0.5 text-[8px] font-bold normal-case tracking-normal text-amber-600">
              obrigatório
            </span>
          </label>
          {targetColumns.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {targetColumns.map((col) => {
                const isSelected = mergeKeys.includes(col)
                return (
                  <button
                    key={col}
                    type="button"
                    onClick={() => {
                      const next = isSelected
                        ? mergeKeys.filter((c) => c !== col)
                        : [...mergeKeys, col]
                      onUpdate({ ...data, merge_keys: next })
                    }}
                    className={cn(
                      "inline-flex h-6 items-center gap-1 rounded-md border px-2 text-[10px] font-medium transition-colors",
                      isSelected
                        ? "border-primary/30 bg-primary/10 text-primary"
                        : "border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                  >
                    {isSelected && <span className="size-1.5 rounded-full bg-primary" />}
                    {col}
                  </button>
                )
              })}
            </div>
          ) : (
            <p className="text-[10px] text-muted-foreground">
              Selecione uma tabela para listar colunas.
            </p>
          )}
          <p className="text-[10px] text-muted-foreground">
            {mergeKeys.length > 0 ? (
              <>
                Linhas onde <code className="font-mono text-foreground">[{mergeKeys.join(", ")}]</code>{" "}
                já existirem serão atualizadas; demais, inseridas.
              </>
            ) : (
              "Selecione as colunas que identificam unicamente cada registro (ex.: chave natural como CNPJ ou código)."
            )}
          </p>
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
            <span className="flex-1">Valor (origem)</span>
            <span className="w-5" />
            <span className="flex-1">Destino (tabela)</span>
            <span className="w-7" />
          </div>

          {/* Rows */}
          <div className="space-y-1.5">
            {columnMapping.map((m, i) => (
              <div key={i} className="flex items-center gap-2">
                {/* Value (source expression) */}
                <div className="flex-1 min-w-0">
                  <ValueInput
                    value={m.value}
                    onChange={(pv) => updateMappingValue(i, pv)}
                    upstreamFields={upstreamFieldPVs}
                    allowTransforms={true}
                    allowVariables={true}
                    placeholder="campo ou expressão..."
                    size="sm"
                  />
                </div>

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

          {/* Add mapping button — aceita drop direto pra criar linha
              ja com source preenchido e target auto-casado. */}
          <button
            type="button"
            onClick={addMapping}
            onDragEnter={(e) => {
              if (
                e.dataTransfer.types.includes("application/x-shift-field") ||
                e.dataTransfer.types.includes("application/x-shift-field-ref")
              ) {
                e.preventDefault()
                setIsDraggingOverAdd(true)
              }
            }}
            onDragOver={(e) => {
              if (
                e.dataTransfer.types.includes("application/x-shift-field") ||
                e.dataTransfer.types.includes("application/x-shift-field-ref")
              ) {
                e.preventDefault()
                e.dataTransfer.dropEffect = "copy"
              }
            }}
            onDragLeave={() => setIsDraggingOverAdd(false)}
            onDrop={handleAddDrop}
            className={cn(
              "flex w-full items-center justify-center gap-1.5 rounded-md border-2 border-dashed py-2 text-[11px] font-medium transition-all",
              isDraggingOverAdd
                ? "border-primary bg-primary/10 text-primary scale-[1.01]"
                : "border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground",
            )}
          >
            {isDraggingOverAdd ? "Soltar para adicionar" : "+ Adicionar coluna"}
          </button>
        </div>
      )}

      {/* ── Unique columns (dedup) ── */}
      {selectedTableName && columnMapping.length > 0 && (
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Colunas únicas (dedup)
          </label>
          <div className="flex flex-wrap gap-1.5">
            {columnMapping
              .filter((m) => m.target)
              .map((m) => {
                const isSelected = uniqueColumns.includes(m.target)
                return (
                  <button
                    key={m.target}
                    type="button"
                    onClick={() => {
                      const next = isSelected
                        ? uniqueColumns.filter((c) => c !== m.target)
                        : [...uniqueColumns, m.target]
                      onUpdate({ ...data, unique_columns: next })
                    }}
                    className={cn(
                      "inline-flex h-6 items-center gap-1 rounded-md border px-2 text-[10px] font-medium transition-colors",
                      isSelected
                        ? "border-primary/30 bg-primary/10 text-primary"
                        : "border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                  >
                    {isSelected && <span className="size-1.5 rounded-full bg-primary" />}
                    {m.target}
                  </button>
                )
              })}
          </div>
          <p className="text-[10px] text-muted-foreground">
            {uniqueColumns.length > 0
              ? `Duplicatas com mesmos valores em [${uniqueColumns.join(", ")}] serão removidas antes do INSERT.`
              : "Selecione colunas que formam a chave única. Duplicatas serão removidas antes de inserir."}
          </p>
        </div>
      )}

      {/* ── Colunas a retornar (RETURNING / OUTPUT INSERTED) ── */}
      {selectedTableName && (
        <div className="space-y-1.5">
          <label className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Colunas a retornar
            <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[8px] font-bold normal-case tracking-normal text-primary">
              novo
            </span>
          </label>
          {targetColumns.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {targetColumns.map((col) => {
                const isSelected = returningColumns.includes(col)
                return (
                  <button
                    key={col}
                    type="button"
                    onClick={() => {
                      const next = isSelected
                        ? returningColumns.filter((c) => c !== col)
                        : [...returningColumns, col]
                      onUpdate({ ...data, returning_columns: next })
                    }}
                    className={cn(
                      "inline-flex h-6 items-center gap-1 rounded-md border px-2 text-[10px] font-medium transition-colors",
                      isSelected
                        ? "border-primary/30 bg-primary/10 text-primary"
                        : "border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                  >
                    {isSelected && <span className="size-1.5 rounded-full bg-primary" />}
                    {col}
                  </button>
                )
              })}
            </div>
          ) : (
            <p className="text-[10px] text-muted-foreground">
              Selecione uma tabela para listar colunas.
            </p>
          )}
          <p className="text-[10px] text-muted-foreground">
            {returningColumns.length > 0 ? (
              <>
                Cada linha do branch <code className="font-mono text-foreground">success</code> downstream
                receberá <code className="font-mono text-foreground">[{returningColumns.join(", ")}]</code>{" "}
                gerados pelo banco. Compatível com PostgreSQL, SQL Server, Oracle e SQLite.
              </>
            ) : (
              "Receba valores gerados pelo banco (ex.: ID auto-increment) sem precisar de um SELECT extra. Não suportado em MySQL/Firebird."
            )}
          </p>
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
