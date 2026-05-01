"use client"

import { X } from "lucide-react"
import { type Node } from "@xyflow/react"
import { getNodeDefinition } from "@/lib/workflow/types"
import { getNodeIcon } from "@/lib/workflow/node-icons"
import { cn } from "@/lib/utils"
import { SqlDatabaseConfig, CacheSection } from "@/components/workflow/nodes/sql-database-config"
import { MapperConfig } from "@/components/workflow/nodes/mapper-config"
import { FilterConfig } from "@/components/workflow/nodes/filter-config"
import { DeduplicationConfig } from "@/components/workflow/nodes/deduplication-config"
import { IfConfig } from "@/components/workflow/nodes/if-config"
import { SwitchConfig } from "@/components/workflow/nodes/switch-config"
import { TruncateTableConfig } from "@/components/workflow/nodes/truncate-table-config"
import { BulkInsertConfig } from "@/components/workflow/nodes/bulk-insert-config"
import { CompositeInsertConfig } from "@/components/workflow/nodes/composite-insert-config"
import { SqlScriptConfig } from "@/components/workflow/nodes/sql-script-config"
import { LoopConfig } from "@/components/workflow/nodes/loop-config"
import { SortConfig } from "@/components/workflow/nodes/sort-config"
import { SampleConfig } from "@/components/workflow/nodes/sample-config"
import { RecordIdConfig } from "@/components/workflow/nodes/record-id-config"
import { UnionConfig } from "@/components/workflow/nodes/union-config"
import { JoinConfig } from "@/components/workflow/nodes/join-config"
import { PivotConfig } from "@/components/workflow/nodes/pivot-config"
import { AggregatorConfig } from "@/components/workflow/nodes/aggregator-config"
import { MathConfig } from "@/components/workflow/nodes/math-config"
import { UnpivotConfig } from "@/components/workflow/nodes/unpivot-config"
import { TextToRowsConfig } from "@/components/workflow/nodes/text-to-rows-config"
import { CronConfig } from "@/components/workflow/nodes/cron-config"
import { ManualConfig } from "@/components/workflow/nodes/manual-config"
import { WebhookConfig } from "@/components/workflow/nodes/webhook-config"
import { WorkflowInputConfig } from "@/components/workflow/nodes/workflow-input-config"
import { WorkflowOutputConfig } from "@/components/workflow/nodes/workflow-output-config"
import { CallWorkflowConfig } from "@/components/workflow/nodes/call-workflow-config"
import { LoadNodeConfig } from "@/components/workflow/nodes/load-node-config"
import { HttpRequestConfig } from "@/components/workflow/nodes/http-request-config"
import {
  RetryPolicyEditor,
  type RetryPolicyValue,
} from "@/components/workflow/retry-policy-editor"
import type { WebhookCapture } from "@/lib/api/webhooks"
import type { WorkflowIOSchema } from "@/lib/api/workflow-versions"
import { migrateLegacySqlParameter } from "@/lib/workflow/parameter-value"
import { ValueInput } from "@/components/workflow/value-input/ValueInput"
import { FilePickerInput } from "@/components/workflow/file-picker-input"
import { InputModelPicker } from "@/components/workflow/input-model-picker"
import { ExcelNodeConfig } from "@/components/workflow/excel-node-config"
import { HelpTip } from "@/components/ui/help-tip"

interface NodeConfigPanelProps {
  node: Node
  workflowId: string
  onClose: () => void
  onUpdate: (nodeId: string, data: Record<string, unknown>) => void
  onWebhookTestEvent?: (capture: WebhookCapture) => void
  ioSchema?: WorkflowIOSchema
}

const categoryBgMap: Record<string, string> = {
  amber: "bg-amber-500/10",
  blue: "bg-blue-500/10",
  violet: "bg-violet-500/10",
  emerald: "bg-emerald-500/10",
  orange: "bg-orange-500/10",
  pink: "bg-pink-500/10",
  slate: "bg-slate-500/10",
  indigo: "bg-indigo-500/10",
  red: "bg-red-500/10",
}

const categoryTextMap: Record<string, string> = {
  amber: "text-amber-500",
  blue: "text-blue-500",
  violet: "text-violet-500",
  emerald: "text-emerald-500",
  orange: "text-orange-500",
  pink: "text-pink-500",
  slate: "text-slate-500",
  indigo: "text-indigo-500",
  red: "text-red-500",
}

