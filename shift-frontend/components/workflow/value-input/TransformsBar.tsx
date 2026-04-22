"use client"

import { cn } from "@/lib/utils"
import type { TransformEntry, TransformKind } from "@/lib/workflow/parameter-value"

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
]

// ─── Component ────────────────────────────────────────────────────────────────

export function TransformsBar({ transforms, onChange, disabled }: TransformsBarProps) {
  function isActive(kind: TransformKind): boolean {
    return transforms.some((e) => e.kind === kind)
  }

  function toggleTransform(def: TransformDef) {
    if (isActive(def.kind)) {
      onChange(transforms.filter((e) => e.kind !== def.kind))
    } else if (def.paramDefs?.length) {
      const defaultArgs: Record<string, string | number> = {}
      for (const pd of def.paramDefs) defaultArgs[pd.key] = ""
      onChange([...transforms, { kind: def.kind, args: defaultArgs }])
    } else {
      onChange([...transforms, { kind: def.kind }])
    }
  }

  function updateParam(kind: TransformKind, key: string, value: string | number) {
    onChange(
      transforms.map((e) =>
        e.kind === kind ? { ...e, args: { ...(e.args ?? {}), [key]: value } } : e
      )
    )
  }

  const activeWithParams = transforms.filter(
    (e) => TRANSFORM_DEFS.find((d) => d.kind === e.kind)?.paramDefs?.length
  )

  return (
    <div className="space-y-1.5 pt-0.5">
      {/* Chips row */}
      <div className="flex flex-wrap gap-1">
        {TRANSFORM_DEFS.map((def) => (
          <button
            key={def.kind}
            type="button"
            title={def.description}
            disabled={disabled}
            onClick={() => toggleTransform(def)}
            className={cn(
              "rounded-full border px-2 py-0.5 text-[10px] font-medium transition-colors",
              isActive(def.kind)
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-muted-foreground/60 hover:border-foreground/30 hover:text-foreground",
              disabled && "pointer-events-none opacity-50",
            )}
          >
            {def.label}
          </button>
        ))}
      </div>

      {/* Param inputs for active parametrized transforms */}
      {activeWithParams.map((entry) => {
        const def = TRANSFORM_DEFS.find((d) => d.kind === entry.kind)
        if (!def?.paramDefs?.length) return null
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

export default TransformsBar
