"use client"

import { useState } from "react"
import { Braces, Link2, Plus, TextCursorInput } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  type ParameterValue,
  type TransformEntry,
  type UpstreamField,
  createFixed,
  createDynamic,
} from "@/lib/workflow/parameter-value"
import { ExpressionEditor } from "./ExpressionEditor"
import { TransformsBar, TransformsPicker } from "./TransformsBar"

// ─── Types ────────────────────────────────────────────────────────────────────

export interface ValueInputProps {
  value: ParameterValue
  onChange: (next: ParameterValue) => void
  upstreamFields?: UpstreamField[]
  allowTransforms?: boolean
  allowVariables?: boolean
  /** When true, drag-drop creates {{nodeId.field}} tokens (for SQL Script params). */
  useFieldRef?: boolean
  placeholder?: string
  expectedType?: "string" | "integer" | "float" | "boolean" | "date" | "datetime"
  size?: "sm" | "md"
  disabled?: boolean
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Returns true when the template is exactly one `{{FIELD}}` token with no transforms. */
export function isSingleChipTemplate(pv: ParameterValue): boolean {
  if (pv.mode !== "dynamic") return false
  if ((pv.transforms ?? []).length > 0) return false
  return /^\{\{([^}]+)\}\}$/.test(pv.template)
}

function extractFieldName(template: string): string {
  return /^\{\{([^}]+)\}\}$/.exec(template)?.[1] ?? ""
}

// ─── Component ────────────────────────────────────────────────────────────────

