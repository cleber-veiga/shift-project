"use client"

import { useEffect, useRef, useState } from "react"
import { Plus, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { Tooltip } from "@/components/ui/tooltip"
import type {
  MapValuesPair,
  TransformEntry,
  TransformKind,
} from "@/lib/workflow/parameter-value"

// ─── Types ────────────────────────────────────────────────────────────────────

export interface TransformsBarProps {
  transforms: TransformEntry[]
  onChange: (next: TransformEntry[]) => void
  disabled?: boolean
}

// ─── Transform catalogue ──────────────────────────────────────────────────────

interface ParamDef {
  key: string
  label: string
  placeholder?: string
  type?: "text" | "number"
}

interface TransformDef {
  kind: TransformKind
  label: string
  description: string
  paramDefs?: ParamDef[]
  /** Quando true, indica que o transform tem UI customizada de parâmetros
      (renderizada por componente próprio em ``TransformsBar``) e não usa o
      grid padrão de ``paramDefs``. Mantém ``hasParams`` semântico para o
      catálogo sem precisar enumerar paramDefs no formato fixo. */
  hasCustomParams?: boolean
}

const TRANSFORM_DEFS: TransformDef[] = [
  {
    kind: "upper",
    label: "Maiúsculo",
    description: 'Converte todos os caracteres para maiúsculo.\nEx: "silva" → "SILVA"',
  },
  {
    kind: "lower",
    label: "Minúsculo",
    description: 'Converte todos os caracteres para minúsculo.\nEx: "SILVA" → "silva"',
  },
  {
    kind: "trim",
    label: "Sem espaços",
    description: 'Remove espaços no início e fim.\nEx: "  abc  " → "abc"',
  },
  {
    kind: "digits_only",
    label: "Somente dígitos",
    description: 'Remove tudo que não for número.\nEx: "(54) 9988-9051" → "54999889051"',
  },
  {
    kind: "remove_specials",
    label: "Remover especiais",
    description: 'Remove caracteres especiais, mantendo letras, números e espaços.\nEx: "R$ 1.500,00" → "R 150000"',
  },
  {
    kind: "replace",
    label: "Substituir",
    description: 'Substitui um trecho por outro.\nEx: de "-" por "" em "123-456" → "123456"',
    paramDefs: [
      { key: "old", label: "De",  placeholder: "texto a substituir" },
      { key: "new", label: "Por", placeholder: "vazio = remover"    },
    ],
  },
  {
    kind: "truncate",
    label: "Truncar",
    description: 'Limita o valor a um número máximo de caracteres.\nEx: tamanho 3 em "ABCDEF" → "ABC"',
    paramDefs: [
      { key: "length", label: "Tamanho", placeholder: "ex: 3", type: "number" },
    ],
  },
  {
    kind: "remove_chars",
    label: "Remover caracteres",
    description: 'Remove do valor todas as ocorrências dos caracteres especificados.\nEx: chars "()-" em "(54) 9988-9051" → "54 99889051"',
    paramDefs: [
      { key: "chars", label: "Caracteres", placeholder: "ex: ( ) - / ." },
    ],
  },
  {
    kind: "default",
    label: "Padrão",
    description:
      'Substitui valores ausentes por defaults.\nEx: NULL → "N", string vazia → "3". Os campos são independentes — preencha apenas o que precisa tratar.',
    hasCustomParams: true,
  },
  {
    kind: "map_values",
    label: "De-Para",
    description:
      'Mapeia valores específicos para outros, em lote.\nEx: "S" → "Sim", "N" → "Não", "T" → "Talvez". Quando nenhuma equivalência casa, mantém o valor original (ou usa o fallback configurado).',
    hasCustomParams: true,
  },
]

// ─── Picker (inline button) ──────────────────────────────────────────────────

export interface TransformsPickerProps {
  transforms: TransformEntry[]
  onChange: (next: TransformEntry[]) => void
  disabled?: boolean
}

/**
 * Botão compacto + dropdown que adiciona transforms à lista. Renderizado
 * inline com outros pickers (ex.: ``Variáveis ▾`` no ExpressionEditor) para
 * dar consistência visual ao usuário. A bar de chips ativos + inputs de
 * parâmetros segue como ``TransformsBar``, exibida abaixo do editor.
 */
export function TransformsPicker({
  transforms,
  onChange,
  disabled,
}: TransformsPickerProps) {
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)

  // Fecha ao clicar fora ou pressionar ESC. Sem portal nem setTimeout —
  // a estrutura é a mesma do botão ``Variáveis ▾`` do ExpressionEditor,
  // que funciona dentro do mesmo modal sem problemas de clipping.
  useEffect(() => {
    if (!open) return
    function onMouseDown(e: MouseEvent) {
      if (
        wrapperRef.current &&
        !wrapperRef.current.contains(e.target as globalThis.Node)
      ) {
        setOpen(false)
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false)
    }
    document.addEventListener("mousedown", onMouseDown)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onMouseDown)
      document.removeEventListener("keydown", onKey)
    }
  }, [open])

  function isActive(kind: TransformKind): boolean {
    return transforms.some((e) => e.kind === kind)
  }

  function addTransform(def: TransformDef) {
    if (isActive(def.kind)) return
    if (def.paramDefs?.length) {
      const defaultArgs: Record<string, string | number> = {}
      for (const pd of def.paramDefs) defaultArgs[pd.key] = ""
      onChange([...transforms, { kind: def.kind, args: defaultArgs }])
    } else if (def.kind === "default") {
      onChange([
        ...transforms,
        { kind: "default", args: { null_value: "", empty_value: "" } },
      ])
    } else if (def.kind === "map_values") {
      // Inicia com uma linha vazia pra dar ponto de partida ao usuário.
      const initialPairs: MapValuesPair[] = [{ from: "", to: "" }]
      onChange([
        ...transforms,
        { kind: "map_values", args: { pairs: initialPairs, fallback: "" } },
      ])
    } else {
      onChange([...transforms, { kind: def.kind }])
    }
    setOpen(false)
  }

  return (
    <div ref={wrapperRef} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "rounded bg-primary/10 px-1.5 py-px text-[9px] font-medium text-primary transition-colors hover:bg-primary/20",
          disabled && "pointer-events-none opacity-50",
        )}
        aria-label="Adicionar transformação"
      >
        + Transformação ▾
      </button>
      {open && (
        <div className="absolute left-0 top-full z-30 mt-1 min-w-[200px] max-h-72 overflow-y-auto rounded-md border border-border bg-popover p-1 shadow-md">
          {TRANSFORM_DEFS.map((def) => {
            const active = isActive(def.kind)
            // ``onMouseDown`` em vez de ``onClick`` evita uma classe de
            // bugs onde o handler de clique do documento ou um blur no
            // editor (contentEditable do ExpressionEditor) fecharia o
            // menu antes do click chegar — mousedown dispara antes de
            // qualquer um deles. ``preventDefault`` impede o blur do
            // editor que mata o caret durante o pick.
            const tooltipText = def.description.replace(/\n/g, " · ")
            return (
              <Tooltip key={def.kind} text={tooltipText}>
                <button
                  type="button"
                  disabled={active}
                  onMouseDown={(e) => {
                    e.preventDefault()
                    if (!active) addTransform(def)
                  }}
                  className={cn(
                    "flex w-full items-start gap-2 rounded px-2 py-1.5 text-left transition-colors",
                    active
                      ? "cursor-not-allowed text-muted-foreground/40"
                      : "hover:bg-muted",
                  )}
                >
                  <span
                    className={cn(
                      "mt-px shrink-0 text-[10px] font-semibold",
                      active ? "text-primary/40" : "text-primary",
                    )}
                  >
                    {def.label}
                  </span>
                  {active && (
                    <span className="ml-auto shrink-0 text-[9px] uppercase tracking-wide text-muted-foreground/60">
                      já adicionado
                    </span>
                  )}
                </button>
              </Tooltip>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ─── Component ────────────────────────────────────────────────────────────────

export function TransformsBar({ transforms, onChange, disabled }: TransformsBarProps) {
  function removeTransform(kind: TransformKind) {
    onChange(transforms.filter((e) => e.kind !== kind))
  }

  function updateParam(kind: TransformKind, key: string, value: string | number) {
    onChange(
      transforms.map((e) =>
        e.kind === kind ? { ...e, args: { ...(e.args ?? {}), [key]: value } } : e
      )
    )
  }

  function updatePairs(kind: TransformKind, pairs: MapValuesPair[]) {
    onChange(
      transforms.map((e) =>
        e.kind === kind ? { ...e, args: { ...(e.args ?? {}), pairs } } : e
      )
    )
  }

  const activeWithParams = transforms.filter((e) => {
    const def = TRANSFORM_DEFS.find((d) => d.kind === e.kind)
    return Boolean(def?.paramDefs?.length || def?.hasCustomParams)
  })

  // Mantém os ativos na ordem em que foram adicionados, mas resolve labels
  // a partir do catálogo para não depender da ordem dele.
  const activeEntries = transforms
    .map((entry) => {
      const def = TRANSFORM_DEFS.find((d) => d.kind === entry.kind)
      return def ? { entry, def } : null
    })
    .filter((x): x is { entry: TransformEntry; def: TransformDef } => x !== null)

  // Sem chips ativos e sem params: a bar fica vazia. Não rendariza nada
  // pra evitar margem fantasma sob o editor — o picker já vive ao lado
  // de "Variáveis ▾" via ``TransformsPicker``.
  if (activeEntries.length === 0) return null

  return (
    <div className="space-y-1.5 pt-0.5">
      {/* Chips dos transforms já adicionados — cada um com botão X
          para remover. Mantém a ordem de aplicação visível para o
          usuário (transforms são compostos da esquerda pra direita). */}
      <div className="flex flex-wrap items-center gap-1">
        {activeEntries.map(({ entry, def }) => (
          <span
            key={entry.kind}
            title={def.description}
            className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/10 px-1.5 py-px text-[10px] font-medium text-primary"
          >
            {def.label}
            <button
              type="button"
              disabled={disabled}
              onClick={() => removeTransform(entry.kind)}
              className="flex size-3 items-center justify-center rounded-sm text-primary/70 transition-colors hover:bg-primary/20 hover:text-primary disabled:pointer-events-none disabled:opacity-50"
              aria-label={`Remover ${def.label}`}
            >
              <X className="size-2.5" strokeWidth={2.5} />
            </button>
          </span>
        ))}
      </div>

      {/* Param inputs for active parametrized transforms */}
      {activeWithParams.map((entry) => {
        const def = TRANSFORM_DEFS.find((d) => d.kind === entry.kind)
        if (!def) return null

        // Custom UIs — fora do grid padrão de ``paramDefs``.
        if (entry.kind === "default") {
          return (
            <DefaultParamsBlock
              key={entry.kind}
              def={def}
              entry={entry}
              disabled={disabled}
              onChange={(key, value) => updateParam(entry.kind, key, value)}
            />
          )
        }
        if (entry.kind === "map_values") {
          const rawPairs = entry.args?.pairs
          const pairs: MapValuesPair[] = Array.isArray(rawPairs)
            ? (rawPairs as MapValuesPair[])
            : []
          return (
            <MapValuesParamsBlock
              key={entry.kind}
              def={def}
              pairs={pairs}
              fallback={String(entry.args?.fallback ?? "")}
              disabled={disabled}
              onPairsChange={(next) => updatePairs(entry.kind, next)}
              onFallbackChange={(v) => updateParam(entry.kind, "fallback", v)}
            />
          )
        }

        // Caminho padrão: paramDefs em grid de inputs.
        if (!def.paramDefs?.length) return null
        return (
          <div
            key={entry.kind}
            className="rounded-md border border-primary/20 bg-primary/5 px-2.5 py-2 space-y-1.5"
          >
            <span className="text-[10px] font-semibold text-primary">{def.label}</span>
            <div className="flex flex-wrap gap-x-3 gap-y-1.5">
              {def.paramDefs.map((pd) => (
                <div key={pd.key} className="flex min-w-0 flex-1 items-center gap-1.5">
                  <span className="shrink-0 text-[10px] text-muted-foreground">{pd.label}:</span>
                  <input
                    type={pd.type === "number" ? "number" : "text"}
                    value={String(entry.args?.[pd.key] ?? "")}
                    onChange={(e) =>
                      updateParam(
                        entry.kind,
                        pd.key,
                        pd.type === "number" ? Number(e.target.value) : e.target.value
                      )
                    }
                    placeholder={pd.placeholder}
                    disabled={disabled}
                    className="h-5 min-w-0 flex-1 rounded border border-input bg-background px-1.5 text-[10px] text-foreground outline-none placeholder:text-muted-foreground/60 focus:ring-1 focus:ring-primary"
                  />
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ─── Custom param blocks ──────────────────────────────────────────────────────

function DefaultParamsBlock({
  def,
  entry,
  disabled,
  onChange,
}: {
  def: TransformDef
  entry: TransformEntry
  disabled?: boolean
  onChange: (key: string, value: string) => void
}) {
  return (
    <div className="rounded-md border border-primary/20 bg-primary/5 px-2.5 py-2 space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold text-primary">{def.label}</span>
        <span className="text-[9px] italic text-muted-foreground">
          deixe em branco pra ignorar o caso
        </span>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1.5">
        <div className="flex min-w-0 flex-1 items-center gap-1.5">
          <span className="shrink-0 text-[10px] text-muted-foreground">Se NULL:</span>
          <input
            type="text"
            value={String(entry.args?.null_value ?? "")}
            onChange={(e) => onChange("null_value", e.target.value)}
            placeholder='ex: "N", "Sem informação"'
            disabled={disabled}
            className="h-5 min-w-0 flex-1 rounded border border-input bg-background px-1.5 text-[10px] text-foreground outline-none placeholder:text-muted-foreground/60 focus:ring-1 focus:ring-primary"
          />
        </div>
        <div className="flex min-w-0 flex-1 items-center gap-1.5">
          <span className="shrink-0 text-[10px] text-muted-foreground">Se vazio:</span>
          <input
            type="text"
            value={String(entry.args?.empty_value ?? "")}
            onChange={(e) => onChange("empty_value", e.target.value)}
            placeholder='ex: "0", "—"'
            disabled={disabled}
            className="h-5 min-w-0 flex-1 rounded border border-input bg-background px-1.5 text-[10px] text-foreground outline-none placeholder:text-muted-foreground/60 focus:ring-1 focus:ring-primary"
          />
        </div>
      </div>
    </div>
  )
}

function MapValuesParamsBlock({
  def,
  pairs,
  fallback,
  disabled,
  onPairsChange,
  onFallbackChange,
}: {
  def: TransformDef
  pairs: MapValuesPair[]
  fallback: string
  disabled?: boolean
  onPairsChange: (next: MapValuesPair[]) => void
  onFallbackChange: (v: string) => void
}) {
  const list = pairs.length > 0 ? pairs : [{ from: "", to: "" }]

  function updatePair(idx: number, patch: Partial<MapValuesPair>) {
    onPairsChange(
      list.map((p, i) => (i === idx ? { ...p, ...patch } : p)),
    )
  }
  function addRow() {
    onPairsChange([...list, { from: "", to: "" }])
  }
  function removeRow(idx: number) {
    if (list.length <= 1) {
      // Sempre mantém pelo menos uma linha pra dar UI consistente.
      onPairsChange([{ from: "", to: "" }])
      return
    }
    onPairsChange(list.filter((_, i) => i !== idx))
  }

  return (
    <div className="rounded-md border border-primary/20 bg-primary/5 px-2.5 py-2 space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold text-primary">{def.label}</span>
        <span className="text-[9px] italic text-muted-foreground">
          quando não casar nenhum: usa o original
        </span>
      </div>
      <div className="space-y-1">
        {list.map((pair, idx) => (
          <div key={idx} className="flex items-center gap-1.5">
            <input
              type="text"
              value={pair.from}
              onChange={(e) => updatePair(idx, { from: e.target.value })}
              placeholder='valor "de"'
              disabled={disabled}
              className="h-5 min-w-0 flex-1 rounded border border-input bg-background px-1.5 text-[10px] text-foreground outline-none placeholder:text-muted-foreground/60 focus:ring-1 focus:ring-primary"
            />
            <span className="shrink-0 text-[10px] text-muted-foreground">→</span>
            <input
              type="text"
              value={pair.to}
              onChange={(e) => updatePair(idx, { to: e.target.value })}
              placeholder='valor "para"'
              disabled={disabled}
              className="h-5 min-w-0 flex-1 rounded border border-input bg-background px-1.5 text-[10px] text-foreground outline-none placeholder:text-muted-foreground/60 focus:ring-1 focus:ring-primary"
            />
            <button
              type="button"
              onClick={() => removeRow(idx)}
              disabled={disabled}
              className="flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive disabled:pointer-events-none disabled:opacity-50"
              aria-label="Remover linha"
            >
              <X className="size-3" />
            </button>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          onClick={addRow}
          disabled={disabled}
          className="inline-flex items-center gap-1 rounded px-1.5 py-px text-[10px] font-medium text-primary transition-colors hover:bg-primary/10 disabled:pointer-events-none disabled:opacity-50"
        >
          <Plus className="size-2.5" />
          Adicionar equivalência
        </button>
        <div className="flex min-w-0 flex-1 items-center gap-1.5 sm:max-w-[60%]">
          <span className="shrink-0 text-[10px] text-muted-foreground">
            Fallback:
          </span>
          <input
            type="text"
            value={fallback}
            onChange={(e) => onFallbackChange(e.target.value)}
            placeholder="vazio = mantém valor original"
            disabled={disabled}
            className="h-5 min-w-0 flex-1 rounded border border-input bg-background px-1.5 text-[10px] text-foreground outline-none placeholder:text-muted-foreground/60 focus:ring-1 focus:ring-primary"
          />
        </div>
      </div>
    </div>
  )
}

export default TransformsBar
