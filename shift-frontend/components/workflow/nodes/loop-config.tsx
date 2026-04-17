"use client"

import { useEffect, useMemo, useState } from "react"
import { ChevronDown, Loader2, Plus, Search, Trash2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"
import {
  listCallableWorkflows,
  listWorkflowVersions,
  type CallableWorkflowSummary,
  type WorkflowParam,
} from "@/lib/api/workflow-versions"

type LoopMode = "sequential" | "parallel"
type OnItemError = "fail_fast" | "continue" | "collect"
type VersionSpec = number | "latest"

interface ExtraInputRow {
  name: string
  path: string
}

interface LoopConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

function extraInputsToRows(
  value: Record<string, string> | undefined,
): ExtraInputRow[] {
  if (!value) return []
  return Object.entries(value).map(([name, path]) => ({ name, path }))
}

function rowsToExtraInputs(rows: ExtraInputRow[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (const row of rows) {
    const key = row.name.trim()
    if (!key) continue
    out[key] = row.path
  }
  return out
}

export function LoopConfig({ data, onUpdate }: LoopConfigProps) {
  const upstreamFields = useUpstreamFields()

  const [workflows, setWorkflows] = useState<CallableWorkflowSummary[]>([])
  const [workflowsLoading, setWorkflowsLoading] = useState(false)
  const [workflowsError, setWorkflowsError] = useState<string | null>(null)
  const [showWorkflowPicker, setShowWorkflowPicker] = useState(false)
  const [workflowSearch, setWorkflowSearch] = useState("")

  const [targetInputs, setTargetInputs] = useState<WorkflowParam[]>([])
  const [inputsLoading, setInputsLoading] = useState(false)

  const sourceField = (data.source_field as string) ?? ""
  const workflowId = (data.workflow_id as string) ?? ""
  const workflowVersion = (data.workflow_version as VersionSpec) ?? "latest"
  const itemParamName = (data.item_param_name as string) ?? "item"
  const indexParamName = (data.index_param_name as string) ?? ""
  const mode = ((data.mode as LoopMode) ?? "sequential") as LoopMode
  const maxParallelism = (data.max_parallelism as number) ?? 4
  const onItemError = ((data.on_item_error as OnItemError) ?? "fail_fast") as OnItemError
  const maxIterations = (data.max_iterations as number) ?? 10000
  const outputField = (data.output_field as string) ?? "loop_result"
  const extraInputs = extraInputsToRows(
    data.extra_inputs as Record<string, string> | undefined,
  )

  const selectedWorkflow = useMemo(
    () => workflows.find((w) => w.workflow_id === workflowId) ?? null,
    [workflows, workflowId],
  )

  useEffect(() => {
    setWorkflowsLoading(true)
    setWorkflowsError(null)
    listCallableWorkflows()
      .then((rows) => setWorkflows(rows))
      .catch((err) => {
        setWorkflows([])
        setWorkflowsError(
          err instanceof Error ? err.message : "Falha ao carregar workflows.",
        )
      })
      .finally(() => setWorkflowsLoading(false))
  }, [])

  useEffect(() => {
    if (!workflowId) {
      setTargetInputs([])
      return
    }
    setInputsLoading(true)
    listWorkflowVersions(workflowId)
      .then((versions) => {
        if (versions.length === 0) {
          setTargetInputs([])
          return
        }
        const target =
          workflowVersion === "latest"
            ? versions[0]
            : versions.find((v) => v.version === workflowVersion) ?? versions[0]
        setTargetInputs(target?.input_schema ?? [])
      })
      .catch(() => setTargetInputs([]))
      .finally(() => setInputsLoading(false))
  }, [workflowId, workflowVersion])

  function update(patch: Record<string, unknown>) {
    onUpdate({ ...data, ...patch })
  }

  function selectWorkflow(wf: CallableWorkflowSummary) {
    update({
      workflow_id: wf.workflow_id,
      workflow_version: "latest",
      label: `For Each: ${wf.name}`,
    })
    setShowWorkflowPicker(false)
    setWorkflowSearch("")
  }

  function setExtraInputs(next: ExtraInputRow[]) {
    update({ extra_inputs: rowsToExtraInputs(next) })
  }

  function addExtraInput() {
    setExtraInputs([...extraInputs, { name: "", path: "" }])
  }

  function updateExtraInput(index: number, patch: Partial<ExtraInputRow>) {
    setExtraInputs(
      extraInputs.map((r, i) => (i === index ? { ...r, ...patch } : r)),
    )
  }

  function removeExtraInput(index: number) {
    setExtraInputs(extraInputs.filter((_, i) => i !== index))
  }

  const filteredWorkflows = workflowSearch
    ? workflows.filter(
        (w) =>
          w.name.toLowerCase().includes(workflowSearch.toLowerCase()) ||
          (w.description ?? "")
            .toLowerCase()
            .includes(workflowSearch.toLowerCase()),
      )
    : workflows

  const itemParamDeclared = targetInputs.some((p) => p.name === itemParamName)
  const indexParamDeclared =
    !indexParamName || targetInputs.some((p) => p.name === indexParamName)
  const extraInputsDeclared = extraInputs.every(
    (r) => !r.name.trim() || targetInputs.some((p) => p.name === r.name),
  )

  const previewLines: string[] = []
  if (selectedWorkflow) {
    previewLines.push(
      `Executará "${selectedWorkflow.name}" (v${
        workflowVersion === "latest" ? selectedWorkflow.latest_version : workflowVersion
      }) para cada item de \`${sourceField || "…"}\`.`,
    )
    previewLines.push(
      mode === "parallel"
        ? `Paralelo — até ${maxParallelism} em voo simultâneos.`
        : "Sequencial — uma iteração por vez.",
    )
    const limit =
      onItemError === "fail_fast"
        ? "Aborta no primeiro erro."
        : onItemError === "continue"
          ? "Ignora falhas silenciosamente."
          : "Coleta sucessos e falhas separadamente."
    previewLines.push(limit)
    previewLines.push(`Limite: até ${maxIterations.toLocaleString()} iterações.`)
  }

  return (
    <div className="space-y-4">
      {/* ── Origem dos itens ── */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Origem dos itens (dotted path)
        </label>
        {upstreamFields.length > 0 ? (
          <select
            value={sourceField}
            onChange={(e) => update({ source_field: e.target.value })}
            className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary"
          >
            <option value="">Selecionar campo...</option>
            {upstreamFields.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        ) : (
          <input
            type="text"
            value={sourceField}
            onChange={(e) => update({ source_field: e.target.value })}
            placeholder="upstream_results.no.data"
            className="h-8 w-full rounded-md border border-input bg-background px-2.5 font-mono text-xs outline-none focus:ring-1 focus:ring-primary"
          />
        )}
        <p className="text-[10px] text-muted-foreground">
          Aceita lista inline, dict único ou referência DuckDB. Datasets são
          streamed em chunks.
        </p>
      </div>

      {/* ── Workflow alvo ── */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Workflow a executar por item
        </label>
        <div className="relative">
          <button
            type="button"
            onClick={() => setShowWorkflowPicker(!showWorkflowPicker)}
            className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 text-xs transition-colors hover:bg-muted/50"
          >
            {workflowsLoading ? (
              <span className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" /> Carregando...
              </span>
            ) : selectedWorkflow ? (
              <span className="font-medium text-foreground">
                {selectedWorkflow.name}
              </span>
            ) : (
              <span className="text-muted-foreground">
                Selecionar workflow publicado...
              </span>
            )}
            <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
          </button>

          {showWorkflowPicker && (
            <div className="absolute left-0 top-full z-30 mt-1 max-h-[220px] w-full overflow-y-auto rounded-md border border-border bg-popover shadow-lg">
              <div className="sticky top-0 border-b border-border bg-popover p-1.5">
                <div className="flex items-center gap-1.5 rounded-md border border-input bg-background px-2">
                  <Search className="size-3 text-muted-foreground" />
                  <input
                    type="text"
                    value={workflowSearch}
                    onChange={(e) => setWorkflowSearch(e.target.value)}
                    placeholder="Buscar workflow..."
                    className="h-7 flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
                    autoFocus
                  />
                </div>
              </div>
              {filteredWorkflows.map((w) => (
                <button
                  key={w.workflow_id}
                  type="button"
                  onClick={() => selectWorkflow(w)}
                  className={cn(
                    "flex w-full flex-col gap-0.5 px-3 py-2 text-left text-xs transition-colors hover:bg-muted",
                    w.workflow_id === workflowId && "bg-accent",
                  )}
                >
                  <span className="font-medium">{w.name}</span>
                  <span className="text-[10px] text-muted-foreground">
                    v{w.latest_version} — {w.versions.length} versões publicadas
                  </span>
                </button>
              ))}
              {!workflowsLoading && filteredWorkflows.length === 0 && (
                <p className="px-3 py-2 text-[10px] text-muted-foreground">
                  Nenhum workflow publicado.
                </p>
              )}
            </div>
          )}
        </div>
        {workflowsError && (
          <p className="text-[10px] text-destructive">{workflowsError}</p>
        )}
      </div>

      {/* ── Versão ── */}
      {selectedWorkflow && (
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Versão
          </label>
          <select
            value={String(workflowVersion)}
            onChange={(e) =>
              update({
                workflow_version:
                  e.target.value === "latest"
                    ? "latest"
                    : Number(e.target.value),
              })
            }
            className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary"
          >
            <option value="latest">latest (v{selectedWorkflow.latest_version})</option>
            {selectedWorkflow.versions
              .slice()
              .reverse()
              .map((v) => (
                <option key={v} value={v}>
                  v{v}
                </option>
              ))}
          </select>
        </div>
      )}

      {/* ── Mapeamento de inputs ── */}
      {workflowId && (
        <div className="rounded-md border border-border bg-muted/30 p-3 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-foreground">
              Mapeamento de inputs
            </span>
            {inputsLoading && (
              <Loader2 className="size-3 animate-spin text-muted-foreground" />
            )}
          </div>

          <div className="space-y-1.5">
            <label className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              Nome do input para o item corrente
            </label>
            {targetInputs.length > 0 ? (
              <select
                value={itemParamName}
                onChange={(e) => update({ item_param_name: e.target.value })}
                className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary"
              >
                {!itemParamDeclared && (
                  <option value={itemParamName}>
                    {itemParamName} (não declarado)
                  </option>
                )}
                {targetInputs.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.name} {p.required ? "*" : ""}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                value={itemParamName}
                onChange={(e) => update({ item_param_name: e.target.value })}
                placeholder="item"
                className="h-8 w-full rounded-md border border-input bg-background px-2.5 font-mono text-xs outline-none focus:ring-1 focus:ring-primary"
              />
            )}
          </div>

          <div className="space-y-1.5">
            <label className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              Nome do input para o índice (opcional)
            </label>
            <input
              type="text"
              value={indexParamName}
              onChange={(e) => update({ index_param_name: e.target.value })}
              placeholder="idx"
              className="h-8 w-full rounded-md border border-input bg-background px-2.5 font-mono text-xs outline-none focus:ring-1 focus:ring-primary"
            />
            {indexParamName && !indexParamDeclared && (
              <p className="text-[10px] text-amber-500">
                Input "{indexParamName}" não declarado no workflow alvo.
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                Inputs extras (constantes por iteração)
              </label>
              <button
                type="button"
                onClick={addExtraInput}
                className="flex items-center gap-1 text-[10px] font-medium text-primary transition-colors hover:text-primary/80"
              >
                <Plus className="size-3" />
                Adicionar
              </button>
            </div>
            {extraInputs.length > 0 && (
              <div className="space-y-1.5">
                {extraInputs.map((row, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <input
                      type="text"
                      value={row.name}
                      onChange={(e) =>
                        updateExtraInput(i, { name: e.target.value })
                      }
                      placeholder="nome_input"
                      className="h-7 flex-1 rounded-md border border-input bg-background px-2 font-mono text-xs outline-none focus:ring-1 focus:ring-primary"
                    />
                    <input
                      type="text"
                      value={row.path}
                      onChange={(e) =>
                        updateExtraInput(i, { path: e.target.value })
                      }
                      placeholder="upstream_results.no.campo"
                      className="h-7 flex-1 rounded-md border border-input bg-background px-2 font-mono text-xs outline-none focus:ring-1 focus:ring-primary"
                    />
                    <button
                      type="button"
                      onClick={() => removeExtraInput(i)}
                      className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                    >
                      <Trash2 className="size-3" />
                    </button>
                  </div>
                ))}
              </div>
            )}
            {!extraInputsDeclared && (
              <p className="text-[10px] text-amber-500">
                Há inputs extras não declarados no workflow alvo.
              </p>
            )}
          </div>
        </div>
      )}

      {/* ── Modo ── */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Modo de execução
        </label>
        <select
          value={mode}
          onChange={(e) => update({ mode: e.target.value as LoopMode })}
          className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary"
        >
          <option value="sequential">sequential — uma iteração por vez</option>
          <option value="parallel">parallel — em paralelo com limite</option>
        </select>
      </div>

      {mode === "parallel" && (
        <div className="space-y-1.5">
          <label className="flex items-center justify-between text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            <span>Paralelismo máximo</span>
            <span className="text-foreground">{maxParallelism}</span>
          </label>
          <input
            type="range"
            min={1}
            max={32}
            value={maxParallelism}
            onChange={(e) =>
              update({ max_parallelism: Number(e.target.value) })
            }
            className="w-full accent-primary"
          />
        </div>
      )}

      {/* ── Política de erro ── */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Política de erro por item
        </label>
        <select
          value={onItemError}
          onChange={(e) =>
            update({ on_item_error: e.target.value as OnItemError })
          }
          className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary"
        >
          <option value="fail_fast">fail_fast — aborta no 1º erro</option>
          <option value="continue">continue — ignora falhas silenciosamente</option>
          <option value="collect">collect — separa successes/failures</option>
        </select>
      </div>

      {/* ── Guards ── */}
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            max_iterations
          </label>
          <input
            type="number"
            value={maxIterations}
            onChange={(e) =>
              update({ max_iterations: parseInt(e.target.value, 10) || 1 })
            }
            min={1}
            max={1_000_000}
            className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs outline-none focus:ring-1 focus:ring-primary"
          />
        </div>

        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Campo de saída
          </label>
          <input
            type="text"
            value={outputField}
            onChange={(e) => update({ output_field: e.target.value })}
            placeholder="loop_result"
            className="h-8 w-full rounded-md border border-input bg-background px-2.5 font-mono text-xs outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
      </div>

      {/* ── Preview ── */}
      {previewLines.length > 0 && (
        <div className="rounded-md border border-dashed border-violet-500/40 bg-violet-500/5 p-3">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-violet-500">
            Preview
          </p>
          <ul className="space-y-0.5 text-[11px] leading-relaxed text-foreground">
            {previewLines.map((line, i) => (
              <li key={i}>• {line}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="rounded-md border border-dashed border-amber-500/30 bg-amber-500/5 p-3">
        <p className="text-[10px] leading-relaxed text-amber-600 dark:text-amber-400">
          Loops aninhados não são permitidos — um workflow invocado pelo loop
          não pode conter outro nó loop (direta ou indiretamente via
          call_workflow).
        </p>
      </div>
    </div>
  )
}
