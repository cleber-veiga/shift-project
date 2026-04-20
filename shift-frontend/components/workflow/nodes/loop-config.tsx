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
import {
  useUpstreamOutputs,
  type UpstreamSummary,
} from "@/lib/workflow/upstream-fields-context"
import { getNodeDefinition } from "@/lib/workflow/types"
import { getNodeIcon } from "@/lib/workflow/node-icons"

type LoopMode = "sequential" | "parallel"
type OnItemError = "fail_fast" | "continue" | "collect"
type VersionSpec = number | "latest"

interface LoopConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

/**
 * Detecta caminhos plausíveis para iterar em cima do output de um upstream.
 * Retorna opções que produzem lista (array de dicts), referência DuckDB ou
 * dict único. Evita campos escalares — o loop precisa de iterável.
 */
function detectIterableOptions(
  up: UpstreamSummary,
): Array<{ path: string; label: string; hint: string }> {
  const options: Array<{ path: string; label: string; hint: string }> = []
  const out = up.output
  if (!out) {
    options.push({
      path: `upstream_results.${up.nodeId}`,
      label: "(saída inteira)",
      hint: "sem execução ainda",
    })
    return options
  }

  const isDuckRef = (v: unknown): boolean =>
    !!v &&
    typeof v === "object" &&
    !Array.isArray(v) &&
    (v as Record<string, unknown>).storage_type === "duckdb"

  if (isDuckRef(out)) {
    options.push({
      path: `upstream_results.${up.nodeId}`,
      label: "(tabela DuckDB)",
      hint: "streaming em chunks",
    })
  }

  for (const [key, val] of Object.entries(out)) {
    if (Array.isArray(val) && val.length > 0 && typeof val[0] === "object") {
      options.push({
        path: `upstream_results.${up.nodeId}.${key}`,
        label: `.${key}`,
        hint: `${val.length} itens`,
      })
    } else if (isDuckRef(val)) {
      options.push({
        path: `upstream_results.${up.nodeId}.${key}`,
        label: `.${key}`,
        hint: "tabela DuckDB",
      })
    }
  }

  if (options.length === 0) {
    options.push({
      path: `upstream_results.${up.nodeId}`,
      label: "(saída inteira — item único)",
      hint: "dict",
    })
  }
  return options
}

