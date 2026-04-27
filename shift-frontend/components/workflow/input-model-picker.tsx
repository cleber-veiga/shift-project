"use client"

/**
 * InputModelPicker — dropdown que lista modelos de entrada do workspace
 * filtrados por file_type (default: csv). Usado pra vincular um modelo
 * de entrada a nos como csv_input/excel_input — o id e armazenado em
 * config.input_model_id e pode ser usado pra validacao futura.
 *
 * Self-contained: dado o workflowId, resolve o workspace_id via API.
 *
 * IMPORTANTE: SEM cache de modelos por workspace. O usuario pode criar/
 * editar/deletar modelos em outra aba e voltar aqui — cache stale escondia
 * modelos novos. O custo do fetch (~50ms) e baixo o suficiente. Apenas
 * o workflow→workspace resolve fica em cache (workflow.workspace_id nao
 * muda durante a sessao normal).
 */

import { useEffect, useRef, useState } from "react"
import { Loader2, FileText } from "lucide-react"
import {
  getWorkflow,
  listWorkspaceInputModels,
  type InputModel,
} from "@/lib/auth"

const _workflowToWorkspaceCache = new Map<string, string>()

export type InputModelPickerProps = {
  workflowId?: string
  value?: string | null
  onChange: (next: string | null) => void
  /** Filtra modelos por file_type. Default: csv. */
  fileType?: "csv" | "excel" | "data"
  disabled?: boolean
  /** Callback opcional disparado quando o modelo selecionado muda (incluindo
      no carregamento inicial). Util pra parents que precisam do schema_def
      do modelo (ex: ExcelNodeConfig usa pra popular dropdown de sheets). */
  onModelChange?: (model: InputModel | null) => void
}

export function InputModelPicker({
  workflowId,
  value,
  onChange,
  fileType = "csv",
  disabled = false,
  onModelChange,
}: InputModelPickerProps) {
  const [models, setModels] = useState<InputModel[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!workflowId) return
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      try {
        let workspaceId = _workflowToWorkspaceCache.get(workflowId!)
        if (!workspaceId) {
          const wf = await getWorkflow(workflowId!)
          workspaceId = wf.workspace_id ?? undefined
          if (workspaceId) _workflowToWorkspaceCache.set(workflowId!, workspaceId)
        }
        if (!workspaceId) {
          throw new Error("Workspace deste workflow nao encontrado.")
        }

        const list = await listWorkspaceInputModels(workspaceId)
        if (!cancelled) setModels(list)
      } catch (err) {
        if (!cancelled) {
          setError((err as Error).message || "Falha ao carregar modelos.")
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [workflowId])

  const filtered = (models ?? []).filter((m) => m.file_type === fileType)
  const selectedExists = value ? filtered.some((m) => m.id === value) : true

  // Notifica o parent quando o modelo selecionado mudar de fato (incluindo
  // primeira carga com value pre-existente). useRef evita disparar o
  // callback toda render por mudancas em onModelChange.
  const lastNotifiedIdRef = useRef<string | null>(null)
  useEffect(() => {
    if (!onModelChange || models === null) return
    const currentId = value ?? null
    if (lastNotifiedIdRef.current === currentId) return
    lastNotifiedIdRef.current = currentId
    const found = currentId
      ? filtered.find((m) => m.id === currentId) ?? null
      : null
    onModelChange(found)
  }, [value, models, filtered, onModelChange])

  return (
    <div className="space-y-1">
      {loading && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-3 animate-spin" />
          Carregando modelos…
        </div>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
      {!loading && !error && (
        <>
          <select
            value={value ?? ""}
            onChange={(e) => onChange(e.target.value || null)}
            disabled={disabled}
            className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-60"
          >
            <option value="">Sem modelo (sem validação)</option>
            {filtered.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
                {m.description ? ` — ${m.description.slice(0, 40)}` : ""}
              </option>
            ))}
            {/* Caso o id atual aponte para um modelo que nao existe mais
                (ex: deletado), mostra com label de aviso pra o usuario nao
                sumir o valor sem perceber. */}
            {value && !selectedExists && (
              <option value={value}>
                {value} (modelo removido)
              </option>
            )}
          </select>
          {filtered.length === 0 && (
            <p className="flex items-center gap-1 text-[11px] text-muted-foreground">
              <FileText className="size-3" />
              Nenhum modelo {fileType.toUpperCase()} cadastrado no workspace.
            </p>
          )}
          {value && selectedExists && (
            <p className="text-[11px] text-muted-foreground">
              O arquivo será comparado com a estrutura definida no modelo (validação na execução).
            </p>
          )}
        </>
      )}
    </div>
  )
}
