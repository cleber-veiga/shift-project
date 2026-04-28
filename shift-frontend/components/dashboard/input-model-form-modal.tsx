"use client"

import { useEffect, useState } from "react"
import { ClipboardPaste, Plus, Trash2 } from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import { cn } from "@/lib/utils"
import {
  createInputModel,
  updateInputModel,
  type InputModel,
  type InputModelColumn,
  type InputModelColumnType,
  type InputModelFileType,
  type InputModelSheet,
} from "@/lib/auth"
import { useToast } from "@/lib/context/toast-context"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

// ─── Types ────────────────────────────────────────────────────────────────────

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  editing: InputModel | null
  workspaceId: string
  onSaved: () => void | Promise<void>
}

const COLUMN_TYPES: { value: InputModelColumnType; label: string }[] = [
  { value: "text", label: "Texto" },
  { value: "number", label: "Número" },
  { value: "integer", label: "Inteiro" },
  { value: "date", label: "Data" },
  { value: "datetime", label: "Data/Hora" },
  { value: "boolean", label: "Booleano" },
]

function emptyColumn(): InputModelColumn {
  return { name: "", type: "text", required: false }
}

function emptySheet(name = "Planilha1"): InputModelSheet {
  return { name, columns: [emptyColumn()] }
}

// Tipos validos conforme backend (app/schemas/input_model.py:ColumnType).
const VALID_COLUMN_TYPES: ReadonlyArray<InputModelColumnType> = [
  "text", "number", "integer", "date", "datetime", "boolean",
]

// Mapa de tipos legados — modelos criados em versoes anteriores podiam
// ter "string", "decimal", etc. Normalizamos no carregamento pra que o
// PUT subsequente passe pelo Pydantic estrito do backend.
const LEGACY_TYPE_MAP: Record<string, InputModelColumnType> = {
  string: "text",
  varchar: "text",
  char: "text",
  decimal: "number",
  float: "number",
  double: "number",
  numeric: "number",
  int: "integer",
  bigint: "integer",
  timestamp: "datetime",
  bool: "boolean",
}

function normalizeColumnType(t: unknown): InputModelColumnType {
  const raw = String(t ?? "").toLowerCase()
  if (VALID_COLUMN_TYPES.includes(raw as InputModelColumnType)) {
    return raw as InputModelColumnType
  }
  return LEGACY_TYPE_MAP[raw] ?? "text"
}

function normalizeSheet(s: InputModelSheet): InputModelSheet {
  return {
    ...s,
    columns: (s.columns ?? []).map((c) => ({
      ...c,
      type: normalizeColumnType(c.type),
    })),
  }
}

// Normaliza file_type vindo do backend (defesa contra letras maiusculas,
// espacos ou valores legados). Default seguro: "excel".
const VALID_FILE_TYPES: ReadonlyArray<InputModelFileType> = ["excel", "csv", "data"]

function normalizeFileType(t: unknown): InputModelFileType {
  const raw = String(t ?? "").trim().toLowerCase()
  if (VALID_FILE_TYPES.includes(raw as InputModelFileType)) {
    return raw as InputModelFileType
  }
  // Aliases legados
  if (raw === "xlsx" || raw === "xls") return "excel"
  if (raw === "internal" || raw === "table") return "data"
  return "excel"
}

// ─── Component ────────────────────────────────────────────────────────────────

