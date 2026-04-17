"use client"

import { useMemo, useState } from "react"
import { ArrowRight, Boxes, Code2, HelpCircle, RefreshCw, Sparkles, Table as TableIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"
import { useCustomNodes, findCustomNode } from "@/lib/workflow/custom-nodes-context"
import {
  previewCompositeSql,
  type CompositePreviewStatement,
} from "@/lib/auth"
import type {
  CompositeBlueprint,
  CompositeConflictMode,
  CompositeTableStep,
  CustomNodeFormField,
  CustomNodeFormSchema,
} from "@/lib/auth"

interface CompositeInsertConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

type FieldMapping = Record<string, string>

function blueprintFromData(data: Record<string, unknown>): CompositeBlueprint | null {
  const bp = data.blueprint as CompositeBlueprint | null | undefined
  if (!bp || !Array.isArray(bp.tables)) return null
  return bp
}

function formSchemaFromData(
  data: Record<string, unknown>
): CustomNodeFormSchema | null {
  const s = data.form_schema as CustomNodeFormSchema | null | undefined
  if (!s || !Array.isArray(s.fields)) return null
  return s
}

const CONFLICT_MODE_LABELS: Record<CompositeConflictMode, string> = {
  insert: "Apenas inserir",
  upsert: "Upsert (atualiza em conflito)",
  insert_or_ignore: "Ignorar em conflito",
}

export function CompositeInsertConfig({ data, onUpdate }: CompositeInsertConfigProps) {
  const upstreamFields = useUpstreamFields()
  const customNodes = useCustomNodes()
  const [previewDialect, setPreviewDialect] = useState<"postgres" | "sqlite" | "oracle">("postgres")
  const [previewByAlias, setPreviewByAlias] = useState<Record<string, CompositePreviewStatement>>({})
  const [previewLoadingAlias, setPreviewLoadingAlias] = useState<string | null>(null)
  const [previewErrorByAlias, setPreviewErrorByAlias] = useState<Record<string, string>>({})

  const definitionId = (data.definition_id as string | null | undefined) ?? null
  const storedVersion = (data.definition_version as number | undefined) ?? null
  const storedBlueprint = blueprintFromData(data)
  const storedFormSchema = formSchemaFromData(data)
  const mapping: FieldMapping = (data.field_mapping as FieldMapping | undefined) ?? {}

  // Snapshot-at-drop: execution uses node.data.blueprint, not the live definition.
  // Show a drift banner when the stored snapshot is stale so the user can re-sync.
  const liveDefinition = findCustomNode(customNodes, definitionId)
  const blueprint = storedBlueprint ?? liveDefinition?.blueprint ?? null
  const formSchema = storedFormSchema ?? liveDefinition?.form_schema ?? null

  const hasDrift =
    liveDefinition !== null &&
    liveDefinition !== undefined &&
    storedVersion !== null &&
    liveDefinition.version !== storedVersion

  function resyncToLive() {
    if (!liveDefinition) return
    onUpdate({
      ...data,
      definition_version: liveDefinition.version,
      icon: liveDefinition.icon ?? null,
      color: liveDefinition.color ?? null,
      blueprint: liveDefinition.blueprint,
      form_schema: liveDefinition.form_schema,
    })
  }

  // Index form fields by blueprint key (alias.column)
  const formFieldsByKey = useMemo(() => {
    const map = new Map<string, CustomNodeFormField>()
    if (formSchema) {
      for (const f of formSchema.fields) map.set(f.key, f)
    }
    return map
  }, [formSchema])

  // Visible keys (honoring hidden flag) — used for counts and auto-map
  const visibleKeys = useMemo(() => {
    if (!blueprint) return [] as string[]
    const keys: string[] = []
    for (const t of blueprint.tables) {
      for (const col of t.columns) {
        const key = `${t.alias}.${col}`
        const field = formFieldsByKey.get(key)
        if (field?.hidden) continue
        keys.push(key)
      }
    }
    return keys
  }, [blueprint, formFieldsByKey])

  const requiredKeys = useMemo(() => {
    const s = new Set<string>()
    for (const f of formFieldsByKey.values()) {
      if (f.required && !f.hidden) s.add(f.key)
    }
    return s
  }, [formFieldsByKey])

  function setMapping(next: FieldMapping) {
    onUpdate({ ...data, field_mapping: next })
  }

  function updateStep(alias: string, patch: Partial<CompositeTableStep>) {
    if (!blueprint) return
    const nextTables = blueprint.tables.map((t) =>
      t.alias === alias ? { ...t, ...patch } : t,
    )
    onUpdate({ ...data, blueprint: { ...blueprint, tables: nextTables } })
  }

  function setConflictMode(alias: string, mode: CompositeConflictMode) {
    const table = blueprint?.tables.find((t) => t.alias === alias)
    if (!table) return
    const patch: Partial<CompositeTableStep> = { conflict_mode: mode }
    if (mode === "insert") {
      patch.conflict_keys = []
      patch.update_columns = null
    } else if ((table.conflict_keys ?? []).length === 0 && table.columns.length > 0) {
      // Sugestao: primeira coluna como conflict_key — usuario pode trocar.
      patch.conflict_keys = [table.columns[0]]
    }
    updateStep(alias, patch)
  }

  function toggleConflictKey(alias: string, col: string) {
    const table = blueprint?.tables.find((t) => t.alias === alias)
    if (!table) return
    const current = new Set(table.conflict_keys ?? [])
    if (current.has(col)) current.delete(col)
    else current.add(col)
    updateStep(alias, { conflict_keys: Array.from(current) })
  }

  function toggleUpdateColumn(alias: string, col: string) {
    const table = blueprint?.tables.find((t) => t.alias === alias)
    if (!table) return
    const explicit = table.update_columns
    // null = "todas exceto keys"; converte para lista explicita ao primeiro toggle.
    const base =
      explicit === null || explicit === undefined
        ? table.columns.filter((c) => !(table.conflict_keys ?? []).includes(c))
        : [...explicit]
    const set = new Set(base)
    if (set.has(col)) set.delete(col)
    else set.add(col)
    updateStep(alias, { update_columns: Array.from(set) })
  }

  async function runPreview(alias: string) {
    if (!blueprint) return
    const table = blueprint.tables.find((t) => t.alias === alias)
    if (!table) return
    setPreviewLoadingAlias(alias)
    setPreviewErrorByAlias((prev) => {
      const { [alias]: _, ...rest } = prev
      return rest
    })
    try {
      const allCols = Array.from(
        new Set<string>([
          ...table.columns,
          ...(table.fk_map ?? []).map((fk) => fk.child_column),
        ]),
      )
      const [stmt] = await previewCompositeSql(previewDialect, [
        {
          alias: table.alias,
          table: table.table,
          columns: allCols,
          conflict_mode: table.conflict_mode ?? "insert",
          conflict_keys: table.conflict_keys ?? [],
          update_columns: table.update_columns ?? null,
          returning: table.returning ?? [],
        },
      ])
      setPreviewByAlias((prev) => ({ ...prev, [alias]: stmt }))
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setPreviewErrorByAlias((prev) => ({ ...prev, [alias]: msg }))
    } finally {
      setPreviewLoadingAlias(null)
    }
  }

  function updateMappingEntry(key: string, upstream: string) {
    const next: FieldMapping = { ...mapping }
    if (upstream) next[key] = upstream
    else delete next[key]
    setMapping(next)
  }

  function autoMap() {
    if (!blueprint) return
    const next: FieldMapping = { ...mapping }
    const upstreamLower = new Map(upstreamFields.map((f) => [f.toLowerCase(), f]))
    for (const key of visibleKeys) {
      if (next[key]) continue
      // 1) Prefer form_schema.default_upstream when set
      const field = formFieldsByKey.get(key)
      const hint = field?.default_upstream?.trim()
      if (hint) {
        const fromHint = upstreamLower.get(hint.toLowerCase())
        if (fromHint) {
          next[key] = fromHint
          continue
        }
      }
      // 2) Fallback: match by column name (case-insensitive)
      const col = key.split(".").slice(1).join(".")
      const match = upstreamLower.get(col.toLowerCase())
      if (match) next[key] = match
    }
    setMapping(next)
  }

  if (!blueprint) {
    return (
      <div className="rounded-lg border border-dashed border-amber-500/30 bg-amber-500/5 p-3">
        <p className="text-xs font-medium text-amber-600 dark:text-amber-400">
          Nó sem definição
        </p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          A definição deste nó composto não está disponível no workspace atual. Arraste um nó
          personalizado da paleta para criar uma nova instância.
        </p>
      </div>
    )
  }

  const mappedVisibleCount = visibleKeys.filter(
    (k) => (mapping[k] ?? "").trim() !== ""
  ).length
  const missingRequired = [...requiredKeys].filter(
    (k) => !(mapping[k] ?? "").trim()
  )

  return (
    <div className="space-y-4">
      {/* ── Definition summary ── */}
      <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3">
        <div className="flex items-center gap-2">
          <Boxes className="size-4 text-emerald-500" />
          <p className="text-xs font-semibold text-foreground">
            {liveDefinition?.name ?? (data.label as string) ?? "Nó composto"}
          </p>
          <span className="ml-auto inline-flex items-center rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] font-semibold text-foreground">
            v{liveDefinition?.version ?? (data.definition_version as number | undefined) ?? "?"}
          </span>
        </div>
        {liveDefinition?.description && (
          <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
            {liveDefinition.description}
          </p>
        )}
        <p className="mt-2 text-[10px] text-muted-foreground">
          {blueprint.tables.length} tabela{blueprint.tables.length !== 1 ? "s" : ""} ·{" "}
          {mappedVisibleCount}/{visibleKeys.length} campo{visibleKeys.length !== 1 ? "s" : ""}{" "}
          mapeado{mappedVisibleCount !== 1 ? "s" : ""}
        </p>
      </div>

      {hasDrift && (
        <div className="flex items-start gap-2 rounded-md border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-700 dark:text-amber-400">
          <div className="flex-1">
            <p className="font-medium">Definição atualizada</p>
            <p className="mt-0.5 text-[10px] leading-tight">
              O snapshot deste nó está em v{storedVersion}; a definição atual é v
              {liveDefinition?.version}. Ressincronize para aplicar as mudanças.
            </p>
          </div>
          <button
            type="button"
            onClick={resyncToLive}
            className="inline-flex shrink-0 items-center gap-1 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[10px] font-semibold transition-colors hover:bg-amber-500/20"
          >
            <RefreshCw className="size-3" />
            Ressincronizar
          </button>
        </div>
      )}

      {missingRequired.length > 0 && (
        <div className="rounded-md border border-red-500/20 bg-red-500/5 px-3 py-2 text-[11px] text-red-600 dark:text-red-400">
          {missingRequired.length} campo{missingRequired.length !== 1 ? "s" : ""} obrigatório
          {missingRequired.length !== 1 ? "s" : ""} sem mapeamento.
        </div>
      )}

      {/* ── Auto-map button ── */}
      <div className="flex items-center justify-between">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Mapeamento de campos
        </label>
        <button
          type="button"
          onClick={autoMap}
          disabled={upstreamFields.length === 0}
          className="flex items-center gap-1 text-[10px] font-medium text-primary transition-colors hover:text-primary/80 disabled:opacity-40"
        >
          <Sparkles className="size-3" />
          Auto mapear
        </button>
      </div>

      {/* ── Tables + columns ── */}
      <div className="space-y-3">
        {blueprint.tables.map((table: CompositeTableStep) => {
          const tableVisibleCols = table.columns.filter((col) => {
            const field = formFieldsByKey.get(`${table.alias}.${col}`)
            return !field?.hidden
          })
          if (tableVisibleCols.length === 0 && (!table.fk_map || table.fk_map.length === 0)) {
            return null
          }

          return (
            <div key={table.alias} className="rounded-lg border border-border bg-muted/20 p-2.5">
              <div className="mb-2 flex items-center gap-2">
                <TableIcon className="size-3 text-muted-foreground" />
                <span className="font-mono text-[11px] font-semibold text-foreground">
                  {table.table}
                </span>
                <span className="text-[10px] text-muted-foreground">({table.alias})</span>
                <span
                  className={cn(
                    "ml-auto inline-flex rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase",
                    table.role === "header"
                      ? "bg-violet-500/10 text-violet-500"
                      : "bg-blue-500/10 text-blue-500",
                  )}
                >
                  {table.role}
                </span>
              </div>

              <div className="space-y-1.5">
                {tableVisibleCols.map((col) => {
                  const key = `${table.alias}.${col}`
                  const field = formFieldsByKey.get(key)
                  const current = mapping[key] ?? ""
                  const label = field?.label?.trim() || col
                  const isRequired = field?.required === true
                  const isEmpty = !current
                  return (
                    <div key={key} className="space-y-0.5">
                      <div className="flex items-center gap-2">
                        <div className="flex w-[92px] shrink-0 items-center gap-1">
                          <span className="truncate text-[10px] font-medium text-foreground" title={col}>
                            {label}
                          </span>
                          {isRequired && (
                            <span className="text-[10px] font-semibold text-red-500">*</span>
                          )}
                          {field?.help && (
                            <span title={field.help} className="cursor-help text-muted-foreground/60">
                              <HelpCircle className="size-2.5" />
                            </span>
                          )}
                        </div>
                        <ArrowRight className="size-3 shrink-0 text-muted-foreground/40" />
                        <select
                          value={current}
                          onChange={(e) => updateMappingEntry(key, e.target.value)}
                          className={cn(
                            "h-7 flex-1 rounded-md border bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary",
                            isRequired && isEmpty
                              ? "border-red-500/50"
                              : "border-input",
                            current ? "text-foreground" : "text-muted-foreground",
                          )}
                        >
                          <option value="">Selecionar upstream...</option>
                          {upstreamFields.map((f) => (
                            <option key={f} value={f}>
                              {f}
                            </option>
                          ))}
                        </select>
                      </div>
                      {field?.help && (
                        <p className="pl-[100px] text-[10px] leading-tight text-muted-foreground">
                          {field.help}
                        </p>
                      )}
                    </div>
                  )
                })}
              </div>

              {table.fk_map && table.fk_map.length > 0 && (
                <div className="mt-2 border-t border-border/50 pt-2">
                  <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">
                    FK (automático)
                  </p>
                  <div className="mt-1 space-y-0.5">
                    {table.fk_map.map((fk, i) => (
                      <p key={i} className="font-mono text-[10px] text-muted-foreground">
                        {fk.child_column} ← {table.parent_alias}.{fk.parent_returning}
                      </p>
                    ))}
                  </div>
                </div>
              )}

              {/* ── Estrategia de conflito ── */}
              {(() => {
                const mode: CompositeConflictMode = table.conflict_mode ?? "insert"
                const keySet = new Set(table.conflict_keys ?? [])
                const candidateKeyCols = Array.from(
                  new Set<string>([
                    ...table.columns,
                    ...(table.fk_map ?? []).map((fk) => fk.child_column),
                  ]),
                )
                const nonKeyCols = table.columns.filter((c) => !keySet.has(c))
                const explicitUpdate = table.update_columns
                const updateSet =
                  explicitUpdate === null || explicitUpdate === undefined
                    ? new Set(nonKeyCols)
                    : new Set(explicitUpdate)
                const preview = previewByAlias[table.alias]
                const previewErr = previewErrorByAlias[table.alias]

                return (
                  <div className="mt-2 border-t border-border/50 pt-2 space-y-2">
                    <div className="flex items-center gap-2">
                      <span className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">
                        Conflito
                      </span>
                      <select
                        value={mode}
                        onChange={(e) =>
                          setConflictMode(table.alias, e.target.value as CompositeConflictMode)
                        }
                        className="h-6 flex-1 rounded-md border border-input bg-background px-1.5 text-[10px] outline-none focus:ring-1 focus:ring-primary"
                      >
                        {(["insert", "upsert", "insert_or_ignore"] as CompositeConflictMode[]).map(
                          (m) => (
                            <option key={m} value={m}>
                              {CONFLICT_MODE_LABELS[m]}
                            </option>
                          ),
                        )}
                      </select>
                    </div>

                    {mode !== "insert" && (
                      <div>
                        <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">
                          Chaves de conflito
                        </p>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {candidateKeyCols.map((col) => (
                            <label
                              key={col}
                              className={cn(
                                "cursor-pointer rounded-md border px-1.5 py-0.5 text-[10px] transition-colors",
                                keySet.has(col)
                                  ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                                  : "border-input bg-background text-muted-foreground hover:bg-muted",
                              )}
                            >
                              <input
                                type="checkbox"
                                checked={keySet.has(col)}
                                onChange={() => toggleConflictKey(table.alias, col)}
                                className="sr-only"
                              />
                              {col}
                            </label>
                          ))}
                        </div>
                        {(table.conflict_keys ?? []).length === 0 && (
                          <p className="mt-1 text-[10px] text-red-500">
                            Selecione ao menos uma chave.
                          </p>
                        )}
                      </div>
                    )}

                    {mode === "upsert" && nonKeyCols.length > 0 && (
                      <div>
                        <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">
                          Colunas atualizadas
                          {explicitUpdate === null || explicitUpdate === undefined ? (
                            <span className="ml-1 normal-case tracking-normal text-muted-foreground/70">
                              (todas)
                            </span>
                          ) : null}
                        </p>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {nonKeyCols.map((col) => (
                            <label
                              key={col}
                              className={cn(
                                "cursor-pointer rounded-md border px-1.5 py-0.5 text-[10px] transition-colors",
                                updateSet.has(col)
                                  ? "border-violet-500/40 bg-violet-500/10 text-violet-700 dark:text-violet-400"
                                  : "border-input bg-background text-muted-foreground hover:bg-muted",
                              )}
                            >
                              <input
                                type="checkbox"
                                checked={updateSet.has(col)}
                                onChange={() => toggleUpdateColumn(table.alias, col)}
                                className="sr-only"
                              />
                              {col}
                            </label>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="flex items-center gap-2">
                      <select
                        value={previewDialect}
                        onChange={(e) =>
                          setPreviewDialect(e.target.value as "postgres" | "sqlite" | "oracle")
                        }
                        className="h-6 rounded-md border border-input bg-background px-1.5 text-[10px] outline-none focus:ring-1 focus:ring-primary"
                      >
                        <option value="postgres">postgres</option>
                        <option value="sqlite">sqlite</option>
                        <option value="oracle">oracle</option>
                      </select>
                      <button
                        type="button"
                        onClick={() => runPreview(table.alias)}
                        disabled={previewLoadingAlias === table.alias}
                        className="inline-flex items-center gap-1 rounded-md border border-input bg-background px-2 py-0.5 text-[10px] font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-40"
                      >
                        <Code2 className="size-2.5" />
                        {previewLoadingAlias === table.alias ? "Gerando..." : "Ver SQL"}
                      </button>
                    </div>
                    {previewErr && (
                      <p className="text-[10px] text-red-500">{previewErr}</p>
                    )}
                    {preview && (
                      <div className="space-y-1">
                        <pre className="max-h-40 overflow-auto rounded-md border border-border bg-muted/40 p-2 font-mono text-[10px] leading-snug text-foreground">
                          {preview.primary_sql}
                        </pre>
                        {preview.fetch_existing_sql && (
                          <>
                            <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">
                              Fallback SELECT
                            </p>
                            <pre className="max-h-32 overflow-auto rounded-md border border-border bg-muted/40 p-2 font-mono text-[10px] leading-snug text-foreground">
                              {preview.fetch_existing_sql}
                            </pre>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                )
              })()}
            </div>
          )
        })}
      </div>

      {upstreamFields.length === 0 && (
        <p className="text-[10px] text-muted-foreground">
          Conecte um nó de origem (ex.: SQL, CSV) para listar campos upstream disponíveis.
        </p>
      )}
    </div>
  )
}
