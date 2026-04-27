"use client"

/**
 * FilePickerInput — input dual-mode pra campos que aceitam arquivos.
 *
 * 3 modos:
 *   1. URL/Path direto       — texto livre (https://, s3://, /path/file.csv)
 *   2. Arquivo do projeto    — dropdown com uploads ja feitos
 *   3. Upload novo           — file picker + drag-drop, POST pra API
 *
 * Os modos 2 e 3 acabam armazenando o valor como `shift-upload://<file_id>`,
 * que e resolvido em runtime pelo backend. Modo 1 armazena a URL crua.
 *
 * O componente exibe um chip "📎 nome-original.csv" quando o value ja e
 * uma referencia a upload, com botao pra trocar.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Loader2, Upload, X, FileSpreadsheet, Globe, Variable } from "lucide-react"
import {
  listWorkflowUploads,
  uploadWorkflowFile,
  deleteWorkflowUpload,
  type WorkflowUpload,
} from "@/lib/auth"
import { useWorkflowVariablesContext } from "@/lib/workflow/workflow-variables-context"

const UPLOAD_SCHEME = "shift-upload://"
const VARS_RE = /^\{\{\s*vars\.([a-zA-Z_][\w]*)\s*\}\}$/

type Mode = "direct" | "saved" | "upload" | "variable"

export type FilePickerInputProps = {
  value: string
  onChange: (next: string) => void
  workflowId?: string
  /** Extensoes aceitas no input (ex: ".csv,.tsv"). Default: aceita tudo. */
  accept?: string
  /** Placeholder do modo URL direto. */
  placeholder?: string
  disabled?: boolean
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function isUploadUri(value: string): boolean {
  return value.startsWith(UPLOAD_SCHEME)
}

function extractFileId(value: string): string | null {
  if (!isUploadUri(value)) return null
  return value.slice(UPLOAD_SCHEME.length).trim() || null
}

function isVariableRef(value: string): boolean {
  return VARS_RE.test(value.trim())
}

function extractVariableName(value: string): string | null {
  const m = VARS_RE.exec(value.trim())
  return m ? m[1] : null
}

