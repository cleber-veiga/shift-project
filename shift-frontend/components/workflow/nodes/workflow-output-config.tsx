"use client"

import { LogOut, Plus, Trash2 } from "lucide-react"

const IDENTIFIER_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/

interface MappingRow {
  output_name: string
  source_path: string
}

interface WorkflowOutputConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

function mappingToRows(value: Record<string, string> | undefined): MappingRow[] {
  if (!value) return []
  return Object.entries(value).map(([output_name, source_path]) => ({
    output_name,
    source_path,
  }))
}

function rowsToMapping(rows: MappingRow[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (const row of rows) {
    const key = row.output_name.trim()
    if (!key) continue
    out[key] = row.source_path
  }
  return out
}

export function WorkflowOutputConfig({ data, onUpdate }: WorkflowOutputConfigProps) {
  const rows = mappingToRows(data.mapping as Record<string, string> | undefined)

  function update(next: MappingRow[]) {
    onUpdate({ ...data, mapping: rowsToMapping(next) })
  }

  function addRow() {
    update([...rows, { output_name: "", source_path: "" }])
  }

  function updateRow(index: number, patch: Partial<MappingRow>) {
    update(rows.map((r, i) => (i === index ? { ...r, ...patch } : r)))
  }

  function removeRow(index: number) {
    update(rows.filter((_, i) => i !== index))
  }

  const names = rows.map((r) => r.output_name.trim())
  const duplicates = new Set(
    names.filter((n, i) => n && names.indexOf(n) !== i),
  )
  const invalidNames = new Set(
    names.filter((n) => n && !IDENTIFIER_PATTERN.test(n)),
  )

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-dashed border-emerald-500/30 bg-emerald-500/5 p-3">
        <div className="mb-1.5 flex items-center gap-2">
          <LogOut className="size-3.5 text-emerald-600 dark:text-emerald-400" />
          <p className="text-xs font-medium text-emerald-700 dark:text-emerald-300">
            Saída do Workflow
          </p>
        </div>
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          Os valores mapeados abaixo compõem o objeto devolvido ao workflow pai
          que invocar este como sub-workflow. Os nomes declarados devem bater com
          os outputs do <span className="font-semibold">io_schema</span>.
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Mapeamento de saídas
          </label>
          <button
            type="button"
            onClick={addRow}
            className="flex items-center gap-1 text-[10px] font-medium text-primary transition-colors hover:text-primary/80"
          >
            <Plus className="size-3" />
            Adicionar saída
          </button>
        </div>

        {rows.length === 0 ? (
          <p className="rounded-md border border-dashed border-border bg-muted/30 px-3 py-4 text-center text-[11px] text-muted-foreground">
            Nenhuma saída mapeada. Clique em "Adicionar saída" para declarar o
            primeiro par.
          </p>
        ) : (
          <div className="space-y-1.5">
            <div className="grid grid-cols-[1fr_1.3fr_auto] gap-2 px-0.5">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Nome
              </span>
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Origem (path/template)
              </span>
              <span />
            </div>
            {rows.map((row, i) => {
              const nameInvalid =
                invalidNames.has(row.output_name.trim()) ||
                duplicates.has(row.output_name.trim())
              return (
                <div
                  key={i}
                  className="grid grid-cols-[1fr_1.3fr_auto] items-center gap-2"
                >
                  <input
                    type="text"
                    aria-label="Nome do output"
                    aria-invalid={nameInvalid}
                    value={row.output_name}
                    onChange={(e) =>
                      updateRow(i, { output_name: e.target.value })
                    }
                    placeholder="nome_output"
                    className={`h-7 rounded-md border bg-background px-2 font-mono text-xs outline-none focus:ring-1 ${
                      nameInvalid
                        ? "border-destructive focus:ring-destructive"
                        : "border-input focus:ring-primary"
                    }`}
                  />
                  <input
                    type="text"
                    aria-label="Origem"
                    value={row.source_path}
                    onChange={(e) =>
                      updateRow(i, { source_path: e.target.value })
                    }
                    placeholder="upstream.node_id.campo"
                    className="h-7 rounded-md border border-input bg-background px-2 font-mono text-xs outline-none focus:ring-1 focus:ring-primary"
                  />
                  <button
                    type="button"
                    aria-label="Remover saída"
                    onClick={() => removeRow(i)}
                    className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2 className="size-3" />
                  </button>
                </div>
              )
            })}
          </div>
        )}

        {duplicates.size > 0 && (
          <p className="text-[10px] text-destructive">
            Nomes duplicados: {Array.from(duplicates).join(", ")}
          </p>
        )}
        {invalidNames.size > 0 && (
          <p className="text-[10px] text-destructive">
            Nomes inválidos ({Array.from(invalidNames).join(", ")}). Use apenas
            letras, números e underscore (não pode começar com número).
          </p>
        )}
        <p className="text-[10px] text-muted-foreground">
          Origem aceita dotted path (ex:{" "}
          <code className="font-mono">upstream.node_id.campo</code>) ou template
          Jinja (ex: <code className="font-mono">{"{{ item.id }}"}</code>).
        </p>
      </div>
    </div>
  )
}
