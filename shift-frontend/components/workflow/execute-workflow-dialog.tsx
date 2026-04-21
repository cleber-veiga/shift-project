"use client"

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { ChevronDown, Eye, FileUp, Loader2, Play, X } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  getVariablesSchema,
  uploadWorkflowFile,
  type ConnectionOption,
  type VariablesSchemaResponse,
} from "@/lib/api/workflow-variables"
import type { WorkflowVariable } from "@/lib/workflow/types"

// ── Props ─────────────────────────────────────────────────────────────────────

interface ExecuteWorkflowDialogProps {
  workflowId: string
  previewOnly?: boolean
  onClose: () => void
  onDirectExecute: () => void
  onExecuteWithVars: (values: Record<string, unknown>) => Promise<void>
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function buildAccept(exts: string[]): string {
  return exts
    .map((e) => e.trim())
    .filter(Boolean)
    .map((e) => (e.startsWith(".") ? e : `.${e}`))
    .join(",")
}

// ── Field components ─────────────────────────────────────────────────────────

interface FieldProps {
  variable: WorkflowVariable
  value: unknown
  error?: string
  connectionOptions: ConnectionOption[]
  uploading: boolean
  onChange: (v: unknown) => void
  onFileUpload: (file: File) => void
}

function VariableField({
  variable,
  value,
  error,
  connectionOptions,
  uploading,
  onChange,
  onFileUpload,
}: FieldProps) {
  const [showConnDropdown, setShowConnDropdown] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const connBtnRef = useRef<HTMLButtonElement>(null)
  const [dropdownRect, setDropdownRect] = useState<{ top: number; left: number; width: number } | null>(null)

  useLayoutEffect(() => {
    if (!showConnDropdown || !connBtnRef.current) {
      setDropdownRect(null)
      return
    }
    const rect = connBtnRef.current.getBoundingClientRect()
    setDropdownRect({ top: rect.bottom + 4, left: rect.left, width: rect.width })
  }, [showConnDropdown])

  useEffect(() => {
    if (!showConnDropdown) return
    function close() {
      setShowConnDropdown(false)
    }
    window.addEventListener("scroll", close, true)
    window.addEventListener("resize", close)
    return () => {
      window.removeEventListener("scroll", close, true)
      window.removeEventListener("resize", close)
    }
  }, [showConnDropdown])

  useEffect(() => {
    if (!showConnDropdown) return
    function handleClickOutside(e: MouseEvent) {
      const btn = connBtnRef.current
      if (btn && btn.contains(e.target as Node)) return
      const target = e.target as HTMLElement
      if (target.closest("[data-conn-dropdown]")) return
      setShowConnDropdown(false)
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setShowConnDropdown(false)
    }
    document.addEventListener("mousedown", handleClickOutside)
    document.addEventListener("keydown", handleKey)
    return () => {
      document.removeEventListener("mousedown", handleClickOutside)
      document.removeEventListener("keydown", handleKey)
    }
  }, [showConnDropdown])

  const strVal = value !== undefined && value !== null ? String(value) : ""
  const selectedConn = connectionOptions.find((c) => c.id === strVal) ?? null

  const inputCls =
    "h-9 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"

  switch (variable.type) {
    case "boolean":
      return (
        <label className="flex cursor-pointer items-center gap-3">
          <div
            role="switch"
            aria-checked={Boolean(value)}
            onClick={() => onChange(!value)}
            className={cn(
              "relative h-5 w-9 cursor-pointer rounded-full transition-colors",
              value ? "bg-primary" : "bg-muted",
            )}
          >
            <span
              className={cn(
                "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform",
                value ? "translate-x-4" : "translate-x-0.5",
              )}
            />
          </div>
          <span className="text-xs text-foreground">{Boolean(value) ? "Sim" : "Não"}</span>
        </label>
      )

    case "integer":
      return (
        <input
          type="number"
          step="1"
          value={strVal}
          onChange={(e) => onChange(e.target.value === "" ? "" : parseInt(e.target.value, 10))}
          className={inputCls}
          placeholder={variable.default !== undefined ? String(variable.default) : "0"}
        />
      )

    case "number":
      return (
        <input
          type="number"
          value={strVal}
          onChange={(e) => onChange(e.target.value === "" ? "" : parseFloat(e.target.value))}
          className={inputCls}
          placeholder={variable.default !== undefined ? String(variable.default) : "0.0"}
        />
      )

    case "secret":
      return (
        <input
          type="password"
          value={strVal}
          onChange={(e) => onChange(e.target.value)}
          className={inputCls}
          placeholder="••••••••"
          autoComplete="new-password"
        />
      )

    case "connection": {
      return (
        <>
          <button
            ref={connBtnRef}
            type="button"
            onClick={() => setShowConnDropdown((v) => !v)}
            className={cn(
              "flex h-9 w-full items-center gap-2 rounded-md border px-2.5 text-left text-xs transition-colors",
              selectedConn
                ? "border-input bg-background text-foreground"
                : "border-dashed border-border bg-muted/20 text-muted-foreground",
            )}
          >
            {selectedConn ? (
              <>
                <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase">
                  {selectedConn.type.slice(0, 2)}
                </span>
                <span className="flex-1 truncate font-medium">{selectedConn.name}</span>
              </>
            ) : (
              <span>Selecionar conexão...</span>
            )}
            <ChevronDown
              className={cn(
                "ml-auto size-3 shrink-0 transition-transform",
                showConnDropdown && "rotate-180",
              )}
            />
          </button>

          {showConnDropdown && dropdownRect && typeof document !== "undefined" &&
            createPortal(
              <div
                data-conn-dropdown
                className="fixed z-[100] overflow-hidden rounded-lg border border-border bg-card shadow-lg"
                style={{
                  top: dropdownRect.top,
                  left: dropdownRect.left,
                  width: dropdownRect.width,
                }}
              >
                <div className="max-h-48 overflow-y-auto p-1">
                  {connectionOptions.length === 0 ? (
                    <p className="px-2 py-3 text-center text-[11px] text-muted-foreground">
                      Nenhuma conexão compatível encontrada
                    </p>
                  ) : (
                    connectionOptions.map((conn) => (
                      <button
                        key={conn.id}
                        type="button"
                        onClick={() => {
                          onChange(conn.id)
                          setShowConnDropdown(false)
                        }}
                        className={cn(
                          "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-muted/60",
                          conn.id === strVal && "bg-primary/5",
                        )}
                      >
                        <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase">
                          {conn.type.slice(0, 2)}
                        </span>
                        <span className="font-medium">{conn.name}</span>
                        <span className="ml-auto text-[10px] text-muted-foreground">{conn.type}</span>
                      </button>
                    ))
                  )}
                </div>
              </div>,
              document.body,
            )}
        </>
      )
    }

    case "file_upload": {
      const fileId = strVal || null
      return (
        <div>
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            accept={variable.accepted_extensions?.length ? buildAccept(variable.accepted_extensions) : undefined}
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) onFileUpload(f)
            }}
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            className={cn(
              "flex h-20 w-full flex-col items-center justify-center gap-1.5 rounded-lg border-2 border-dashed text-xs transition-colors",
              fileId
                ? "border-emerald-500/40 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400"
                : "border-border bg-muted/20 text-muted-foreground hover:border-primary/40 hover:bg-muted/40",
              uploading && "pointer-events-none opacity-60",
            )}
          >
            {uploading ? (
              <>
                <Loader2 className="size-5 animate-spin" />
                <span>Enviando...</span>
              </>
            ) : fileId ? (
              <>
                <FileUp className="size-5" />
                <span className="font-mono text-[10px]">{fileId.slice(0, 16)}…</span>
                <span className="text-[10px] opacity-70">Clique para substituir</span>
              </>
            ) : (
              <>
                <FileUp className="size-5" />
                <span>Clique para selecionar arquivo</span>
                {variable.accepted_extensions && (
                  <span className="text-[10px] opacity-70">
                    {variable.accepted_extensions.join(", ")}
                  </span>
                )}
              </>
            )}
          </button>
        </div>
      )
    }

    default:
      return (
        <input
          type="text"
          value={strVal}
          onChange={(e) => onChange(e.target.value)}
          className={inputCls}
          placeholder={
            variable.default !== undefined
              ? String(variable.default)
              : variable.description ?? variable.name
          }
        />
      )
  }
}