function ConfigField({
  label,
  help,
  helpArticle,
  children,
}: {
  label: string
  /** Conteudo opcional do HelpTip (ícone ? ao lado do label). */
  help?: React.ReactNode
  /** Slug opcional pra link "Saiba mais" → /ajuda/<slug>. */
  helpArticle?: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <label className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
        {help && <HelpTip article={helpArticle}>{help}</HelpTip>}
      </label>
      {children}
    </div>
  )
}

function TextInput({
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
    />
  )
}

function TextArea({
  value,
  onChange,
  placeholder,
  rows = 4,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  rows?: number
}) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      rows={rows}
      className="w-full rounded-md border border-input bg-background px-2.5 py-2 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
    />
  )
}

function SelectInput({
  value,
  onChange,
  options,
}: {
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  )
}

function CheckboxInput({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
}) {
  return (
    <label className="flex items-center gap-2">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="size-3.5 rounded border-input accent-primary"
      />
      <span className="text-xs text-foreground">{label}</span>
    </label>
  )
}

/** Render config fields based on the node type */
export function NodeConfigFields({
  node,
  workflowId,
  onUpdate,
  onWebhookTestEvent,
  ioSchema,
}: {
  node: Node
  workflowId?: string
  onUpdate: (nodeId: string, data: Record<string, unknown>) => void
  onWebhookTestEvent?: (capture: WebhookCapture) => void
  ioSchema?: WorkflowIOSchema
}) {
  const data = node.data as Record<string, unknown>
  const nodeType = (data.type as string) ?? node.type
  const definition = getNodeDefinition(nodeType)
  const supportsRetry = definition ? definition.category !== "trigger" : false

  function update(field: string, value: unknown) {
    onUpdate(node.id, { ...data, [field]: value })
  }

  const retryPolicy = (data.retry_policy as RetryPolicyValue | null | undefined) ?? null
  const retrySection = supportsRetry ? (
    <RetryPolicyEditor
      value={retryPolicy}
      onChange={(policy) => onUpdate(node.id, { ...data, retry_policy: policy })}
    />
  ) : null

  const checkpointEnabled = !!data.checkpoint_enabled
  const checkpointSection = supportsRetry ? (
    <CheckpointToggle
      enabled={checkpointEnabled}
      onChange={(next) =>
        onUpdate(node.id, { ...data, checkpoint_enabled: next })
      }
    />
  ) : null

  const specific = renderNodeSpecificFields({
    nodeType,
    node,
    data,
    workflowId,
    onUpdate,
    onWebhookTestEvent,
    update,
    ioSchema,
  })

  return (
    <div className="space-y-4">
      {specific}
      {retrySection}
      {checkpointSection}
    </div>
  )
}

function CheckpointToggle({
  enabled,
  onChange,
}: {
  enabled: boolean
  onChange: (next: boolean) => void
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-foreground">Checkpoint</p>
          <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
            Persiste a sa&iacute;da deste n&oacute; ao concluir. Em caso de falha,
            &quot;Retomar&quot; pula este n&oacute; e reaproveita o resultado salvo.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          onClick={() => onChange(!enabled)}
          className={
            enabled
              ? "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full bg-emerald-500 transition-colors"
              : "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full bg-muted transition-colors"
          }
        >
          <span
            className={
              enabled
                ? "inline-block size-4 translate-x-[18px] transform rounded-full bg-white shadow transition-transform"
                : "inline-block size-4 translate-x-0.5 transform rounded-full bg-white shadow transition-transform"
            }
          />
        </button>
      </div>
    </div>
  )
}

