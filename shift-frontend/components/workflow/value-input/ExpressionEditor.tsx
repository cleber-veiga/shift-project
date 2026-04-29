"use client"

import { useRef, useState } from "react"
import { cn } from "@/lib/utils"
import type { UpstreamField } from "@/lib/workflow/parameter-value"

// ─── Types ────────────────────────────────────────────────────────────────────

export interface ExpressionEditorProps {
  template: string
  onChange: (template: string) => void
  upstreamFields: UpstreamField[]
  allowVariables?: boolean
  /** When true, drag-drop prefers x-shift-field-ref (nodeId.field) over bare field name. */
  useFieldRef?: boolean
  placeholder?: string
  size?: "sm" | "md"
  /** Conteúdo extra renderizado na barra inferior, depois do botão
      ``Variáveis ▾``. Usado pelo ValueInput para encaixar o
      ``TransformsPicker`` lado-a-lado e não em uma linha separada. */
  trailingControls?: React.ReactNode
}

// ─── Constants ────────────────────────────────────────────────────────────────

interface SystemVar {
  token: string
  label: string
  description: string
}

export const SYSTEM_VARS: SystemVar[] = [
  { token: "$now",   label: "$now",   description: "Data e hora atual"      },
  { token: "$today", label: "$today", description: "Data atual (sem hora)"  },
]

// ─── Helpers ──────────────────────────────────────────────────────────────────

const TOKEN_RE = /(\{\{[^}]+\}\}|\$[a-zA-Z_]+)/g

export type ExprToken = { type: "text" | "field" | "sysvar"; value: string }

export function parseExprTokens(template: string): ExprToken[] {
  const result: ExprToken[] = []
  let last = 0
  let m: RegExpExecArray | null
  const re = new RegExp(TOKEN_RE.source, "g")
  while ((m = re.exec(template)) !== null) {
    if (m.index > last) result.push({ type: "text", value: template.slice(last, m.index) })
    const tok = m[1]
    if (tok.startsWith("{{")) {
      result.push({ type: "field", value: tok.slice(2, -2) })
    } else {
      result.push({ type: "sysvar", value: tok })
    }
    last = m.index + tok.length
  }
  if (last < template.length) result.push({ type: "text", value: template.slice(last) })
  return result
}

function chipClass(type: "field" | "sysvar"): string {
  return type === "field"
    ? "inline-flex items-center gap-0.5 rounded bg-primary/15 px-1 py-px mx-0.5 text-[10px] font-semibold text-primary align-baseline select-none cursor-default"
    : "inline-flex items-center gap-0.5 rounded bg-amber-500/15 px-1 py-px mx-0.5 text-[10px] font-semibold text-amber-600 dark:text-amber-400 align-baseline select-none cursor-default"
}

function chipAriaLabel(tok: ExprToken): string {
  if (tok.type === "sysvar") return `Variável ${tok.value} — pressione Delete para remover`
  if (tok.value.startsWith("vars.")) return `Variável ${tok.value.slice(5)} — pressione Delete para remover`
  return `Campo ${tok.value} — pressione Delete para remover`
}

function renderTokenToChip(el: HTMLElement, tok: ExprToken) {
  const chip = document.createElement("span")
  chip.contentEditable = "false"
  chip.dataset.token = tok.type === "field" ? `{{${tok.value}}}` : tok.value
  chip.className = chipClass(tok.type as "field" | "sysvar")
  chip.textContent = tok.value
  chip.tabIndex = 0
  chip.setAttribute("aria-label", chipAriaLabel(tok))
  el.appendChild(chip)
}

function renderToDOM(el: HTMLElement, template: string) {
  el.innerHTML = ""
  for (const tok of parseExprTokens(template)) {
    if (tok.type === "text") {
      el.appendChild(document.createTextNode(tok.value))
    } else {
      renderTokenToChip(el, tok)
    }
  }
}

