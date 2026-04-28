"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import {
  ArrowLeft,
  Check,
  ClipboardPaste,
  FileSpreadsheet,
  Pencil,
  Plus,
  Trash2,
  X,
} from "lucide-react"
import {
  getInputModel,
  listInputModelRows,
  addInputModelRow,
  addInputModelRowsBulk,
  updateInputModelRow,
  deleteInputModelRow,
  clearInputModelRows,
  type InputModel,
  type InputModelRow,
  type InputModelColumn,
} from "@/lib/auth"
import { useToast } from "@/lib/context/toast-context"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { MorphLoader } from "@/components/ui/morph-loader"
import { cn } from "@/lib/utils"

interface Props {
  modelId: string
}

export function InputModelDataPage({ modelId }: Props) {
  const router = useRouter()
  const toast = useToast()

  const [model, setModel] = useState<InputModel | null>(null)
  const [rows, setRows] = useState<InputModelRow[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)

  // Inline editing
  const [editingRowId, setEditingRowId] = useState<string | null>(null)
  const [editingData, setEditingData] = useState<Record<string, unknown>>({})

  // New row
  const [addingRow, setAddingRow] = useState(false)
  const [newRowData, setNewRowData] = useState<Record<string, unknown>>({})

  // Bulk import
  const [bulkOpen, setBulkOpen] = useState(false)
  const [bulkText, setBulkText] = useState("")
  const [bulkSaving, setBulkSaving] = useState(false)

  // Delete
  const [deleteTarget, setDeleteTarget] = useState<InputModelRow | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [clearConfirmOpen, setClearConfirmOpen] = useState(false)
  const [clearing, setClearing] = useState(false)

  // ─── Columns from schema ───────────────────────────────────────────────

  const columns: InputModelColumn[] = useMemo(() => {
    if (!model?.schema_def?.sheets?.length) return []
    // Use first sheet's columns (for CSV there's only one; for Excel use first)
    return model.schema_def.sheets[0].columns
  }, [model])

  // ─── Load data ─────────────────────────────────────────────────────────

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [modelData, rowsData] = await Promise.all([
        getInputModel(modelId),
        listInputModelRows(modelId),
      ])
      setModel(modelData)
      setRows(rowsData.rows)
      setTotal(rowsData.total)
    } catch {
      toast.error("Erro", "Não foi possível carregar os dados do modelo.")
    } finally {
      setLoading(false)
    }
  }, [modelId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    void loadData()
  }, [loadData])

  // ─── Inline edit ───────────────────────────────────────────────────────

  function startEdit(row: InputModelRow) {
    setEditingRowId(row.id)
    setEditingData({ ...row.data })
    setAddingRow(false)
  }

  function cancelEdit() {
    setEditingRowId(null)
    setEditingData({})
  }

  async function saveEdit() {
    if (!editingRowId) return
    try {
      await updateInputModelRow(editingRowId, editingData)
      setEditingRowId(null)
      setEditingData({})
      await loadData()
    } catch {
      toast.error("Erro", "Não foi possível salvar a linha.")
    }
  }

  // ─── Add row ───────────────────────────────────────────────────────────

  function startAddRow() {
    setAddingRow(true)
    setEditingRowId(null)
    const empty: Record<string, unknown> = {}
    for (const col of columns) {
      empty[col.name] = ""
    }
    setNewRowData(empty)
  }

  function cancelAddRow() {
    setAddingRow(false)
    setNewRowData({})
  }

  async function saveNewRow() {
    try {
      await addInputModelRow(modelId, newRowData)
      setAddingRow(false)
      setNewRowData({})
      await loadData()
      toast.success("Linha adicionada", "A linha foi inserida com sucesso.")
    } catch {
      toast.error("Erro", "Não foi possível adicionar a linha.")
    }
  }

  // ─── Delete row ────────────────────────────────────────────────────────

  async function handleDeleteRow() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteInputModelRow(deleteTarget.id)
      setDeleteTarget(null)
      await loadData()
      toast.success("Linha removida", "A linha foi excluída com sucesso.")
    } catch {
      toast.error("Erro", "Não foi possível excluir a linha.")
    } finally {
      setDeleting(false)
    }
  }

  // ─── Clear all ─────────────────────────────────────────────────────────

  async function handleClearAll() {
    setClearing(true)
    try {
      const result = await clearInputModelRows(modelId)
      setClearConfirmOpen(false)
      await loadData()
      toast.success("Dados limpos", `${result.deleted} linha(s) removida(s).`)
    } catch {
      toast.error("Erro", "Não foi possível limpar os dados.")
    } finally {
      setClearing(false)
    }
  }

  // ─── Bulk import ───────────────────────────────────────────────────────

  function parseBulkText(): Record<string, unknown>[] {
    const lines = bulkText.split("\n").filter((l) => l.trim())
    if (lines.length === 0) return []

    // Detect delimiter: tab first, then semicolon, then comma
    const firstLine = lines[0]
    const delimiter = firstLine.includes("\t") ? "\t" : firstLine.includes(";") ? ";" : ","

    const colNames = columns.map((c) => c.name)

    return lines.map((line) => {
      const values = line.split(delimiter).map((v) => v.trim())
      const row: Record<string, unknown> = {}
      colNames.forEach((name, i) => {
        row[name] = values[i] ?? ""
      })
      return row
    })
  }

  const bulkPreviewRows = useMemo(() => {
    if (!bulkText.trim()) return []
    return parseBulkText()
  }, [bulkText, columns]) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleBulkImport() {
    const parsed = parseBulkText()
    if (parsed.length === 0) return
    setBulkSaving(true)
    try {
      await addInputModelRowsBulk(modelId, parsed)
      setBulkOpen(false)
      setBulkText("")
      await loadData()
      toast.success("Importação concluída", `${parsed.length} linha(s) importada(s).`)
    } catch {
      toast.error("Erro", "Não foi possível importar os dados.")
    } finally {
      setBulkSaving(false)
    }
  }

  // ─── Render ────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <MorphLoader className="size-5" />
      </div>
    )
  }

  if (!model) {
    return (
      <div className="py-10 text-center text-sm text-muted-foreground">
        Modelo de entrada não encontrado.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => router.push("/espaco/modelos-entrada")}
          className="flex size-9 items-center justify-center rounded-lg border border-border bg-background text-muted-foreground transition hover:bg-accent hover:text-foreground"
          aria-label="Voltar"
        >
          <ArrowLeft className="size-4" />
        </button>
        <div className="flex items-center gap-2">
          <FileSpreadsheet className="size-5 text-primary" />
          <div>
            <h1 className="text-lg font-semibold text-foreground">{model.name}</h1>
            {model.description && (
              <p className="text-xs text-muted-foreground">{model.description}</p>
            )}
          </div>
        </div>
        <span className={`ml-2 inline-flex rounded px-2 py-0.5 text-[10px] font-medium uppercase ${
          model.file_type === "excel"
            ? "bg-emerald-500/10 text-emerald-600"
            : "bg-blue-500/10 text-blue-600"
        }`}>
          {model.file_type}
        </span>
        <span className="text-xs text-muted-foreground">{total} linha(s)</span>
      </div>

      {/* Toolbar */}
      <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={startAddRow}
            disabled={addingRow}
            className="inline-flex h-8 items-center gap-1.5 rounded-md bg-foreground px-3 text-xs font-semibold text-background transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            <Plus className="size-3.5" />
            Nova Linha
          </button>
          <button
            type="button"
            onClick={() => { setBulkOpen(!bulkOpen); setBulkText("") }}
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-xs font-medium transition",
              bulkOpen
                ? "border-primary/30 bg-primary/5 text-primary"
                : "border-border bg-background text-muted-foreground hover:text-foreground",
            )}
          >
            <ClipboardPaste className="size-3.5" />
            Importar em Massa
          </button>
        </div>
        {rows.length > 0 && (
          <button
            type="button"
            onClick={() => setClearConfirmOpen(true)}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-3 text-xs font-medium text-destructive transition hover:bg-destructive/10"
          >
            <Trash2 className="size-3.5" />
            Limpar Tudo
          </button>
        )}
      </div>

      {/* Bulk import area */}
      {bulkOpen && (
        <div className="space-y-3 rounded-xl border border-border bg-card p-4">
          <div>
            <p className="text-sm font-medium text-foreground">Importar dados em massa</p>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              Cole os dados abaixo. Cada linha representa um registro. Colunas separadas por TAB, ponto-e-vírgula ou vírgula.
              A ordem das colunas deve seguir: <strong>{columns.map((c) => c.name).join(", ")}</strong>
            </p>
          </div>
          <textarea
            value={bulkText}
            onChange={(e) => setBulkText(e.target.value)}
            placeholder={columns.map((c) => c.name).join("\t")}
            rows={6}
            className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2 font-mono text-xs outline-none placeholder:text-muted-foreground/50 focus:ring-1 focus:ring-primary"
          />
          {bulkPreviewRows.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border bg-muted/30">
                    <th className="px-3 py-2 text-left text-[10px] font-bold uppercase tracking-wider text-muted-foreground">#</th>
                    {columns.map((col) => (
                      <th key={col.name} className="px-3 py-2 text-left text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                        {col.name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {bulkPreviewRows.slice(0, 5).map((row, i) => (
                    <tr key={i} className="hover:bg-muted/10">
                      <td className="px-3 py-1.5 text-muted-foreground">{i + 1}</td>
                      {columns.map((col) => (
                        <td key={col.name} className="px-3 py-1.5 text-foreground">
                          {String(row[col.name] ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {bulkPreviewRows.length > 5 && (
                <div className="border-t border-border px-3 py-1.5 text-[11px] text-muted-foreground">
                  ... e mais {bulkPreviewRows.length - 5} linha(s)
                </div>
              )}
            </div>
          )}
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-muted-foreground">
              {bulkPreviewRows.length} linha(s) detectada(s)
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => { setBulkOpen(false); setBulkText("") }}
                className="h-8 rounded-md border border-border bg-background px-3 text-xs font-medium text-foreground transition hover:bg-accent"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={handleBulkImport}
                disabled={bulkPreviewRows.length === 0 || bulkSaving}
                className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
              >
                {bulkSaving && <MorphLoader className="size-3" />}
                Importar {bulkPreviewRows.length} linha(s)
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Data table */}
      {columns.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-card/60 p-8 text-center">
          <p className="text-sm text-muted-foreground">
            Este modelo não possui colunas definidas no schema.
          </p>
        </div>
      ) : rows.length === 0 && !addingRow ? (
        <div className="rounded-2xl border border-dashed border-border bg-card/60 p-8 text-center">
          <FileSpreadsheet className="mx-auto size-10 text-muted-foreground/40" />
          <p className="mt-3 text-base font-semibold text-foreground">Nenhum dado cadastrado</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Adicione linhas manualmente ou importe dados em massa.
          </p>
          <div className="mt-4 flex items-center justify-center gap-2">
            <button
              type="button"
              onClick={startAddRow}
              className="inline-flex h-9 items-center gap-1.5 rounded-md bg-foreground px-4 text-sm font-semibold text-background transition-opacity hover:opacity-90"
            >
              <Plus className="size-4" />
              Nova Linha
            </button>
            <button
              type="button"
              onClick={() => setBulkOpen(true)}
              className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-background px-4 text-sm font-medium text-foreground transition hover:bg-accent"
            >
              <ClipboardPaste className="size-4" />
              Importar em Massa
            </button>
          </div>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="w-12 px-3 py-3 text-center text-[10px] font-bold uppercase tracking-wider text-muted-foreground">#</th>
                {columns.map((col) => (
                  <th key={col.name} className="px-3 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                    <span>{col.name}</span>
                    {col.required && <span className="ml-1 text-destructive">*</span>}
                    <span className="ml-1.5 font-normal text-muted-foreground/60">{col.type}</span>
                  </th>
                ))}
                <th className="w-24 px-3 py-3 text-right text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Ações</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((row, idx) => (
                <tr key={row.id} className="transition-colors hover:bg-muted/10">
                  <td className="px-3 py-2 text-center text-xs text-muted-foreground">{idx + 1}</td>
                  {columns.map((col) =>
                    editingRowId === row.id ? (
                      <td key={col.name} className="px-2 py-1.5">
                        <input
                          type="text"
                          value={String(editingData[col.name] ?? "")}
                          onChange={(e) => setEditingData((prev) => ({ ...prev, [col.name]: e.target.value }))}
                          className="h-7 w-full rounded border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary"
                        />
                      </td>
                    ) : (
                      <td key={col.name} className="px-3 py-2 text-xs text-foreground">
                        {String(row.data[col.name] ?? "")}
                      </td>
                    ),
                  )}
                  <td className="px-3 py-2">
                    <div className="flex items-center justify-end gap-0.5">
                      {editingRowId === row.id ? (
                        <>
                          <button
                            type="button"
                            onClick={saveEdit}
                            className="rounded p-1.5 text-emerald-600 transition hover:bg-emerald-500/10"
                            aria-label="Salvar"
                          >
                            <Check className="size-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={cancelEdit}
                            className="rounded p-1.5 text-muted-foreground transition hover:bg-muted"
                            aria-label="Cancelar"
                          >
                            <X className="size-3.5" />
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={() => startEdit(row)}
                            className="rounded p-1.5 text-muted-foreground transition hover:bg-muted hover:text-foreground"
                            aria-label="Editar linha"
                          >
                            <Pencil className="size-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={() => setDeleteTarget(row)}
                            className="rounded p-1.5 text-destructive/70 transition hover:bg-destructive/10 hover:text-destructive"
                            aria-label="Excluir linha"
                          >
                            <Trash2 className="size-3.5" />
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}

              {/* New row inline */}
              {addingRow && (
                <tr className="bg-primary/5">
                  <td className="px-3 py-2 text-center text-xs text-muted-foreground">
                    <Plus className="mx-auto size-3.5 text-primary" />
                  </td>
                  {columns.map((col) => (
                    <td key={col.name} className="px-2 py-1.5">
                      <input
                        type="text"
                        value={String(newRowData[col.name] ?? "")}
                        onChange={(e) => setNewRowData((prev) => ({ ...prev, [col.name]: e.target.value }))}
                        placeholder={col.name}
                        className="h-7 w-full rounded border border-input bg-background px-2 text-xs outline-none placeholder:text-muted-foreground/40 focus:ring-1 focus:ring-primary"
                      />
                    </td>
                  ))}
                  <td className="px-3 py-2">
                    <div className="flex items-center justify-end gap-0.5">
                      <button
                        type="button"
                        onClick={saveNewRow}
                        className="rounded p-1.5 text-emerald-600 transition hover:bg-emerald-500/10"
                        aria-label="Salvar nova linha"
                      >
                        <Check className="size-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={cancelAddRow}
                        className="rounded p-1.5 text-muted-foreground transition hover:bg-muted"
                        aria-label="Cancelar"
                      >
                        <X className="size-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Delete row confirmation */}
      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}
        title="Excluir linha"
        description="Tem certeza que deseja excluir esta linha? Esta ação não pode ser desfeita."
        confirmText="Excluir"
        confirmVariant="destructive"
        loading={deleting}
        onConfirm={handleDeleteRow}
      />

      {/* Clear all confirmation */}
      <ConfirmDialog
        open={clearConfirmOpen}
        onOpenChange={setClearConfirmOpen}
        title="Limpar todos os dados"
        description={`Tem certeza que deseja remover todas as ${total} linha(s)? Esta ação não pode ser desfeita.`}
        confirmText="Limpar Tudo"
        confirmVariant="destructive"
        loading={clearing}
        onConfirm={handleClearAll}
      />
    </div>
  )
}