export function InputModelFormModal({ open, onOpenChange, editing, workspaceId, onSaved }: Props) {
  const toast = useToast()
  const [saving, setSaving] = useState(false)

  // Form state
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [fileType, setFileType] = useState<InputModelFileType>("excel")
  const [sheets, setSheets] = useState<InputModelSheet[]>([emptySheet()])
  const [activeSheet, setActiveSheet] = useState(0)
  const [bulkOpen, setBulkOpen] = useState(false)
  const [bulkText, setBulkText] = useState("")

  // Reset form when modal opens/closes or editing changes
  useEffect(() => {
    if (!open) return
    if (editing) {
      setName(editing.name)
      setDescription(editing.description ?? "")
      setFileType(normalizeFileType(editing.file_type))
      const s = editing.schema_def?.sheets
      setSheets(s?.length ? s.map(normalizeSheet) : [emptySheet()])
      setActiveSheet(0)
    } else {
      setName("")
      setDescription("")
      setFileType("excel")
      setSheets([emptySheet()])
      setActiveSheet(0)
    }
  }, [open, editing])

  // CSV and data types only support a single sheet
  useEffect(() => {
    if ((fileType === "csv" || fileType === "data") && sheets.length > 1) {
      setSheets([sheets[0]])
      setActiveSheet(0)
    }
  }, [fileType]) // eslint-disable-line react-hooks/exhaustive-deps

  // ─── Sheet helpers ──────────────────────────────────────────────────────

  function updateSheet(index: number, patch: Partial<InputModelSheet>) {
    setSheets((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)))
  }

  function addSheet() {
    const num = sheets.length + 1
    setSheets((prev) => [...prev, emptySheet(`Planilha${num}`)])
    setActiveSheet(sheets.length)
  }

  function removeSheet(index: number) {
    if (sheets.length <= 1) return
    setSheets((prev) => prev.filter((_, i) => i !== index))
    setActiveSheet((prev) => Math.min(prev, sheets.length - 2))
  }

  // ─── Column helpers ─────────────────────────────────────────────────────

  function updateColumn(sheetIdx: number, colIdx: number, patch: Partial<InputModelColumn>) {
    setSheets((prev) =>
      prev.map((s, si) =>
        si === sheetIdx
          ? { ...s, columns: s.columns.map((c, ci) => (ci === colIdx ? { ...c, ...patch } : c)) }
          : s,
      ),
    )
  }

  function addColumn(sheetIdx: number) {
    setSheets((prev) =>
      prev.map((s, si) => (si === sheetIdx ? { ...s, columns: [...s.columns, emptyColumn()] } : s)),
    )
  }

  function removeColumn(sheetIdx: number, colIdx: number) {
    setSheets((prev) =>
      prev.map((s, si) =>
        si === sheetIdx && s.columns.length > 1
          ? { ...s, columns: s.columns.filter((_, ci) => ci !== colIdx) }
          : s,
      ),
    )
  }

  function applyBulkColumns() {
    const names = bulkText
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
    if (names.length === 0) return
    const newCols: InputModelColumn[] = names.map((n) => ({ name: n, type: "text", required: false }))
    setSheets((prev) =>
      prev.map((s, si) => {
        if (si !== activeSheet) return s
        // Replace the single empty placeholder row, otherwise append
        const hasOnlyEmpty = s.columns.length === 1 && !s.columns[0].name.trim()
        return { ...s, columns: hasOnlyEmpty ? newCols : [...s.columns, ...newCols] }
      }),
    )
    setBulkText("")
    setBulkOpen(false)
  }

  // ─── Submit ─────────────────────────────────────────────────────────────

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) return

    // Validate sheets have names and at least one named column
    for (const sheet of sheets) {
      if (!sheet.name.trim()) {
        toast.error("Validação", "Todas as abas precisam de um nome.")
        return
      }
      const namedCols = sheet.columns.filter((c) => c.name.trim())
      if (namedCols.length === 0) {
        toast.error("Validação", `Aba "${sheet.name}" precisa de ao menos uma coluna.`)
        return
      }
    }

    // Clean up: remove unnamed columns + normaliza tipo de cada coluna.
    // A normalizacao na carga ja deveria cobrir, mas fazemos aqui tambem
    // como defesa final — garante que mesmo state corrompido (hot reload
    // antigo, edicao manual no devtools, etc) NUNCA envia tipo invalido.
    const cleanSheets = sheets.map((s) => ({
      ...s,
      columns: s.columns
        .filter((c) => c.name.trim())
        .map((c) => ({ ...c, type: normalizeColumnType(c.type) })),
    }))

    setSaving(true)
    try {
      const payload = {
        name: name.trim(),
        description: description.trim() || null,
        file_type: fileType,
        schema_def: { sheets: cleanSheets },
      }

      if (editing) {
        await updateInputModel(editing.id, payload)
        toast.success("Modelo atualizado", "As alterações foram salvas com sucesso.")
      } else {
        await createInputModel(workspaceId, payload)
        toast.success("Modelo criado", "O modelo de entrada foi cadastrado com sucesso.")
      }

      onOpenChange(false)
      await onSaved()
    } catch (err) {
      toast.error("Erro ao salvar", err instanceof Error ? err.message : "Erro ao salvar modelo.")
    } finally {
      setSaving(false)
    }
  }

  if (!open) return null

  const sheet = sheets[activeSheet] ?? sheets[0]

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div
        className="mx-4 flex max-h-[90vh] w-full max-w-2xl flex-col rounded-2xl border border-border bg-card shadow-xl"
        role="dialog"
        aria-modal
      >
        {/* Title */}
        <div className="border-b border-border px-6 py-4">
          <h2 className="text-lg font-semibold text-foreground">
            {editing ? "Editar Modelo" : "Novo Modelo de Entrada"}
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Defina a estrutura esperada do arquivo que os consultores devem enviar.
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
          {/* Name + File type */}
          <div className="grid gap-4 sm:grid-cols-[1fr_160px]">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Nome do modelo</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Ex: Cadastro de Pessoas"
                required
                className="h-9 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                Tipo
                {editing && (
                  <span
                    className="ml-1 text-[10px] font-normal text-muted-foreground/70"
                    title="O tipo nao pode ser alterado apos a criacao para preservar a integridade dos dados ja cadastrados."
                  >
                    (bloqueado)
                  </span>
                )}
              </label>
              {/* Select HTML nativo — Radix Select tem quirks com disabled +
                  Portal (items nao montam, label nao resolve). Native sempre
                  funciona e visualmente fica igual com as classes do shadcn. */}
              <select
                value={fileType}
                onChange={(e) => setFileType(e.target.value as InputModelFileType)}
                disabled={editing != null}
                className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-60"
              >
                <option value="excel">Excel (.xlsx)</option>
                <option value="csv">CSV</option>
                <option value="data">Dados (tabela interna)</option>
              </select>
            </div>
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Descrição (opcional)</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Breve descrição do modelo..."
              className="h-9 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
            />
          </div>

          {/* Sheet tabs (Excel only — CSV and data have a single fixed sheet) */}
          {fileType === "excel" && (
            <div className="flex items-center gap-1 border-b border-border pb-0">
              {sheets.map((s, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => setActiveSheet(idx)}
                  className={cn(
                    "group relative flex items-center gap-1.5 rounded-t-lg border border-b-0 px-3 py-1.5 text-xs font-medium transition",
                    idx === activeSheet
                      ? "border-border bg-card text-foreground"
                      : "border-transparent text-muted-foreground hover:text-foreground",
                  )}
                >
                  {s.name || `Aba ${idx + 1}`}
                  {sheets.length > 1 && (
                    <span
                      onClick={(e) => { e.stopPropagation(); removeSheet(idx) }}
                      className="ml-1 hidden size-4 items-center justify-center rounded text-muted-foreground hover:text-destructive group-hover:inline-flex"
                    >
                      ×
                    </span>
                  )}
                </button>
              ))}
              <button
                type="button"
                onClick={addSheet}
                className="inline-flex size-7 items-center justify-center rounded-lg text-muted-foreground transition hover:bg-accent hover:text-foreground"
                title="Adicionar aba"
              >
                <Plus className="size-3.5" />
              </button>
            </div>
          )}

          {/* Sheet name — hidden for data type */}
          {fileType !== "data" && (
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                {fileType === "excel" ? "Nome da aba" : "Identificador (interno)"}
              </label>
              <input
                type="text"
                value={sheet.name}
                onChange={(e) => updateSheet(activeSheet, { name: e.target.value })}
                placeholder="Ex: PESSOAS"
                className="h-9 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
              />
            </div>
          )}

          {/* Columns */}
          <div className="space-y-2">
            <label className="text-xs font-medium text-muted-foreground">Colunas</label>

            {/* Header */}
            <div className="grid grid-cols-[1fr_110px_60px_32px] items-center gap-2 px-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              <span>Nome</span>
              <span>Tipo</span>
              <span className="text-center">Obrig.</span>
              <span />
            </div>

            {sheet.columns.map((col, ci) => (
              <div key={ci} className="grid grid-cols-[1fr_110px_60px_32px] items-center gap-2">
                <input
                  type="text"
                  value={col.name}
                  onChange={(e) => updateColumn(activeSheet, ci, { name: e.target.value })}
                  placeholder="nome_coluna"
                  className="h-8 rounded-md border border-input bg-background px-2 text-xs outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
                />
                <Select
                  value={normalizeColumnType(col.type)}
                  onValueChange={(v) => updateColumn(activeSheet, ci, { type: v as InputModelColumnType })}
                >
                  <SelectTrigger className="h-8 text-xs bg-background">
                    <SelectValue placeholder="Tipo…" />
                  </SelectTrigger>
                  <SelectContent>
                    {COLUMN_TYPES.map((t) => (
                      <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="flex items-center justify-center">
                  <input
                    type="checkbox"
                    checked={col.required}
                    onChange={(e) => updateColumn(activeSheet, ci, { required: e.target.checked })}
                    className="size-3.5 rounded border-input accent-primary"
                  />
                </div>
                <button
                  type="button"
                  onClick={() => removeColumn(activeSheet, ci)}
                  disabled={sheet.columns.length <= 1}
                  className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition hover:bg-destructive/10 hover:text-destructive disabled:opacity-30"
                >
                  <Trash2 className="size-3" />
                </button>
              </div>
            ))}

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => addColumn(activeSheet)}
                className="flex h-8 flex-1 items-center justify-center gap-1.5 rounded-lg border border-dashed border-border text-xs font-medium text-muted-foreground transition hover:border-foreground/30 hover:text-foreground"
              >
                <Plus className="size-3" />
                Adicionar coluna
              </button>
              <button
                type="button"
                onClick={() => { setBulkOpen(!bulkOpen); setBulkText("") }}
                className={cn(
                  "flex h-8 items-center gap-1.5 rounded-lg border px-3 text-xs font-medium transition",
                  bulkOpen
                    ? "border-primary/30 bg-primary/5 text-primary"
                    : "border-dashed border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground",
                )}
              >
                <ClipboardPaste className="size-3" />
                Importar colunas
              </button>
            </div>

            {bulkOpen && (
              <div className="space-y-2 rounded-lg border border-border bg-background p-3">
                <p className="text-[11px] text-muted-foreground">
                  Cole os nomes das colunas, um por linha. Todas serão criadas como Texto e não obrigatórias.
                </p>
                <textarea
                  value={bulkText}
                  onChange={(e) => setBulkText(e.target.value)}
                  placeholder={"NOME\nCPF\nDATA_NASCIMENTO\nSALARIO"}
                  rows={5}
                  className="w-full resize-none rounded-md border border-input bg-card px-3 py-2 font-mono text-xs outline-none placeholder:text-muted-foreground/50 focus:ring-1 focus:ring-primary"
                />
                <div className="flex items-center justify-between">
                  <span className="text-[11px] text-muted-foreground">
                    {bulkText.split("\n").filter((l) => l.trim()).length} coluna(s)
                  </span>
                  <button
                    type="button"
                    onClick={applyBulkColumns}
                    disabled={!bulkText.trim()}
                    className="inline-flex h-7 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
                  >
                    Aplicar
                  </button>
                </div>
              </div>
            )}
          </div>
        </form>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-border px-6 py-4">
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={saving}
            className="h-9 rounded-lg border border-border bg-background px-4 text-sm font-medium text-foreground transition hover:bg-accent disabled:opacity-50"
          >
            Cancelar
          </button>
          <button
            onClick={handleSubmit}
            disabled={saving || !name.trim()}
            className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
          >
            {saving && <MorphLoader className="size-3.5" />}
            {editing ? "Salvar alterações" : "Criar modelo"}
          </button>
        </div>
      </div>
    </div>
  )
}