function serialize(el: HTMLElement): string {
  let out = ""
  for (const node of Array.from(el.childNodes)) {
    if (node.nodeType === Node.TEXT_NODE) {
      out += node.textContent ?? ""
    } else if (node instanceof HTMLElement && node.dataset.token) {
      out += node.dataset.token
    }
  }
  return out
}

// ─── Component ────────────────────────────────────────────────────────────────

export function ExpressionEditor({
  template,
  onChange,
  upstreamFields,
  allowVariables = true,
  useFieldRef = false,
  placeholder = "Arraste campos ou digite expressão...",
  size = "md",
  trailingControls,
}: ExpressionEditorProps) {
  const editRef = useRef<HTMLDivElement>(null)
  const lastSerialized = useRef(template)
  const [showVars, setShowVars] = useState(false)
  const [isDragOver, setIsDragOver] = useState(false)

  // Sync external value → DOM when it changes
  if (editRef.current && template !== lastSerialized.current) {
    renderToDOM(editRef.current, template)
    lastSerialized.current = template
  }

  function handleRef(el: HTMLDivElement | null) {
    ;(editRef as React.MutableRefObject<HTMLDivElement | null>).current = el
    if (el && !el.hasChildNodes()) {
      renderToDOM(el, template)
      lastSerialized.current = template
    }
  }

  function handleInput() {
    if (!editRef.current) return
    const serialized = serialize(editRef.current)
    lastSerialized.current = serialized
    onChange(serialized)
  }

  function insertAtCursor(token: string) {
    const el = editRef.current
    if (!el) return
    el.focus()
    const sel = window.getSelection()
    if (!sel || sel.rangeCount === 0) return
    const range = sel.getRangeAt(0)
    range.deleteContents()

    const frag = document.createDocumentFragment()
    for (const tok of parseExprTokens(token)) {
      if (tok.type === "text") {
        frag.appendChild(document.createTextNode(tok.value))
      } else {
        const chip = document.createElement("span")
        chip.contentEditable = "false"
        chip.dataset.token = tok.type === "field" ? `{{${tok.value}}}` : tok.value
        chip.className = chipClass(tok.type as "field" | "sysvar")
        chip.textContent = tok.value
        chip.tabIndex = 0
        chip.setAttribute("aria-label", chipAriaLabel(tok))
        frag.appendChild(chip)
      }
    }
    frag.appendChild(document.createTextNode(" "))
    range.insertNode(frag)
    range.collapse(false)
    sel.removeAllRanges()
    sel.addRange(range)
    handleInput()
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    // Chip focused via Tab: Delete or Backspace removes it and returns focus to editor
    const target = e.target as HTMLElement
    if (
      target !== editRef.current &&
      target.dataset.token &&
      (e.key === "Delete" || e.key === "Backspace")
    ) {
      e.preventDefault()
      const parent = target.parentNode
      if (parent) {
        const idx = Array.from(parent.childNodes).indexOf(target as ChildNode)
        target.remove()
        // Place cursor where the chip was
        const sel = window.getSelection()
        const range = document.createRange()
        const afterChip = parent.childNodes[idx]
        if (afterChip) {
          range.setStart(afterChip, 0)
        } else {
          range.setStart(parent, parent.childNodes.length)
        }
        range.collapse(true)
        sel?.removeAllRanges()
        sel?.addRange(range)
        editRef.current?.focus()
      }
      handleInput()
      return
    }

    if (e.key !== "Backspace") return
    const sel = window.getSelection()
    if (!sel || sel.rangeCount === 0 || !sel.isCollapsed) return
    const range = sel.getRangeAt(0)
    const node = range.startContainer
    const offset = range.startOffset

    if (node.nodeType === Node.TEXT_NODE && offset === 0) {
      const prev = node.previousSibling
      if (prev instanceof HTMLElement && prev.dataset.token) {
        e.preventDefault()
        prev.remove()
        handleInput()
      }
    }
    if (node === editRef.current && offset > 0) {
      const child = node.childNodes[offset - 1]
      if (child instanceof HTMLElement && child.dataset.token) {
        e.preventDefault()
        child.remove()
        handleInput()
      }
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)
    if (useFieldRef) {
      const refRaw = e.dataTransfer.getData("application/x-shift-field-ref")
      if (refRaw) {
        try {
          const ref = JSON.parse(refRaw) as { nodeId?: string; field?: string }
          if (ref.nodeId && ref.field) {
            insertAtCursor(`{{${ref.nodeId}.${ref.field}}}`)
            return
          }
        } catch { /* fallthrough */ }
      }
    }
    const field = e.dataTransfer.getData("application/x-shift-field")
    if (field) insertAtCursor(`{{${field}}}`)
  }

  const minH = size === "sm" ? "min-h-[44px]" : "min-h-[60px]"
  const fieldLimit = size === "sm" ? 5 : 8

  return (
    <div className="space-y-1.5">
      {/* Editable area */}
      <div
        ref={handleRef}
        contentEditable
        suppressContentEditableWarning
        role="textbox"
        aria-multiline="true"
        aria-label={placeholder ?? "Expressão dinâmica"}
        onInput={handleInput}
        onKeyDown={handleKeyDown}
        onDragOver={(e) => {
          const hasField = e.dataTransfer.types.includes("application/x-shift-field")
          const hasRef = useFieldRef && e.dataTransfer.types.includes("application/x-shift-field-ref")
          if (!hasField && !hasRef) return
          e.preventDefault()
          e.dataTransfer.dropEffect = "copy"
          setIsDragOver(true)
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        data-placeholder={placeholder}
        className={cn(
          minH,
          "w-full rounded-md border bg-background px-2.5 py-2 text-xs text-foreground outline-none transition-colors",
          "focus:ring-1 focus:ring-primary",
          "empty:before:content-[attr(data-placeholder)] empty:before:text-muted-foreground/60",
          isDragOver ? "border-primary bg-primary/5" : "border-input",
        )}
        style={{ lineHeight: "1.7", whiteSpace: "pre-wrap", wordBreak: "break-word" }}
      />

      {/* Quick-insert bar */}
      <div className="flex flex-wrap items-center gap-1">
        {upstreamFields.slice(0, fieldLimit).map((f, fi) => (
          <button
            key={`${f.name}-${fi}`}
            type="button"
            aria-label={`Inserir campo ${f.name}`}
            onClick={() => insertAtCursor(`{{${f.name}}}`)}
            className="rounded bg-primary/10 px-1.5 py-px text-[9px] font-medium text-primary/70 transition-colors hover:bg-primary/20 hover:text-primary"
          >
            {f.name}
          </button>
        ))}
        {upstreamFields.length > fieldLimit && (
          <span className="text-[9px] text-muted-foreground/50">
            +{upstreamFields.length - fieldLimit}
          </span>
        )}

        {allowVariables && (
          <>
            <span className="mx-0.5 text-muted-foreground/20">|</span>
            <div className="relative">
              <button
                type="button"
                onClick={() => setShowVars(!showVars)}
                className="rounded bg-amber-500/10 px-1.5 py-px text-[9px] font-medium text-amber-600 dark:text-amber-400 transition-colors hover:bg-amber-500/20"
              >
                Variáveis ▾
              </button>
              {showVars && (
                <div className="absolute left-0 top-full z-20 mt-1 min-w-[140px] rounded-md border border-border bg-popover p-1 shadow-md">
                  {SYSTEM_VARS.map((v) => (
                    <button
                      key={v.token}
                      type="button"
                      onClick={() => { insertAtCursor(v.token); setShowVars(false) }}
                      className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[10px] transition-colors hover:bg-muted"
                    >
                      <span className="font-mono font-semibold text-amber-600 dark:text-amber-400">
                        {v.token}
                      </span>
                      <span className="text-muted-foreground">{v.description}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </>
        )}

        {trailingControls && (
          <>
            <span className="mx-0.5 text-muted-foreground/20">|</span>
            {trailingControls}
          </>
        )}
      </div>
    </div>
  )
}

export default ExpressionEditor