export function FilePickerInput({
  value,
  onChange,
  workflowId,
  accept,
  placeholder = "https://... ou /path/to/file",
  disabled = false,
}: FilePickerInputProps) {
  // Inicializa modo com base no valor atual.
  const initialMode: Mode = isUploadUri(value)
    ? "saved"
    : isVariableRef(value)
      ? "variable"
      : "direct"
  const [mode, setMode] = useState<Mode>(initialMode)
  const [uploads, setUploads] = useState<WorkflowUpload[] | null>(null)
  const [loadingList, setLoadingList] = useState(false)
  const [listError, setListError] = useState<string | null>(null)

  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)

  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const currentFileId = extractFileId(value)
  const currentUploadMeta = useMemo(() => {
    if (!currentFileId || !uploads) return null
    return uploads.find((u) => u.file_id === currentFileId) ?? null
  }, [currentFileId, uploads])

  // Variaveis do workflow (file_upload). Quando o no usa "{{vars.X}}",
  // o consultor sera solicitado a fazer upload no momento da execucao.
  const { variables } = useWorkflowVariablesContext()
  const fileUploadVars = useMemo(
    () => variables.filter((v) => v.type === "file_upload"),
    [variables],
  )
  const currentVarName = extractVariableName(value)

  const refreshUploads = useCallback(async () => {
    if (!workflowId) return
    setLoadingList(true)
    setListError(null)
    try {
      const list = await listWorkflowUploads(workflowId)
      setUploads(list)
    } catch (err) {
      setListError((err as Error).message || "Falha ao listar arquivos.")
    } finally {
      setLoadingList(false)
    }
  }, [workflowId])

  // Carrega lista quando entrar em modo saved (ou no mount se ja for saved).
  useEffect(() => {
    if (mode === "saved" || (mode === "direct" && isUploadUri(value))) {
      refreshUploads()
    }
  }, [mode, refreshUploads, value])

  const handleUpload = useCallback(
    async (file: File) => {
      if (!workflowId) {
        setUploadError("workflow_id nao disponivel — salve o workflow antes de fazer upload.")
        return
      }
      setUploading(true)
      setUploadProgress(0)
      setUploadError(null)
      try {
        const result = await uploadWorkflowFile(workflowId, file, (loaded, total) => {
          setUploadProgress(total > 0 ? Math.round((loaded / total) * 100) : 0)
        })
        onChange(`${UPLOAD_SCHEME}${result.file_id}`)
        await refreshUploads()
        setMode("saved")
      } catch (err) {
        setUploadError((err as Error).message || "Falha no upload.")
      } finally {
        setUploading(false)
      }
    },
    [workflowId, onChange, refreshUploads],
  )

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) handleUpload(f)
    // Reset input pra permitir re-selecionar o mesmo arquivo.
    e.target.value = ""
  }

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragActive(false)
    const f = e.dataTransfer.files?.[0]
    if (f) handleUpload(f)
  }

  const handleDeleteSaved = async (fileId: string) => {
    if (!workflowId) return
    try {
      await deleteWorkflowUpload(workflowId, fileId)
      await refreshUploads()
      // Se o arquivo deletado era o selecionado, limpa value.
      if (currentFileId === fileId) onChange("")
    } catch (err) {
      setListError((err as Error).message || "Falha ao remover.")
    }
  }

  // Se o value ja e shift-upload://, mostra chip + botao trocar.
  if (currentFileId && !uploading) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2">
        <FileSpreadsheet className="size-4 shrink-0 text-emerald-500" />
        <span className="flex-1 truncate text-sm">
          {currentUploadMeta?.original_filename ?? currentFileId}
          {currentUploadMeta && (
            <span className="ml-2 text-xs text-muted-foreground">
              {formatBytes(currentUploadMeta.size_bytes)}
            </span>
          )}
        </span>
        <button
          type="button"
          onClick={() => onChange("")}
          className="text-xs text-muted-foreground hover:text-foreground"
          disabled={disabled}
          aria-label="Trocar arquivo"
        >
          Trocar
        </button>
      </div>
    )
  }

  // Se o value ja e {{vars.X}}, mostra chip de variavel.
  if (currentVarName) {
    const v = fileUploadVars.find((vv) => vv.name === currentVarName)
    return (
      <div className="space-y-1">
        <div className="flex items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2">
          <Variable className="size-4 shrink-0 text-violet-500" />
          <span className="flex-1 truncate text-sm">
            <span className="font-mono">{currentVarName}</span>
            {!v && (
              <span className="ml-2 text-xs text-amber-500">
                (variável não encontrada)
              </span>
            )}
          </span>
          <button
            type="button"
            onClick={() => onChange("")}
            className="text-xs text-muted-foreground hover:text-foreground"
            disabled={disabled}
            aria-label="Trocar variável"
          >
            Trocar
          </button>
        </div>
        <p className="text-[11px] text-muted-foreground">
          O arquivo será solicitado quando o fluxo for executado.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {/* Tabs de modo */}
      <div role="tablist" className="flex rounded-md border border-border p-0.5 text-xs">
        <ModeTab active={mode === "direct"} onClick={() => setMode("direct")} icon={<Globe className="size-3" />}>
          URL / Path
        </ModeTab>
        <ModeTab active={mode === "saved"} onClick={() => setMode("saved")} icon={<FileSpreadsheet className="size-3" />}>
          Do projeto
        </ModeTab>
        <ModeTab active={mode === "upload"} onClick={() => setMode("upload")} icon={<Upload className="size-3" />}>
          Enviar
        </ModeTab>
        <ModeTab active={mode === "variable"} onClick={() => setMode("variable")} icon={<Variable className="size-3" />}>
          Variável
        </ModeTab>
      </div>

      {/* Modo: URL direto */}
      {mode === "direct" && (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        />
      )}

      {/* Modo: Arquivo do projeto */}
      {mode === "saved" && (
        <div className="space-y-2">
          {!workflowId && (
            <p className="text-xs text-amber-500">
              Salve o workflow antes pra usar arquivos do projeto.
            </p>
          )}
          {workflowId && loadingList && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="size-3 animate-spin" />
              Carregando arquivos...
            </div>
          )}
          {workflowId && listError && (
            <p className="text-xs text-destructive">{listError}</p>
          )}
          {workflowId && uploads !== null && uploads.length === 0 && !loadingList && (
            <p className="text-xs text-muted-foreground">
              Nenhum arquivo enviado ainda. Use a aba &ldquo;Enviar&rdquo;.
            </p>
          )}
          {workflowId && uploads !== null && uploads.length > 0 && (
            <ul className="max-h-48 overflow-auto rounded-md border border-border divide-y divide-border">
              {uploads.map((u) => {
                const selected = currentFileId === u.file_id
                return (
                  <li
                    key={u.file_id}
                    className={`flex items-center gap-2 px-3 py-2 text-sm hover:bg-muted/50 ${
                      selected ? "bg-muted/40" : ""
                    }`}
                  >
                    <button
                      type="button"
                      className="flex flex-1 items-center gap-2 text-left"
                      onClick={() => onChange(`${UPLOAD_SCHEME}${u.file_id}`)}
                      disabled={disabled}
                    >
                      <FileSpreadsheet className="size-4 shrink-0 text-emerald-500" />
                      <span className="flex-1 truncate">{u.original_filename}</span>
                      <span className="text-xs text-muted-foreground">
                        {formatBytes(u.size_bytes)}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDeleteSaved(u.file_id)}
                      className="text-muted-foreground hover:text-destructive"
                      aria-label={`Remover ${u.original_filename}`}
                      disabled={disabled}
                    >
                      <X className="size-3.5" />
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}

      {/* Modo: Upload novo */}
      {mode === "upload" && (
        <div className="space-y-2">
          {!workflowId && (
            <p className="text-xs text-amber-500">
              Salve o workflow antes pra fazer upload.
            </p>
          )}
          <div
            onDragEnter={(e) => {
              e.preventDefault()
              setDragActive(true)
            }}
            onDragOver={(e) => e.preventDefault()}
            onDragLeave={() => setDragActive(false)}
            onDrop={handleDrop}
            className={`flex flex-col items-center justify-center gap-2 rounded-md border-2 border-dashed px-4 py-8 text-sm transition ${
              dragActive
                ? "border-emerald-500 bg-emerald-500/10"
                : "border-border bg-muted/20"
            } ${!workflowId || disabled ? "opacity-50" : "cursor-pointer hover:bg-muted/40"}`}
            onClick={() => {
              if (workflowId && !disabled && !uploading) fileInputRef.current?.click()
            }}
            role="button"
            tabIndex={0}
          >
            {uploading ? (
              <>
                <Loader2 className="size-5 animate-spin" />
                <p className="text-muted-foreground">
                  Enviando... {uploadProgress}%
                </p>
                <div className="h-1.5 w-full max-w-xs overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full bg-emerald-500 transition-all"
                    style={{ width: `${uploadProgress}%` }}
                  />
                </div>
              </>
            ) : (
              <>
                <Upload className="size-5 text-muted-foreground" />
                <p>Arraste um arquivo ou clique pra selecionar</p>
                {accept && (
                  <p className="text-xs text-muted-foreground">Aceita: {accept}</p>
                )}
              </>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept={accept}
              className="hidden"
              onChange={handleFileInput}
              disabled={!workflowId || disabled || uploading}
            />
          </div>
          {uploadError && <p className="text-xs text-destructive">{uploadError}</p>}
        </div>
      )}

      {/* Modo: Variavel */}
      {mode === "variable" && (
        <div className="space-y-2">
          {fileUploadVars.length === 0 ? (
            <div className="rounded-md border border-dashed border-border bg-muted/20 px-3 py-4 text-xs text-muted-foreground">
              Nenhuma variável de tipo &ldquo;arquivo&rdquo; cadastrada neste workflow.
              Cadastre uma em <span className="font-medium">Variáveis do workflow</span> com tipo
              &ldquo;Arquivo&rdquo; pra usar aqui.
            </div>
          ) : (
            <>
              <select
                value={currentVarName ?? ""}
                onChange={(e) => {
                  const name = e.target.value
                  if (name) onChange(`{{vars.${name}}}`)
                  else onChange("")
                }}
                disabled={disabled}
                className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-60"
              >
                <option value="">Selecione uma variável…</option>
                {fileUploadVars.map((v) => (
                  <option key={v.name} value={v.name}>
                    {v.name}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-muted-foreground">
                O arquivo será solicitado quando o fluxo for executado — ideal pra
                CSVs que mudam a cada execução.
              </p>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function ModeTab({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean
  onClick: () => void
  icon?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`flex flex-1 items-center justify-center gap-1.5 rounded-sm px-2 py-1.5 transition ${
        active
          ? "bg-foreground/10 text-foreground"
          : "text-muted-foreground hover:text-foreground"
      }`}
    >
      {icon}
      <span>{children}</span>
    </button>
  )
}