// ── Main dialog ───────────────────────────────────────────────────────────────

export function ExecuteWorkflowDialog({
  workflowId,
  previewOnly = false,
  onClose,
  onDirectExecute,
  onExecuteWithVars,
}: ExecuteWorkflowDialogProps) {
  const [schema, setSchema] = useState<VariablesSchemaResponse | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [formValues, setFormValues] = useState<Record<string, unknown>>({})
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [executing, setExecuting] = useState(false)
  const [execError, setExecError] = useState<string | null>(null)
  const [uploadingVars, setUploadingVars] = useState<Set<string>>(new Set())
  const [uploadProgress, setUploadProgress] = useState<Record<string, number>>({})

  useEffect(() => {
    let cancelled = false
    getVariablesSchema(workflowId)
      .then((s) => {
        if (cancelled) return
        if (s.variables.length === 0) {
          onClose()
          if (!previewOnly) onDirectExecute()
          return
        }
        setSchema(s)
        const defaults: Record<string, unknown> = {}
        for (const v of s.variables) {
          if (v.default !== undefined) defaults[v.name] = v.default
        }
        setFormValues(defaults)
      })
      .catch((e: unknown) => {
        if (!cancelled)
          setLoadError(e instanceof Error ? e.message : "Erro ao carregar schema")
      })
    return () => {
      cancelled = true
    }
  }, [workflowId, previewOnly])

  const groups = useMemo(() => {
    if (!schema) return []
    const sorted = [...schema.variables].sort((a, b) => a.ui_order - b.ui_order)
    const result: { name: string | null; vars: WorkflowVariable[] }[] = []
    const seen = new Map<string | null, WorkflowVariable[]>()
    for (const v of sorted) {
      const key = v.ui_group ?? null
      if (!seen.has(key)) {
        const arr: WorkflowVariable[] = []
        seen.set(key, arr)
        result.push({ name: key, vars: arr })
      }
      seen.get(key)!.push(v)
    }
    return result
  }, [schema])

  function setValue(name: string, value: unknown) {
    setFormValues((prev) => ({ ...prev, [name]: value }))
    setFieldErrors((prev) => {
      const next = { ...prev }
      delete next[name]
      return next
    })
  }

  function validate(): boolean {
    const errs: Record<string, string> = {}
    for (const v of schema?.variables ?? []) {
      const val = formValues[v.name]
      const isEmpty = val === undefined || val === "" || val === null
      if (v.required && isEmpty) {
        errs[v.name] = "Campo obrigatório"
      }
      if (!isEmpty) {
        if (v.type === "integer" && !Number.isInteger(Number(val))) {
          errs[v.name] = "Deve ser um número inteiro"
        }
        if (v.type === "number" && isNaN(Number(val))) {
          errs[v.name] = "Deve ser um número"
        }
      }
    }
    setFieldErrors(errs)
    return Object.keys(errs).length === 0
  }

  async function handleSubmit() {
    if (!validate()) return
    if (previewOnly) {
      onClose()
      return
    }
    setExecuting(true)
    setExecError(null)
    try {
      await onExecuteWithVars(formValues)
      onClose()
    } catch (e: unknown) {
      setExecError(e instanceof Error ? e.message : "Erro ao executar")
      setExecuting(false)
    }
  }

  async function handleFileUpload(varName: string, file: File) {
    setUploadingVars((prev) => new Set(prev).add(varName))
    setUploadProgress((prev) => ({ ...prev, [varName]: 0 }))
    try {
      const result = await uploadWorkflowFile(workflowId, file, (pct) => {
        setUploadProgress((prev) => ({ ...prev, [varName]: pct }))
      })
      setValue(varName, result.file_id)
    } catch (e: unknown) {
      setFieldErrors((prev) => ({
        ...prev,
        [varName]: e instanceof Error ? e.message : "Erro no upload",
      }))
    } finally {
      setUploadingVars((prev) => {
        const next = new Set(prev)
        next.delete(varName)
        return next
      })
      setUploadProgress((prev) => {
        const next = { ...prev }
        delete next[varName]
        return next
      })
    }
  }

  // Loading spinner before schema arrives (auto-proceed case also handled here)
  if (!schema && !loadError) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-[2px]">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (loadError) {
    return (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-[2px]"
        onClick={onClose}
      >
        <div
          className="rounded-lg border border-border bg-card p-6 shadow-xl"
          onClick={(e) => e.stopPropagation()}
        >
          <p className="text-sm text-destructive">{loadError}</p>
          <button
            type="button"
            onClick={onClose}
            className="mt-3 text-xs text-muted-foreground hover:text-foreground"
          >
            Fechar
          </button>
        </div>
      </div>
    )
  }

  if (!schema) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-[2px]"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-lg flex-col rounded-xl border border-border bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4">
          <div>
            <h2 className="text-sm font-semibold text-foreground">
              {previewOnly ? "Preview do formulário de execução" : "Executar workflow"}
            </h2>
            <p className="text-[11px] text-muted-foreground">
              {previewOnly
                ? "Visualize como os parâmetros serão solicitados"
                : "Preencha os parâmetros para esta execução"}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label="Fechar"
          >
            <X className="size-4" />
          </button>
        </header>

        {/* Form body */}
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <div className="space-y-6">
            {groups.map((group) => (
              <div key={group.name ?? "__ungrouped"}>
                {group.name && (
                  <h3 className="mb-3 border-b border-border pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    {group.name}
                  </h3>
                )}
                <div className="space-y-4">
                  {group.vars.map((v) => (
                    <div key={v.name} className="space-y-1.5">
                      <label className="flex items-center gap-1.5 text-[11px] font-medium text-foreground">
                        <span>{v.description || v.name}</span>
                        {v.required && (
                          <span className="text-destructive">*</span>
                        )}
                        <code className="ml-auto font-mono text-[9px] text-muted-foreground">
                          {`{{vars.${v.name}}}`}
                        </code>
                      </label>
                      <VariableField
                        variable={v}
                        value={formValues[v.name]}
                        error={fieldErrors[v.name]}
                        connectionOptions={schema.connection_options[v.name] ?? []}
                        uploading={uploadingVars.has(v.name)}
                        onChange={(val) => setValue(v.name, val)}
                        onFileUpload={(file) => void handleFileUpload(v.name, file)}
                      />
                      {v.type === "file_upload" && uploadingVars.has(v.name) && (
                        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                          <div
                            className="h-full rounded-full bg-primary transition-[width] duration-200"
                            style={{ width: `${uploadProgress[v.name] ?? 0}%` }}
                          />
                        </div>
                      )}
                      {fieldErrors[v.name] && (
                        <p className="text-[11px] text-destructive">
                          {fieldErrors[v.name]}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <footer className="flex shrink-0 flex-col gap-2 border-t border-border px-4 py-3">
          {execError && (
            <p className="text-[11px] text-destructive">{execError}</p>
          )}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="h-8 flex-1 rounded-md border border-border bg-background text-xs font-medium text-foreground transition-colors hover:bg-muted"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={executing || uploadingVars.size > 0}
              className="flex h-8 flex-1 items-center justify-center gap-1.5 rounded-md bg-emerald-600 text-xs font-semibold text-white transition-colors hover:bg-emerald-700 disabled:opacity-50"
            >
              {executing ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : previewOnly ? (
                <Eye className="size-3.5" />
              ) : (
                <Play className="size-3.5" />
              )}
              {previewOnly ? "Fechar preview" : "Executar"}
            </button>
          </div>
        </footer>
      </div>
    </div>
  )
}
