export type TransformKind =
  | "upper"
  | "lower"
  | "trim"
  | "digits_only"
  | "remove_specials"
  | "replace"
  | "truncate"
  | "remove_chars"

export type TransformEntry = {
  kind: TransformKind
  args?: Record<string, string | number>
}

export type ParameterValue =
  | { mode: "fixed"; value: string }
  | { mode: "dynamic"; template: string; transforms?: TransformEntry[] }

// ─── Upstream field descriptor ────────────────────────────────────────────────

export interface UpstreamField {
  name: string
  type?: string
}

// ─── Type guards & factories ──────────────────────────────────────────────────

export function isParameterValue(x: unknown): x is ParameterValue {
  if (typeof x !== "object" || x === null) return false
  const obj = x as Record<string, unknown>
  if (obj.mode === "fixed") return typeof obj.value === "string"
  if (obj.mode === "dynamic") return typeof obj.template === "string"
  return false
}

export function createFixed(value: string): ParameterValue {
  return { mode: "fixed", value }
}

export function createDynamic(
  template: string,
  transforms?: TransformEntry[]
): ParameterValue {
  return transforms !== undefined
    ? { mode: "dynamic", template, transforms }
    : { mode: "dynamic", template }
}

export function parameterValueToJson(v: ParameterValue): unknown {
  return { ...v }
}

export function parameterValueFromJson(raw: unknown): ParameterValue {
  if (!isParameterValue(raw)) {
    throw new Error(`Invalid ParameterValue: ${JSON.stringify(raw)}`)
  }
  return raw
}

/**
 * Converts a legacy SQL Script parameter value to ParameterValue.
 *
 * "upstream_results.node_X.data.CAMPO" → { mode: "dynamic", template: "{{node_X.data.CAMPO}}" }
 * "upstream.node_X.CAMPO"              → { mode: "dynamic", template: "{{node_X.CAMPO}}" }
 * { mode: "fixed"|"dynamic", ... }     → returned as-is
 * "literal_value"                      → { mode: "fixed", value: "literal_value" }
 */
export function migrateLegacySqlParameter(raw: unknown): ParameterValue {
  if (isParameterValue(raw)) return raw
  if (typeof raw !== "string") {
    return createFixed(raw != null ? String(raw) : "")
  }
  const path = raw.trim()
  if (!path) return createFixed("")
  const m = /^upstream_results\.(.+)$/.exec(path) || /^upstream\.(.+)$/.exec(path)
  if (m) return createDynamic(`{{${m[1]}}}`, [])
  return createFixed(path)
}

// ─── Mapper compatibility adapters ───────────────────────────────────────────
// The Mapper persists { valueType, source, value, exprTemplate, transforms }.
// These adapters bridge that shape ↔ ParameterValue for the UI layer.
// Nothing on disk is changed in this phase.

/** Minimal shape of a mapper Mapping — matches mapper-config.tsx's Mapping type */
export interface MapperMapping {
  valueType: "field" | "static" | "expression"
  source?: string
  value?: string
  exprTemplate?: string
  transforms?: Array<string | { id: string; params: Record<string, string> }>
}

/** Converts a Mapper transform entry to the ParameterValue TransformEntry format */
function mapperTransformToEntry(
  entry: string | { id: string; params: Record<string, string> }
): TransformEntry | null {
  const id = typeof entry === "string" ? entry : entry.id
  const params = typeof entry === "string" ? {} : entry.params

  const simpleKinds: Record<string, TransformKind> = {
    upper: "upper",
    lower: "lower",
    trim: "trim",
    only_digits: "digits_only",
    remove_special: "remove_specials",
    remove_specials: "remove_specials",
  }

  if (id === "replace") {
    return { kind: "replace", args: { old: params.from ?? "", new: params.to ?? "" } }
  }
  if (id === "truncate") {
    const length = parseInt(params.length ?? "0", 10)
    return { kind: "truncate", args: { length: isNaN(length) ? 0 : length } }
  }
  if (id === "remove_chars") {
    return { kind: "remove_chars", args: { chars: params.chars ?? "" } }
  }
  const kind = simpleKinds[id]
  if (kind) return { kind }
  return null
}

/** Converts a ParameterValue TransformEntry back to the Mapper's format */
function entryToMapperTransform(
  entry: TransformEntry
): string | { id: string; params: Record<string, string> } {
  const pvToMapper: Record<TransformKind, string> = {
    upper: "upper",
    lower: "lower",
    trim: "trim",
    digits_only: "only_digits",
    remove_specials: "remove_special",
    replace: "replace",
    truncate: "truncate",
    remove_chars: "remove_chars",
  }

  if (entry.kind === "replace") {
    return {
      id: "replace",
      params: {
        from: String(entry.args?.old ?? ""),
        to: String(entry.args?.new ?? ""),
      },
    }
  }
  if (entry.kind === "truncate") {
    return {
      id: "truncate",
      params: { length: String(entry.args?.length ?? "") },
    }
  }
  if (entry.kind === "remove_chars") {
    return {
      id: "remove_chars",
      params: { chars: String(entry.args?.chars ?? "") },
    }
  }
  return pvToMapper[entry.kind] ?? entry.kind
}

/**
 * Converts a Mapper Mapping to a ParameterValue for use in the UI layer.
 *
 * field      → dynamic  { template: "{{source}}", transforms: [...] }
 * static     → fixed    { value: "..." }
 * expression → dynamic  { template: exprTemplate, transforms: [] }
 */
export function mappingToParameterValue(mapping: MapperMapping): ParameterValue {
  if (mapping.valueType === "static") {
    return createFixed(mapping.value ?? "")
  }
  if (mapping.valueType === "field") {
    const template = mapping.source ? `{{${mapping.source}}}` : ""
    const transforms = (mapping.transforms ?? [])
      .map(mapperTransformToEntry)
      .filter((e): e is TransformEntry => e !== null)
    return { mode: "dynamic", template, transforms }
  }
  // expression
  return { mode: "dynamic", template: mapping.exprTemplate ?? "", transforms: [] }
}

/**
 * Converts a ParameterValue back to a Mapper Mapping shape for persistence.
 * `existing` provides the non-value fields (target, type, etc.) to merge into.
 *
 * fixed                   → static
 * dynamic {{X}} only      → field (source = X)
 * dynamic multi/text      → expression
 */
export function parameterValueToMapping(
  pv: ParameterValue,
  existing: MapperMapping
): MapperMapping {
  if (pv.mode === "fixed") {
    return { ...existing, valueType: "static", value: pv.value, source: "", exprTemplate: "", transforms: [] }
  }

  const singleField = /^\{\{([^}]+)\}\}$/.exec(pv.template)
  if (singleField) {
    const source = singleField[1]
    const transforms = (pv.transforms ?? []).map(entryToMapperTransform)
    return { ...existing, valueType: "field", source, exprTemplate: "", transforms }
  }

  return {
    ...existing,
    valueType: "expression",
    exprTemplate: pv.template,
    source: "",
    transforms: [],
  }
}
