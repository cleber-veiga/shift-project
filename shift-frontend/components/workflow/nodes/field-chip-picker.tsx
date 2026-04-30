"use client"

/**
 * FieldChipPicker — entrada compartilhada que segue o padrão visual de
 * "campo linkado" da plataforma:
 *   - Quando há valor: ícone <Link2/> ao lado de um chip violeta com o nome
 *     do campo. Click no chip volta para o modo de edição (dropdown).
 *   - Quando vazio: dropdown com colunas do upstream (ou input livre como
 *     fallback quando o schema ainda não está disponível).
 *   - Drag-drop de campos do schema lateral funciona em ambos os estados.
 *
 * Inspirado no compact mode do `ValueInput` (usado pelo Mapper). Centralizar
 * aqui garante consistência entre nós de Agregador, Ordenar, e quaisquer
 * outros que precisem de uma entrada "uma coluna".
 */

import { useEffect, useState } from "react"
import { Asterisk, Link2 } from "lucide-react"
import { cn } from "@/lib/utils"

interface FieldChipPickerProps {
  value: string
  onChange: (next: string) => void
  upstreamFields: string[]
  /** Texto exibido no placeholder do dropdown / input livre. */
  placeholder?: string
  /** Quando true, valor vazio é estado válido renderizado como chip neutro
   *  com asterisco — usado por COUNT(*) no Agregador, por exemplo. */
  allowAllRows?: boolean
  /** Texto exibido no chip neutro quando ``allowAllRows`` está ativo e o
   *  valor está vazio. Default: "todas as linhas". */
  allRowsLabel?: string
}

export function FieldChipPicker({
  value,
  onChange,
  upstreamFields,
  placeholder = "selecionar coluna",
  allowAllRows = false,
  allRowsLabel = "todas as linhas",
}: FieldChipPickerProps) {
  const hasChip = !!value || allowAllRows
  const [editing, setEditing] = useState(!hasChip)

  // Sai do modo edição quando um valor é definido externamente (ex.: drag-drop
  // do schema, ou pai mudou o valor por outra interação).
  useEffect(() => {
    if (value) setEditing(false)
  }, [value])

  const handleDragOver = (e: React.DragEvent) => {
    if (e.dataTransfer.types.includes("application/x-shift-field")) {
      e.preventDefault()
      e.dataTransfer.dropEffect = "copy"
    }
  }
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    const f = e.dataTransfer.getData("application/x-shift-field")
    if (f) {
      onChange(f)
      setEditing(false)
    }
  }

  // ── Modo chip ────────────────────────────────────────────────────────────
  if (!editing && hasChip) {
    if (value) {
      return (
        <div
          className="flex min-w-0 items-center gap-1.5"
          onDragOver={handleDragOver}
          onDrop={handleDrop}
        >
          <span
            className="flex size-7 shrink-0 items-center justify-center rounded-md border border-primary/40 bg-primary/10 text-primary"
            title="Campo linkado"
          >
            <Link2 className="size-3.5" />
          </span>
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="inline-flex h-7 min-w-0 items-center rounded-md bg-primary/12 px-2 text-[11px] font-semibold text-primary transition-colors hover:bg-primary/20"
            title="Clique para alterar"
          >
            <span className="truncate">{value}</span>
          </button>
        </div>
      )
    }
    // allowAllRows + vazio: chip neutro
    return (
      <div
        className="flex min-w-0 items-center gap-1.5"
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        <span
          className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border bg-muted/60 text-muted-foreground"
          title="Sem campo específico"
        >
          <Asterisk className="size-3.5" />
        </span>
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="inline-flex h-7 min-w-0 items-center rounded-md bg-muted/60 px-2 text-[11px] font-semibold italic text-muted-foreground transition-colors hover:bg-muted"
          title="Clique para escolher uma coluna"
        >
          {allRowsLabel}
        </button>
      </div>
    )
  }

  // ── Modo edição: dropdown ou input livre ─────────────────────────────────
  if (upstreamFields.length > 0) {
    return (
      <select
        autoFocus
        value={value}
        onChange={(e) => {
          const v = e.target.value
          onChange(v)
          if (v || allowAllRows) setEditing(false)
        }}
        onBlur={() => {
          if (value || allowAllRows) setEditing(false)
        }}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
      >
        <option value="">
          {allowAllRows ? `* (${allRowsLabel})` : `-- ${placeholder} --`}
        </option>
        {upstreamFields.map((f) => (
          <option key={f} value={f}>
            {f}
          </option>
        ))}
      </select>
    )
  }
  return (
    <input
      type="text"
      autoFocus
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onBlur={() => {
        if (value || allowAllRows) setEditing(false)
      }}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      placeholder={allowAllRows ? `* = ${allRowsLabel}` : placeholder}
      className={cn(
        "h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary",
        "placeholder:text-muted-foreground/60",
      )}
    />
  )
}
