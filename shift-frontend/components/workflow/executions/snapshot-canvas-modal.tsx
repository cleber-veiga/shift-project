"use client"

/**
 * SnapshotCanvasModal — exibe a definicao do workflow no momento de uma
 * execucao em um canvas ReactFlow read-only (Sprint 4.1).
 *
 * O modal e aberto a partir do detalhe de execucao quando o usuario clica
 * em "Ver como foi executado". O snapshot vem do endpoint
 * GET /executions/{id}/definition e ja esta no formato ReactFlow
 * (nodes com position, edges com source/target).
 */

import { useEffect, useMemo, useState } from "react"
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  ReactFlowProvider,
  BackgroundVariant,
  type Node,
  type Edge,
  type NodeTypes,
  type EdgeTypes,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { AlertTriangle, GitCompareArrows, Loader2, X } from "lucide-react"

import { WorkflowNode } from "@/components/workflow/workflow-node"
import { WorkflowEdge } from "@/components/workflow/workflow-edge"
import { NODE_REGISTRY } from "@/lib/workflow/types"
import { NodeActionsContext } from "@/lib/workflow/node-actions-context"
import { NodeExecutionContext } from "@/lib/workflow/execution-context"
import { getExecutionDefinition, type ExecutionDefinitionResponse } from "@/lib/api/executions"
import { cn } from "@/lib/utils"

// ---------------------------------------------------------------------------
// Node type map (igual ao workflow-editor, mas separado para nao criar
// dependencia circular)
// ---------------------------------------------------------------------------

function buildReadOnlyNodeTypes(): NodeTypes {
  const types: NodeTypes = {}
  for (const def of NODE_REGISTRY) {
    types[def.type] = WorkflowNode
  }
  return types
}

const READ_ONLY_NODE_TYPES: NodeTypes = buildReadOnlyNodeTypes()
const READ_ONLY_EDGE_TYPES: EdgeTypes = { default: WorkflowEdge }

// ---------------------------------------------------------------------------
// Contextos com valores neutros para o canvas read-only
// (sem execucao em curso e sem acoes de edicao)
// ---------------------------------------------------------------------------

const EMPTY_EXEC_CTX: Record<string, never> = {}
const NOOP_ACTIONS = { onExecuteNode: () => {} }

// ---------------------------------------------------------------------------
// Inner canvas (precisa estar dentro de ReactFlowProvider)
// ---------------------------------------------------------------------------

interface CanvasInnerProps {
  nodes: Node[]
  edges: Edge[]
}

function CanvasInner({ nodes, edges }: CanvasInnerProps) {
  return (
    <NodeExecutionContext.Provider value={EMPTY_EXEC_CTX}>
      <NodeActionsContext.Provider value={NOOP_ACTIONS}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={READ_ONLY_NODE_TYPES}
          edgeTypes={READ_ONLY_EDGE_TYPES}
          // Read-only: sem arrastar nos nem criar/editar arestas
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          edgesFocusable={false}
          panOnDrag
          zoomOnScroll
          fitView
          fitViewOptions={{ padding: 0.15 }}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
          <Controls showInteractive={false} />
          <MiniMap nodeStrokeWidth={3} zoomable pannable />
        </ReactFlow>
      </NodeActionsContext.Provider>
    </NodeExecutionContext.Provider>
  )
}

// ---------------------------------------------------------------------------
// Modal wrapper
// ---------------------------------------------------------------------------

interface SnapshotCanvasModalProps {
  executionId: string
  onClose: () => void
}

export function SnapshotCanvasModal({ executionId, onClose }: SnapshotCanvasModalProps) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<ExecutionDefinitionResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getExecutionDefinition(executionId)
      .then((d) => { if (!cancelled) setData(d) })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Erro ao carregar snapshot.")
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [executionId])

  // Parse snapshot definition into ReactFlow nodes + edges
  const { rfNodes, rfEdges } = useMemo(() => {
    if (!data?.snapshot) return { rfNodes: [], rfEdges: [] }
    const snap = data.snapshot as { nodes?: unknown[]; edges?: unknown[] }
    const rfNodes = (snap.nodes ?? []) as Node[]
    const rfEdges = (snap.edges ?? []) as Edge[]
    return { rfNodes, rfEdges }
  }, [data])

  return (
    // Overlay
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      {/* Panel */}
      <div className="relative flex h-[90vh] w-[95vw] max-w-7xl flex-col overflow-hidden rounded-xl border border-border bg-background shadow-2xl">
        {/* Header */}
        <div className="flex shrink-0 items-center gap-3 border-b border-border bg-muted/30 px-4 py-3">
          <GitCompareArrows className="size-4 text-muted-foreground" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-foreground">
              Workflow como foi executado
            </p>
            <p className="truncate text-[11px] text-muted-foreground font-mono">
              execução {executionId.slice(0, 8)}…
            </p>
          </div>

          {/* Divergence badge */}
          {data?.definition_diverged && (
            <div className="flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-[11px] font-medium text-amber-600">
              <AlertTriangle className="size-3.5" />
              Definição alterada desde esta execução
            </div>
          )}

          <button
            type="button"
            onClick={onClose}
            className="ml-2 flex size-7 items-center justify-center rounded-md border border-border bg-card hover:bg-muted text-muted-foreground"
            aria-label="Fechar"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0">
          {loading && (
            <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Carregando snapshot…
            </div>
          )}

          {!loading && error && (
            <div className="flex h-full items-center justify-center p-8 text-center">
              <div className="space-y-1">
                <p className="text-sm font-medium text-red-500">{error}</p>
                <p className="text-[11px] text-muted-foreground">
                  Não foi possível carregar a definição do snapshot.
                </p>
              </div>
            </div>
          )}

          {!loading && !error && !data?.snapshot && (
            <div className="flex h-full items-center justify-center p-8 text-center">
              <div className="space-y-1">
                <p className="text-sm font-medium text-muted-foreground">
                  Snapshot não disponível
                </p>
                <p className="text-[11px] text-muted-foreground">
                  Esta execução foi iniciada antes de a funcionalidade de snapshot ser ativada.
                </p>
              </div>
            </div>
          )}

          {!loading && !error && data?.snapshot && (
            <ReactFlowProvider>
              <CanvasInner nodes={rfNodes} edges={rfEdges} />
            </ReactFlowProvider>
          )}
        </div>

        {/* Footer info */}
        {data && (
          <div className="shrink-0 flex items-center gap-4 border-t border-border bg-muted/20 px-4 py-2 text-[11px] text-muted-foreground">
            <span>
              Hash do snapshot:{" "}
              <code className="font-mono">{data.snapshot_hash?.slice(0, 12) ?? "—"}</code>
            </span>
            <span className="opacity-50">•</span>
            <span>
              Hash atual:{" "}
              <code className={cn("font-mono", data.definition_diverged && "text-amber-600")}>
                {data.current_hash?.slice(0, 12) ?? "—"}
              </code>
            </span>
            {data.definition_diverged && (
              <>
                <span className="opacity-50">•</span>
                <span className="text-amber-600 font-medium">
                  A definição atual é diferente da que foi executada.
                </span>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