function renderNodeSpecificFields({
  nodeType,
  node,
  data,
  workflowId,
  onUpdate,
  onWebhookTestEvent,
  update,
  ioSchema,
}: {
  nodeType: string
  node: Node
  data: Record<string, unknown>
  workflowId?: string
  onUpdate: (nodeId: string, data: Record<string, unknown>) => void
  onWebhookTestEvent?: (capture: WebhookCapture) => void
  update: (field: string, value: unknown) => void
  ioSchema?: WorkflowIOSchema
}) {
  switch (nodeType) {
    case "manual":
      return (
        <ManualConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "cron":
      return (
        <CronConfig
          data={data}
          onUpdate={(patch) => onUpdate(node.id, { ...data, ...patch })}
        />
      )

    case "webhook":
      return (
        <WebhookConfig
          workflowId={workflowId ?? ""}
          nodeId={node.id}
          data={data}
          onUpdate={(patch) => onUpdate(node.id, { ...data, ...patch })}
          onTestEvent={onWebhookTestEvent}
        />
      )

    case "sql_database":
      return (
        <SqlDatabaseConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "csv_input":
      return (
        <div className="space-y-4">

          <ConfigField
            label="Arquivo CSV"
            help="4 modos: URL/Path direto, Do projeto (uploads salvos), Enviar (upload novo) ou Variável (arquivo solicitado em runtime — ideal pra CSVs que mudam a cada execução)."
            helpArticle="variaveis-arquivos"
          >
            <FilePickerInput
              value={(data.url as string) ?? ""}
              onChange={(next) => update("url", next)}
              workflowId={workflowId}
              accept=".csv,.tsv,.txt"
              placeholder="https://... ou /path/to/file.csv"
            />
          </ConfigField>
          <ConfigField
            label="Modelo de entrada (opcional)"
            help="Define o cabeçalho esperado do CSV. Vinculado, valida o arquivo na execução e falha cedo com mensagem clara se faltar coluna obrigatória."
            helpArticle="modelos-entrada"
          >
            <InputModelPicker
              workflowId={workflowId}
              value={(data.input_model_id as string | null | undefined) ?? null}
              onChange={(next) => update("input_model_id", next)}
              fileType="csv"
            />
          </ConfigField>
          <ConfigField label="Delimitador">
            <TextInput
              value={(data.delimiter as string) ?? ","}
              onChange={(v) => update("delimiter", v)}
            />
          </ConfigField>
          <CheckboxInput
            checked={(data.has_header as boolean) ?? true}
            onChange={(v) => update("has_header", v)}
            label="Possui cabeçalho"
          />
          <ConfigField label="Encoding">
            <TextInput
              value={(data.encoding as string) ?? "utf-8"}
              onChange={(v) => update("encoding", v)}
            />
          </ConfigField>
          <CacheSection
            nodeType="csv_input"
            data={data}
            onUpdate={(newData) => onUpdate(node.id, newData)}
          />
        </div>
      )

    case "excel_input":
      return (
        <div className="space-y-4">

          <ExcelNodeConfig
            workflowId={workflowId ?? ""}
            data={data}
            update={update}
          />
          <CacheSection
            nodeType="excel_input"
            data={data}
            onUpdate={(newData) => onUpdate(node.id, newData)}
          />
        </div>
      )

    case "http_request":
      return (
        <HttpRequestConfig
          data={data}
          onUpdate={(patch) => onUpdate(node.id, { ...data, ...patch })}
        />
      )

    case "inline_data":
      return (
        <div className="space-y-4">

          <ConfigField label="Dados (JSON)">
            <TextArea
              value={typeof data.data === "string" ? (data.data as string) : JSON.stringify(data.data ?? [], null, 2)}
              onChange={(v) => {
                try {
                  update("data", JSON.parse(v))
                } catch {
                  update("data", v)
                }
              }}
              placeholder='[{"id": 1, "name": "..."}]'
              rows={6}
            />
          </ConfigField>
        </div>
      )

    case "mapper":
      return (
        <MapperConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
          workflowId={workflowId}
          nodeId={node.id}
        />
      )

    case "filter":
      return (
        <FilterConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
          workflowId={workflowId}
          nodeId={node.id}
        />
      )

    case "deduplication":
      return (
        <DeduplicationConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "if_node":
      return (
        <IfConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "switch_node":
      return (
        <SwitchConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "aggregator":
      return (
        <AggregatorConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "math":
      return (
        <MathConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "code":
      return (
        <div className="space-y-4">

          <ConfigField label="Código Python">
            <TextArea
              value={(data.code as string) ?? ""}
              onChange={(v) => update("code", v)}
              placeholder="# Escreva seu código aqui..."
              rows={8}
            />
          </ConfigField>
          <ConfigField label="Variável de resultado">
            <TextInput
              value={(data.result_variable as string) ?? "result"}
              onChange={(v) => update("result_variable", v)}
            />
          </ConfigField>
        </div>
      )

    case "truncate_table":
      return (
        <TruncateTableConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "bulk_insert":
      return (
        <BulkInsertConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "composite_insert":
      return (
        <CompositeInsertConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "sql_script":
      return (
        <SqlScriptConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "sync":
      return (
        <div className="space-y-4">
          <div className="rounded-lg border border-dashed border-violet-500/30 bg-violet-500/5 p-3">
            <p className="text-xs font-medium text-violet-600 dark:text-violet-400">Sincronização de Ramos</p>
            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
              Este nó aguarda a conclusão de <strong>todos os ramos paralelos</strong> antes de prosseguir. Conecte as saídas dos nós paralelos aqui para sincronizá-los em um único ponto.
            </p>
          </div>
          <ConfigField label="Campo de saída">
            <TextInput
              value={(data.output_field as string) ?? "data"}
              onChange={(v) => update("output_field", v)}
              placeholder="data"
            />
          </ConfigField>
        </div>
      )

    case "loop":
      return (
        <LoopConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "workflow_input":
      return (
        <WorkflowInputConfig
          data={data}
          onUpdate={(patch) => onUpdate(node.id, patch)}
          ioSchema={ioSchema}
        />
      )

    case "workflow_output":
      return (
        <WorkflowOutputConfig
          data={data}
          onUpdate={(patch) => onUpdate(node.id, patch)}
        />
      )

    case "call_workflow":
      return (
        <CallWorkflowConfig
          data={data}
          onUpdate={(patch) => onUpdate(node.id, patch)}
          currentWorkflowId={workflowId}
        />
      )

    case "loadNode":
      return (
        <LoadNodeConfig
          data={data}
          onUpdate={(patch) => onUpdate(node.id, patch)}
        />
      )

    case "aiNode":
      return (
        <div className="space-y-4">

          <ConfigField label="Modelo">
            <TextInput
              value={(data.model_name as string) ?? "gpt-4"}
              onChange={(v) => update("model_name", v)}
              placeholder="gpt-4"
            />
          </ConfigField>
          <ConfigField label="Temperature">
            <TextInput
              type="number"
              value={String((data.temperature as number) ?? 0.7)}
              onChange={(v) => update("temperature", Number(v))}
            />
          </ConfigField>
          <ConfigField label="Prompt Template">
            <TextArea
              value={(data.prompt_template as string) ?? ""}
              onChange={(v) => update("prompt_template", v)}
              placeholder="Analise os seguintes dados: {{data}}"
              rows={6}
            />
          </ConfigField>
        </div>
      )

    case "sort":
      return (
        <SortConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "sample":
      return (
        <SampleConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "record_id":
      return (
        <RecordIdConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "union":
      return (
        <UnionConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "join":
      return (
        <JoinConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "pivot":
      return (
        <PivotConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "unpivot":
      return (
        <UnpivotConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    case "text_to_rows":
      return (
        <TextToRowsConfig
          data={data}
          onUpdate={(newData) => onUpdate(node.id, newData)}
        />
      )

    default:
      return (
        <div className="space-y-4">

          <p className="text-xs text-muted-foreground">
            Configuração avançada não disponível para este tipo de nó.
          </p>
          <ConfigField label="Dados (JSON)">
            <TextArea
              value={JSON.stringify(data, null, 2)}
              onChange={(v) => {
                try {
                  onUpdate(node.id, JSON.parse(v))
                } catch {
                  /* keep raw */
                }
              }}
              rows={8}
            />
          </ConfigField>
        </div>
      )
  }
}

export function NodeConfigPanel({
  node,
  workflowId,
  onClose,
  onUpdate,
  onWebhookTestEvent,
  ioSchema,
}: NodeConfigPanelProps) {
  const definition = getNodeDefinition(node.type ?? "")
  const Icon = getNodeIcon(definition?.icon ?? "Database")
  const color = definition?.color ?? "blue"

  return (
    <div className="flex h-full w-72 flex-col border-l border-border bg-card">
      {/* Header */}
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-border px-3">
        <div className="flex items-center gap-2">
          <div className={cn("flex size-6 items-center justify-center rounded", categoryBgMap[color])}>
            <Icon className={cn("size-3.5", categoryTextMap[color])} />
          </div>
          <span className="text-xs font-semibold text-foreground">{definition?.label ?? node.type}</span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <X className="size-3.5" />
        </button>
      </div>

      {/* Config form */}
      <div className="flex-1 overflow-y-auto px-3 py-4">
        <NodeConfigFields
          node={node}
          workflowId={workflowId}
          onUpdate={onUpdate}
          onWebhookTestEvent={onWebhookTestEvent}
          ioSchema={ioSchema}
        />
      </div>

      {/* Footer */}
      <div className="shrink-0 border-t border-border px-3 py-2">
        <p className="text-[10px] text-muted-foreground">ID: {node.id}</p>
      </div>
    </div>
  )
}