export function ValueInput({
  value,
  onChange,
  upstreamFields = [],
  allowTransforms = true,
  allowVariables = true,
  useFieldRef = false,
  placeholder,
  size = "md",
  disabled,
}: ValueInputProps) {
  // When the compact chip is displayed, the user can click "+ transformação"
  // to reveal the full ExpressionEditor + TransformsBar.
  const [showFull, setShowFull] = useState(false)

  const isFixed = value.mode === "fixed"
  const isDynamic = value.mode === "dynamic"
  const transforms: TransformEntry[] = isDynamic ? (value.transforms ?? []) : []

  // Compact mode: single chip, no transforms, and the user hasn't expanded yet.
  const compact = isDynamic && isSingleChipTemplate(value) && !showFull

  // ── Mode switch helpers ──────────────────────────────────────────────────────

  function switchToFixed() {
    setShowFull(false)
    onChange(createFixed(""))
  }

  function switchToDynamic() {
    // Carry fixed text as template literal so "hello" → dynamic "hello" is lossless.
    const seed = isFixed && value.value ? value.value : ""
    onChange(createDynamic(seed, []))
  }

  // ── Value change handlers ────────────────────────────────────────────────────

  function handleFixedChange(text: string) {
    onChange(createFixed(text))
  }

  function handleTemplateChange(template: string) {
    onChange({ mode: "dynamic", template, transforms })
  }

  function handleTransformsChange(next: TransformEntry[]) {
    if (value.mode !== "dynamic") return
    onChange({ ...value, transforms: next })
  }

  // Drag a field onto a fixed input → auto-promote to dynamic with the chip.
  function handleFixedDrop(e: React.DragEvent) {
    if (useFieldRef) {
      const refRaw = e.dataTransfer.getData("application/x-shift-field-ref")
      if (refRaw) {
        try {
          const ref = JSON.parse(refRaw) as { nodeId?: string; field?: string }
          if (ref.nodeId && ref.field) {
            e.preventDefault()
            setShowFull(false)
            onChange(createDynamic(`{{${ref.nodeId}.${ref.field}}}`, []))
            return
          }
        } catch { /* fallthrough */ }
      }
    }
    const field = e.dataTransfer.getData("application/x-shift-field")
    if (!field) return
    e.preventDefault()
    setShowFull(false)
    onChange(createDynamic(`{{${field}}}`, []))
  }

  // ── Sizing ───────────────────────────────────────────────────────────────────

  const toggleSize = size === "sm" ? "size-6" : "size-7"
  const inputH     = size === "sm" ? "h-6 text-[11px]" : "h-7 text-xs"

  // ── Toggle button ────────────────────────────────────────────────────────────

  const toggleBtn = (
    <button
      type="button"
      disabled={disabled}
      title={
        isFixed
          ? "Valor fixo · clique para dinâmico"
          : compact
            ? "Campo linkado · clique para valor fixo"
            : "Dinâmico · clique para valor fixo"
      }
      onClick={isFixed ? switchToDynamic : switchToFixed}
      className={cn(
        "flex shrink-0 items-center justify-center rounded-md border transition-colors",
        toggleSize,
        isFixed
          ? "border-border bg-background text-muted-foreground hover:text-foreground"
          : compact
            ? "border-primary/40 bg-primary/10 text-primary"
            : "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400",
        disabled && "pointer-events-none opacity-50",
      )}
    >
      {isFixed ? (
        <TextCursorInput className="size-3.5" />
      ) : compact ? (
        <Link2 className="size-3.5" />
      ) : (
        <Braces className="size-3.5" />
      )}
    </button>
  )

  // ─── Compact: single-chip render ─────────────────────────────────────────────

  if (compact) {
    const fieldName = extractFieldName(value.template)
    return (
      <div className="flex flex-1 flex-col gap-1 min-w-0">
        <div className="flex items-center gap-1.5 min-w-0">
          {toggleBtn}
          {/* Chip pill */}
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-md bg-primary/12 px-2 font-semibold text-primary",
              size === "sm" ? "h-6 text-[10px]" : "h-7 text-[11px]",
            )}
          >
            {fieldName}
          </span>
          {/* Expand to add transforms */}
          {allowTransforms && !disabled && (
            <button
              type="button"
              onClick={() => setShowFull(true)}
              className="flex items-center gap-0.5 text-[10px] text-muted-foreground/60 transition-colors hover:text-primary"
            >
              <Plus className="size-2.5" />
              transformação
            </button>
          )}
        </div>
      </div>
    )
  }

  // ─── Full render (fixed OR expanded dynamic) ──────────────────────────────────

  return (
    <div className="flex flex-1 flex-col gap-1.5 min-w-0">
      {/* Toggle + input row */}
      <div className="flex items-start gap-1.5">
        {toggleBtn}

        <div className="flex-1 min-w-0">
          {isFixed ? (
            <input
              type="text"
              value={value.value}
              onChange={(e) => handleFixedChange(e.target.value)}
              onDragOver={(e) => {
                const hasField = e.dataTransfer.types.includes("application/x-shift-field")
                const hasRef = useFieldRef && e.dataTransfer.types.includes("application/x-shift-field-ref")
                if (hasField || hasRef) {
                  e.preventDefault()
                  e.dataTransfer.dropEffect = "copy"
                }
              }}
              onDrop={handleFixedDrop}
              placeholder={placeholder ?? "valor fixo..."}
              disabled={disabled}
              className={cn(
                inputH,
                "w-full rounded-md border border-input bg-background px-2 text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary",
                disabled && "opacity-50",
              )}
            />
          ) : (
            <ExpressionEditor
              template={value.template}
              onChange={handleTemplateChange}
              upstreamFields={upstreamFields}
              allowVariables={allowVariables}
              useFieldRef={useFieldRef}
              placeholder={placeholder ?? "Arraste campos ou digite expressão..."}
              size={size}
              trailingControls={
                allowTransforms ? (
                  <TransformsPicker
                    transforms={transforms}
                    onChange={handleTransformsChange}
                    disabled={disabled}
                  />
                ) : undefined
              }
            />
          )}
        </div>
      </div>

      {/* Transforms bar (dynamic only) */}
      {isDynamic && allowTransforms && (
        <TransformsBar
          transforms={transforms}
          onChange={handleTransformsChange}
          disabled={disabled}
        />
      )}
    </div>
  )
}

export default ValueInput