export function LoopConfig({ data, onUpdate }: LoopConfigProps) {
  const upstreamOutputs = useUpstreamOutputs()

  const [workflows, setWorkflows] = useState<CallableWorkflowSummary[]>([])
  const [workflowsLoading, setWorkflowsLoading] = useState(false)
  const [workflowsError, setWorkflowsError] = useState<string | null>(null)
  const [showWorkflowPicker, setShowWorkflowPicker] = useState(false)
  const [workflowSearch, setWorkflowSearch] = useState("")

  const [versionsList, setVersionsList] = useState<
    Array<{ version: number; input_schema: WorkflowParam[] }>
  >([])
  const [versionsLoading, setVersionsLoading] = useState(false)
  const [versionsError, setVersionsError] = useState<string | null>(null)
  const [versionsReloadKey, setVersionsReloadKey] = useState(0)

  const [dragOverField, setDragOverField] = useState<string | null>(null)
  const [showSourcePicker, setShowSourcePicker] = useState(false)

  const sourceField = (data.source_field as string) ?? ""
  const workflowId = (data.workflow_id as string) ?? ""
  const workflowVersion = (data.workflow_version as VersionSpec) ?? "latest"
  const inputMapping =
    (data.input_mapping as Record<string, string> | undefined) ?? {}
  const mode = ((data.mode as LoopMode) ?? "sequential") as LoopMode
  const maxParallelism = (data.max_parallelism as number) ?? 4
  const onItemError = ((data.on_item_error as OnItemError) ?? "fail_fast") as OnItemError
  const maxIterations = (data.max_iterations as number) ?? 10000
  const outputField = (data.output_field as string) ?? "loop_result"
  const timeoutSeconds = (data.timeout_seconds as number) ?? 300

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
      setVersionsList([])
      setVersionsError(null)
      return
    }
    setVersionsLoading(true)
    setVersionsError(null)
    listWorkflowVersions(workflowId)
      .then((rows) =>
        setVersionsList(
          rows.map((r) => ({
            version: r.version,
            input_schema: r.input_schema ?? [],
          })),
        ),
      )
      .catch((err) => {
        setVersionsList([])
        setVersionsError(
          err instanceof Error ? err.message : "Falha ao carregar versões.",
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
    if (workflowVersion === "latest") return publishedVersionNumbers[0] ?? null
    return workflowVersion
  }, [workflowVersion, publishedVersionNumbers])

  const resolvedInputSchema = useMemo<WorkflowParam[]>(() => {
    if (resolvedVersion == null) return []
    const v = versionsList.find((vv) => vv.version === resolvedVersion)
    return v?.input_schema ?? []
  }, [versionsList, resolvedVersion])

  /**
   * Extrai o nodeId do upstream que gera os itens a partir do source_field
   * (``upstream_results.<nodeId>.<path>``). Quando o usuario arrasta um
   * campo desse mesmo nodeId e o path comeca com o mesmo prefixo, tratamos
   * o restante como campo-do-item → emite ``{{item.<rest>}}``. Caso
   * contrario, emitimos referencia constante ``{{upstream_results…}}``.
   */
  const { sourceNodeId, sourcePathPrefix } = useMemo(() => {
    const m = sourceField.match(/^upstream_results\.([^.]+)\.(.+)$/)
    if (!m) return { sourceNodeId: null as string | null, sourcePathPrefix: "" }
    return { sourceNodeId: m[1], sourcePathPrefix: m[2] }
  }, [sourceField])

  function update(patch: Record<string, unknown>) {
    onUpdate({ ...data, ...patch })
  }

  function selectWorkflow(wf: CallableWorkflowSummary) {
    update({
      workflow_id: wf.workflow_id,
      workflow_version: "latest",
      input_mapping: {},
      label: `For Each: ${wf.name}`,
    })
    setShowWorkflowPicker(false)
    setWorkflowSearch("")
  }

  function setMappingValue(name: string, value: string) {
    const next = { ...inputMapping }
    if (value.trim() === "") delete next[name]
    else next[name] = value
    update({ input_mapping: next })
  }

  function handleFieldDragOver(e: React.DragEvent, paramName: string) {
    if (
      e.dataTransfer.types.includes("application/x-shift-field-ref") ||
      e.dataTransfer.types.includes("application/x-shift-field")
    ) {
      e.preventDefault()
      e.stopPropagation()
      e.dataTransfer.dropEffect = "copy"
      setDragOverField(paramName)
    }
  }

  function handleFieldDrop(e: React.DragEvent, paramName: string) {
    e.preventDefault()
    e.stopPropagation()
    setDragOverField(null)

    const refRaw = e.dataTransfer.getData("application/x-shift-field-ref")
    if (refRaw) {
      try {
        const ref = JSON.parse(refRaw) as { nodeId?: string; field?: string }
        if (ref.nodeId && ref.field) {
          // Mesmo nodeId do source → campo do item corrente. A schema view
          // ja achata linhas (array) como folhas, entao ref.field ja vem
          // relativo ao row — emitimos direto {{item.<field>}}. Se o
          // ref.field por acaso comecar com o prefixo do source (caso raro
          // de schema que preserva o path completo), descasca antes.
          if (sourceNodeId && ref.nodeId === sourceNodeId) {
            const prefix = sourcePathPrefix ? `${sourcePathPrefix}.` : ""
            const rel =
              prefix && ref.field.startsWith(prefix)
                ? ref.field.slice(prefix.length)
                : ref.field
            if (rel) {
              setMappingValue(paramName, `{{item.${rel}}}`)
              return
            }
          }
          setMappingValue(
            paramName,
            `{{upstream_results.${ref.nodeId}.${ref.field}}}`,
          )
          return
        }
      } catch {
        /* fallthrough */
      }
    }

    const field = e.dataTransfer.getData("application/x-shift-field")
    if (field) {
      // Sem nodeId — assume campo do item corrente.
      setMappingValue(paramName, `{{item.${field}}}`)
    }
  }

  function handleSourceDrop(e: React.DragEvent) {
    e.preventDefault()
    const refRaw = e.dataTransfer.getData("application/x-shift-field-ref")
    if (refRaw) {
      try {
        const ref = JSON.parse(refRaw) as { nodeId?: string; field?: string }
        if (ref.nodeId && ref.field) {
          update({ source_field: `upstream_results.${ref.nodeId}.${ref.field}` })
          return
        }
      } catch { /* fallthrough */ }
    }
    const col = e.dataTransfer.getData("application/x-shift-field")
    if (col) update({ source_field: col })
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

  const requiredMissing = resolvedInputSchema.filter(
    (p) => (p.required ?? true) && !inputMapping[p.name]?.trim(),
  )

  const previewLines: string[] = []
  if (selectedWorkflow) {
    previewLines.push(
      `Executará "${selectedWorkflow.name}" (v${
        workflowVersion === "latest"
          ? selectedWorkflow.latest_version
          : workflowVersion
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
    previewLines.push(`Cada item tem até ${timeoutSeconds}s para completar.`)
  }

  return (
    <div className="space-y-4">
      {/* ── Origem dos itens ── */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Origem dos itens
        </label>

        {/* Picker — lista cada upstream com as opções iteráveis detectadas */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setShowSourcePicker((v) => !v)}
            className={cn(
              "flex h-9 w-full items-center justify-between rounded-md border bg-background px-3 text-xs transition-colors hover:bg-muted/50",
              sourceField ? "border-input" : "border-destructive/60",
            )}
          >
            {sourceField ? (
              <span className="truncate font-mono text-foreground">
                {sourceField}
              </span>
            ) : (
              <span className="text-muted-foreground">
                Selecione um nó upstream…
              </span>
            )}
            <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
          </button>

          {showSourcePicker && (
            <div className="absolute left-0 top-full z-30 mt-1 max-h-[300px] w-full overflow-y-auto rounded-md border border-border bg-popover shadow-lg">
              {upstreamOutputs.length === 0 ? (
                <p className="px-3 py-3 text-[11px] text-muted-foreground">
                  Nenhum nó upstream conectado ao loop.
                </p>
              ) : (
                upstreamOutputs.map((up) => {
                  const def = getNodeDefinition(up.nodeType)
                  const NodeIcon = getNodeIcon(def?.icon ?? "Database")
                  const options = detectIterableOptions(up)
                  return (
                    <div key={up.nodeId} className="border-b border-border/60 last:border-b-0">
                      <div className="flex items-center gap-2 bg-muted/40 px-3 py-1.5">
                        <NodeIcon className="size-3 text-muted-foreground" />
                        <span className="text-[11px] font-medium text-foreground">
                          {up.label}
                        </span>
                        {up.depth > 1 && (
                          <span className="rounded bg-muted px-1 py-0.5 text-[9px] text-muted-foreground">
                            ancestral
                          </span>
                        )}
                      </div>
                      {options.map((opt) => (
                        <button
                          key={opt.path}
                          type="button"
                          onClick={() => {
                            update({ source_field: opt.path })
                            setShowSourcePicker(false)
                          }}
                          className={cn(
                            "flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-xs transition-colors hover:bg-muted",
                            sourceField === opt.path && "bg-accent",
                          )}
                        >
                          <span className="flex flex-col">
                            <span className="font-mono text-foreground">{opt.label}</span>
                            <span className="font-mono text-[10px] text-muted-foreground">
                              {opt.path}
                            </span>
                          </span>
                          <span className="shrink-0 text-[10px] text-muted-foreground">
                            {opt.hint}
                          </span>
                        </button>
                      ))}
                    </div>
                  )
                })
              )}
            </div>
          )}
        </div>

        {/* Caixa manual — drag/drop + edição livre para casos avançados */}
        <input
          type="text"
          value={sourceField}
          onChange={(e) => update({ source_field: e.target.value })}
          placeholder="upstream_results.no.data (avançado)"
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleSourceDrop}
          className="h-7 w-full rounded-md border border-input bg-background/60 px-2 font-mono text-[11px] outline-none focus:ring-1 focus:ring-primary"
        />
        <p className="text-[10px] text-muted-foreground">
          Escolha no dropdown acima, arraste um campo do INPUT ou edite o
          caminho manualmente.
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
            onClick={() => setShowWorkflowPicker((v) => !v)}
            aria-haspopup="listbox"
            aria-expanded={showWorkflowPicker}
            className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 text-xs transition-colors hover:bg-muted/50"
          >
            {workflowsLoading ? (
              <span className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" /> Carregando…
              </span>
            ) : selectedWorkflow ? (
              <span className="flex items-center gap-2 truncate font-medium text-foreground">
                <WorkflowIcon className="size-3.5 shrink-0 text-violet-500" />
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

          {showWorkflowPicker && (
            <div className="absolute left-0 top-full z-30 mt-1 max-h-[260px] w-full overflow-y-auto rounded-md border border-border bg-popover shadow-lg">
              <div className="sticky top-0 border-b border-border bg-popover p-1.5">
                <div className="flex items-center gap-1.5 rounded-md border border-input bg-background px-2">
                  <Search className="size-3 text-muted-foreground" />
                  <input
                    type="text"
                    value={workflowSearch}
                    onChange={(e) => setWorkflowSearch(e.target.value)}
                    placeholder="Buscar workflow…"
                    className="h-7 flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
                    autoFocus
                  />
                </div>
              </div>
              {filteredWorkflows.length === 0 ? (
                <p className="px-3 py-3 text-[11px] text-muted-foreground">
                  Nenhum workflow publicado.
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
          <p className="text-[10px] text-destructive">{workflowsError}</p>
        )}
      </div>

      {/* ── Versão ── */}
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
            <select
              value={String(workflowVersion)}
              onChange={(e) =>
                update({
                  workflow_version:
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
          )}
        </div>
      )}

      {/* ── Mapeamento de inputs ── */}
      {workflowId && resolvedVersion != null && (
        <div className="space-y-2 rounded-md border border-border bg-muted/30 p-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-foreground">
              Mapeamento por iteração
            </span>
            <span className="text-[10px] text-muted-foreground">
              v{resolvedVersion}
            </span>
          </div>

          <div className="rounded-md border border-dashed border-border bg-background/60 p-2 text-[10px] leading-relaxed text-muted-foreground">
            Variáveis disponíveis:{" "}
            <code className="rounded bg-muted px-1 font-mono text-foreground">
              {"{{item}}"}
            </code>{" "}
            <code className="rounded bg-muted px-1 font-mono text-foreground">
              {"{{item.<campo>}}"}
            </code>{" "}
            <code className="rounded bg-muted px-1 font-mono text-foreground">
              {"{{idx}}"}
            </code>
            . Arraste um campo do INPUT: se for da origem dos itens vira{" "}
            <code className="font-mono">{"{{item.<campo>}}"}</code>, senão vira
            referência absoluta (constante por iteração).
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
                    : "{{item.campo}} ou {{upstream_results.no.campo}}"

                return (
                  <div key={param.name} className="space-y-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <label
                        htmlFor={`loop-input-${param.name}`}
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
                        <span title={param.description} className="inline-flex items-center">
                          <Info className="size-3 text-muted-foreground" />
                        </span>
                      )}
                    </div>
                    <input
                      id={`loop-input-${param.name}`}
                      type="text"
                      value={currentValue}
                      onChange={(e) => setMappingValue(param.name, e.target.value)}
                      onDragOver={(e) => handleFieldDragOver(e, param.name)}
                      onDragLeave={() => setDragOverField(null)}
                      onDrop={(e) => handleFieldDrop(e, param.name)}
                      placeholder={placeholder}
                      aria-invalid={isInvalid}
                      className={cn(
                        "h-7 w-full rounded-md border bg-background px-2 font-mono text-xs outline-none transition-colors focus:ring-1",
                        isInvalid
                          ? "border-destructive focus:ring-destructive"
                          : dragOverField === param.name
                          ? "border-primary bg-primary/5 ring-1 ring-primary"
                          : "border-input focus:ring-primary",
                      )}
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

          {requiredMissing.length > 0 && (
            <p className="flex items-start gap-1 text-[10px] text-amber-600 dark:text-amber-400">
              <AlertTriangle className="mt-0.5 size-3 shrink-0" />
              Inputs obrigatórios sem valor:{" "}
              {requiredMissing.map((p) => p.name).join(", ")}
            </p>
          )}
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
            onChange={(e) => update({ max_parallelism: Number(e.target.value) })}
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
          onChange={(e) => update({ on_item_error: e.target.value as OnItemError })}
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

      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Timeout (segundos)
        </label>
        <input
          type="number"
          value={timeoutSeconds}
          onChange={(e) =>
            update({ timeout_seconds: parseInt(e.target.value, 10) || 300 })
          }
          min={1}
          max={3600}
          className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs outline-none focus:ring-1 focus:ring-primary"
        />
        <p className="text-[10px] text-muted-foreground">
          Tempo máximo por invocação do sub-workflow. Default: 300s.
        </p>
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
