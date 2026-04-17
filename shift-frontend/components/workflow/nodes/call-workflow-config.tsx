"use client"

import { useEffect, useMemo, useState } from "react"
import {
  AlertTriangle,
  ChevronDown,
  Info,
  Loader2,
  RefreshCw,
  Search,
  Workflow as WorkflowIcon,
} from "lucide-react"
import { cn } from "@/lib/utils"
import {
  listCallableWorkflows,
  listWorkflowVersions,
  type CallableWorkflowSummary,
  type WorkflowParam,
} from "@/lib/api/workflow-versions"

type VersionSpec = number | "latest"

interface CallWorkflowConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

export function CallWorkflowConfig({ data, onUpdate }: CallWorkflowConfigProps) {
  const workflowId = (data.workflow_id as string) ?? ""
  const version = (data.version as VersionSpec) ?? "latest"
  const inputMapping =
    (data.input_mapping as Record<string, string> | undefined) ?? {}
  const outputField = (data.output_field as string) ?? "workflow_result"
  const timeoutSeconds = (data.timeout_seconds as number) ?? 300

  // ── Workflows list ─────────────────────────────────────────────────────
  const [workflows, setWorkflows] = useState<CallableWorkflowSummary[]>([])
  const [workflowsLoading, setWorkflowsLoading] = useState(false)
  const [workflowsError, setWorkflowsError] = useState<string | null>(null)
  const [showPicker, setShowPicker] = useState(false)
  const [search, setSearch] = useState("")

  // ── Versions for selected workflow ─────────────────────────────────────
  const [versionsList, setVersionsList] = useState<
    Array<{ version: number; input_schema: WorkflowParam[] }>
  >([])
  const [versionsLoading, setVersionsLoading] = useState(false)
  const [versionsError, setVersionsError] = useState<string | null>(null)
  const [versionsReloadKey, setVersionsReloadKey] = useState(0)

  function loadWorkflows() {
    setWorkflowsLoading(true)
    setWorkflowsError(null)
    listCallableWorkflows()
      .then((rows) => setWorkflows(rows))
      .catch((err) => {
        setWorkflows([])
        setWorkflowsError(
          err instanceof Error
            ? err.message
            : "Falha ao carregar workflows disponíveis.",
        )
      })
      .finally(() => setWorkflowsLoading(false))
  }

  useEffect(() => {
    loadWorkflows()
  }, [])

  useEffect(() => {
    if (!workflowId) {
      setVersionsList([])
      setVersionsError(null)
      return
    }
    setVersionsLoading(true)
    setVersionsError(null)
    listWorkflowVersions(workflowId)
      .then((rows) => {
        setVersionsList(
          rows.map((r) => ({
            version: r.version,
            input_schema: r.input_schema ?? [],
          })),
        )
      })
      .catch((err) => {
        setVersionsList([])
        setVersionsError(
          err instanceof Error
            ? err.message
            : "Falha ao carregar versões do workflow.",
        )
      })
      .finally(() => setVersionsLoading(false))
  }, [workflowId, versionsReloadKey])

  const selectedWorkflow = useMemo(
    () => workflows.find((w) => w.workflow_id === workflowId) ?? null,
    [workflows, workflowId],
  )

  const publishedVersionNumbers = useMemo(
    () => versionsList.map((v) => v.version).sort((a, b) => b - a),
    [versionsList],
  )

  const resolvedVersion = useMemo(() => {
    if (version === "latest") {
      return publishedVersionNumbers[0] ?? null
    }
    return version
  }, [version, publishedVersionNumbers])

  const resolvedInputSchema = useMemo<WorkflowParam[]>(() => {
    if (resolvedVersion == null) return []
    const v = versionsList.find((vv) => vv.version === resolvedVersion)
    return v?.input_schema ?? []
  }, [versionsList, resolvedVersion])

  // Warnings
  const workflowMissing =
    !!workflowId &&
    !workflowsLoading &&
    !workflowsError &&
    !workflows.some((w) => w.workflow_id === workflowId)

  const versionMissing =
    !!workflowId &&
    !versionsLoading &&
    !versionsError &&
    typeof version === "number" &&
    !publishedVersionNumbers.includes(version)

  function update(patch: Record<string, unknown>) {
    onUpdate({ ...data, ...patch })
  }

  function selectWorkflow(wf: CallableWorkflowSummary) {
    update({
      workflow_id: wf.workflow_id,
      version: "latest",
      input_mapping: {},
      label: `Chamar: ${wf.name}`,
    })
    setShowPicker(false)
    setSearch("")
  }

  function setInputMappingValue(name: string, value: string) {
    const next = { ...inputMapping }
    if (value.trim() === "") {
      delete next[name]
    } else {
      next[name] = value
    }
    update({ input_mapping: next })
  }

  const filteredWorkflows = search.trim()
    ? workflows.filter(
        (w) =>
          w.name.toLowerCase().includes(search.toLowerCase()) ||
          (w.description ?? "").toLowerCase().includes(search.toLowerCase()),
      )
    : workflows

  const requiredInputsMissing = resolvedInputSchema.filter(
    (p) => (p.required ?? true) && !inputMapping[p.name]?.trim(),
  )

  return (
    <div className="space-y-4">
      {/* ── Workflow picker ── */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Workflow a invocar
        </label>
        <div className="relative">
          <button
            type="button"
            onClick={() => setShowPicker((v) => !v)}
            aria-haspopup="listbox"
            aria-expanded={showPicker}
            className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 text-xs transition-colors hover:bg-muted/50"
          >
            {workflowsLoading ? (
              <span className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" /> Carregando…
              </span>
            ) : selectedWorkflow ? (
              <span className="flex items-center gap-2 truncate font-medium text-foreground">
                <WorkflowIcon className="size-3.5 shrink-0 text-indigo-500" />
                {selectedWorkflow.name}
              </span>
            ) : workflowId ? (
              <span className="flex items-center gap-1.5 text-amber-600 dark:text-amber-400">
                <AlertTriangle className="size-3.5" />
                Workflow não disponível
              </span>
            ) : (
              <span className="text-muted-foreground">
                Selecionar workflow publicado…
              </span>
            )}
            <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
          </button>

          {showPicker && (
            <div className="absolute left-0 top-full z-30 mt-1 max-h-[260px] w-full overflow-y-auto rounded-md border border-border bg-popover shadow-lg">
              <div className="sticky top-0 border-b border-border bg-popover p-1.5">
                <div className="flex items-center gap-1.5 rounded-md border border-input bg-background px-2">
                  <Search className="size-3 text-muted-foreground" />
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Buscar workflow…"
                    className="h-7 flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
                    autoFocus
                  />
                </div>
              </div>
              {filteredWorkflows.length === 0 ? (
                <p className="px-3 py-3 text-[11px] text-muted-foreground">
                  Nenhum workflow publicado disponível.
                </p>
              ) : (
                filteredWorkflows.map((w) => (
                  <button
                    key={w.workflow_id}
                    type="button"
                    onClick={() => selectWorkflow(w)}
                    className={cn(
                      "flex w-full flex-col gap-0.5 px-3 py-2 text-left text-xs transition-colors hover:bg-muted",
                      w.workflow_id === workflowId && "bg-accent",
                    )}
                  >
                    <span className="font-medium text-foreground">{w.name}</span>
                    {w.description && (
                      <span className="line-clamp-1 text-[10px] text-muted-foreground">
                        {w.description}
                      </span>
                    )}
                    <span className="text-[10px] text-muted-foreground">
                      v{w.latest_version} · {w.versions.length} versões publicadas
                    </span>
                  </button>
                ))
              )}
            </div>
          )}
        </div>
        {workflowsError && (
          <div className="flex items-center justify-between gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-2 py-1.5">
            <p className="text-[10px] text-destructive">{workflowsError}</p>
            <button
              type="button"
              onClick={loadWorkflows}
              className="flex items-center gap-1 text-[10px] font-medium text-destructive hover:underline"
            >
              <RefreshCw className="size-3" /> Tentar novamente
            </button>
          </div>
        )}
        {workflowMissing && (
          <p className="flex items-center gap-1 text-[10px] text-amber-600 dark:text-amber-400">
            <AlertTriangle className="size-3" />
            Workflow referenciado não está mais disponível — selecione outro.
          </p>
        )}
      </div>

      {/* ── Version selector ── */}
      {workflowId && (
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Versão
          </label>
          {versionsLoading ? (
            <div className="flex h-8 items-center gap-2 text-[11px] text-muted-foreground">
              <Loader2 className="size-3 animate-spin" /> Carregando versões…
            </div>
          ) : versionsError ? (
            <div className="flex items-center justify-between gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-2 py-1.5">
              <p className="text-[10px] text-destructive">{versionsError}</p>
              <button
                type="button"
                onClick={() => setVersionsReloadKey((k) => k + 1)}
                className="flex items-center gap-1 text-[10px] font-medium text-destructive hover:underline"
              >
                <RefreshCw className="size-3" /> Tentar novamente
              </button>
            </div>
          ) : publishedVersionNumbers.length === 0 ? (
            <p className="rounded-md border border-dashed border-border bg-muted/30 px-2 py-2 text-[11px] text-muted-foreground">
              Este workflow ainda não tem versões publicadas.
            </p>
          ) : (
            <>
              <select
                value={String(version)}
                onChange={(e) =>
                  update({
                    version:
                      e.target.value === "latest"
                        ? "latest"
                        : Number(e.target.value),
                    input_mapping: {},
                  })
                }
                className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="latest">
                  Mais recente (v{publishedVersionNumbers[0]})
                </option>
                {publishedVersionNumbers.map((v) => (
                  <option key={v} value={v}>
                    v{v}
                  </option>
                ))}
              </select>
              {versionMissing && (
                <p className="flex items-center gap-1 text-[10px] text-amber-600 dark:text-amber-400">
                  <AlertTriangle className="size-3" />
                  Versão {typeof version === "number" ? version : ""} não
                  encontrada — escolha outra.
                </p>
              )}
            </>
          )}
        </div>
      )}

      {/* ── Input mapping ── */}
      {workflowId && resolvedVersion != null && (
        <div className="space-y-2 rounded-md border border-border bg-muted/30 p-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-foreground">
              Mapeamento de inputs
            </span>
            <span className="text-[10px] text-muted-foreground">
              v{resolvedVersion}
            </span>
          </div>

          {resolvedInputSchema.length === 0 ? (
            <p className="text-[11px] text-muted-foreground">
              Este workflow não declara inputs.
            </p>
          ) : (
            <div className="space-y-2.5">
              {resolvedInputSchema.map((param) => {
                const currentValue = inputMapping[param.name] ?? ""
                const isRequired = param.required ?? true
                const isEmpty = !currentValue.trim()
                const isInvalid = isRequired && isEmpty
                const placeholder =
                  param.default !== undefined && param.default !== null
                    ? "Deixe vazio para usar default"
                    : "upstream.node_id.campo"

                return (
                  <div key={param.name} className="space-y-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <label
                        htmlFor={`cw-input-${param.name}`}
                        className="font-mono text-[11px] font-medium text-foreground"
                      >
                        {param.name}
                      </label>
                      <span className="rounded bg-muted px-1 py-0.5 text-[9px] font-mono text-muted-foreground">
                        {param.type}
                      </span>
                      {isRequired ? (
                        <span className="rounded bg-destructive/10 px-1 py-0.5 text-[9px] font-medium text-destructive">
                          obrigatório
                        </span>
                      ) : (
                        <span className="rounded bg-muted px-1 py-0.5 text-[9px] text-muted-foreground">
                          opcional
                        </span>
                      )}
                      {param.description && (
                        <span
                          title={param.description}
                          className="inline-flex items-center"
                        >
                          <Info className="size-3 text-muted-foreground" />
                        </span>
                      )}
                    </div>
                    <input
                      id={`cw-input-${param.name}`}
                      type="text"
                      value={currentValue}
                      onChange={(e) =>
                        setInputMappingValue(param.name, e.target.value)
                      }
                      placeholder={placeholder}
                      aria-invalid={isInvalid}
                      className={`h-7 w-full rounded-md border bg-background px-2 font-mono text-xs outline-none focus:ring-1 ${
                        isInvalid
                          ? "border-destructive focus:ring-destructive"
                          : "border-input focus:ring-primary"
                      }`}
                    />
                    {param.description && (
                      <p className="text-[10px] leading-relaxed text-muted-foreground">
                        {param.description}
                      </p>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          {requiredInputsMissing.length > 0 && (
            <p className="flex items-start gap-1 text-[10px] text-amber-600 dark:text-amber-400">
              <AlertTriangle className="mt-0.5 size-3 shrink-0" />
              Inputs obrigatórios sem valor:{" "}
              {requiredInputsMissing.map((p) => p.name).join(", ")}
            </p>
          )}
        </div>
      )}

      {/* ── Output field & timeout ── */}
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Campo de saída
          </label>
          <input
            type="text"
            value={outputField}
            onChange={(e) => update({ output_field: e.target.value })}
            placeholder="workflow_result"
            className="h-8 w-full rounded-md border border-input bg-background px-2.5 font-mono text-xs outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Timeout (s)
          </label>
          <input
            type="number"
            min={1}
            max={600}
            value={timeoutSeconds}
            onChange={(e) =>
              update({
                timeout_seconds: Math.max(
                  1,
                  Math.min(600, parseInt(e.target.value, 10) || 300),
                ),
              })
            }
            className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
      </div>
    </div>
  )
}
