"use client"

import dynamic from "next/dynamic"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  ReactFlow,
  Background,
  addEdge,
  useNodesState,
  useEdgesState,
  useReactFlow,
  type Connection,
  type Node,
  type Edge,
  type NodeChange,
  type EdgeChange,
  type NodeTypes,
  type EdgeTypes,
  ReactFlowProvider,
  type ReactFlowInstance,
  BackgroundVariant,
  SelectionMode,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"

import { WorkflowNode } from "@/components/workflow/workflow-node"
import { WorkflowEdge } from "@/components/workflow/workflow-edge"
import { HelperLines } from "@/components/workflow/helper-lines"
import { getHelperLines, type GuideLine } from "@/lib/workflow/helper-lines"
import { WorkflowToolbar } from "@/components/workflow/workflow-toolbar"
import type { UpstreamOutput } from "@/components/workflow/node-config-modal"
import { isIoSchemaValid } from "@/lib/workflow/io-schema-utils"

// Placeholder para paineis — evita flash vazio enquanto o chunk carrega.
const DynamicPanelFallback = () => (
  <div className="flex h-full w-full items-center justify-center p-4">
    <div className="h-2 w-24 animate-pulse rounded bg-muted" />
  </div>
)

const NodeLibrary = dynamic(() => import("@/components/workflow/node-library").then((m) => m.NodeLibrary), { ssr: false, loading: DynamicPanelFallback })
// Modais (loading: null) — soh aparecem apos clique explicito do usuario.
const NodeConfigModal = dynamic(() => import("@/components/workflow/node-config-modal").then((m) => m.NodeConfigModal), { ssr: false, loading: () => null })
const ExecutionPanel = dynamic(() => import("@/components/workflow/execution-panel").then((m) => m.ExecutionPanel), { ssr: false, loading: DynamicPanelFallback })
const ExecutionsTab = dynamic(() => import("@/components/workflow/executions/executions-tab").then((m) => m.ExecutionsTab), { ssr: false, loading: DynamicPanelFallback })
const IoSchemaEditor = dynamic(() => import("@/components/workflow/io-schema-editor").then((m) => m.IoSchemaEditor), { ssr: false, loading: DynamicPanelFallback })
const PublishVersionModal = dynamic(() => import("@/components/workflow/publish-version-modal").then((m) => m.PublishVersionModal), { ssr: false, loading: () => null })
const VariablesPanel = dynamic(() => import("@/components/workflow/variables-panel").then((m) => m.VariablesPanel), { ssr: false, loading: DynamicPanelFallback })
const ExecuteWorkflowDialog = dynamic(() => import("@/components/workflow/execute-workflow-dialog").then((m) => m.ExecuteWorkflowDialog), { ssr: false, loading: () => null })
import type { WorkflowIOSchema } from "@/lib/api/workflow-versions"
import { useWorkflowVariables } from "@/lib/workflow/use-workflow-variables"
import {
  executeWorkflowWithVars,
  getVariablesSchema,
  type InheritedVariable,
} from "@/lib/api/workflow-variables"
import { getNodeDefinition, NODE_REGISTRY, type WorkflowVariable } from "@/lib/workflow/types"
import {
  collapseInlineLoopBodies,
  expandInlineLoopBodies,
} from "@/lib/workflow/loop-inline-bodies"
import { NodeExecutionContext, type NodeExecState } from "@/lib/workflow/execution-context"
import { NodeActionsContext } from "@/lib/workflow/node-actions-context"
import { WorkflowVariablesContext } from "@/lib/workflow/workflow-variables-context"
import { Copy, Hand, LayoutGrid, Maximize2, MousePointer2, Power, PowerOff, Trash2, X, ZoomIn, ZoomOut } from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import { cn } from "@/lib/utils"
import {
  getWorkflow,
  getWorkflowSchedule,
  updateWorkflow,
  testWorkflowStream,
  listWorkspaceCustomNodeDefinitions,
  exportWorkflow,
  importWorkflowYaml,
  WorkflowExportError,
  type CustomNodeDefinition,
  type UnsupportedNodeReport,
  type Workflow,
  type WorkflowExportFormat,
  type WorkflowScheduleStatus,
  type WorkflowTestEvent,
} from "@/lib/auth"
import { useDashboard } from "@/lib/context/dashboard-context"
import { useRegisterAIContext } from "@/lib/context/ai-context"
import { CustomNodesContext, findCustomNode } from "@/lib/workflow/custom-nodes-context"
import {
  useWorkflowDefinitionStream,
  type BuildModeHandlers,
} from "@/lib/hooks/use-workflow-definition-stream"
import { useBuildMode } from "@/lib/workflow/build-mode-context"
import { useToast } from "@/lib/context/toast-context"
// BuildModeBar foi removida — a confirmacao/cancelamento do build agora acontece
// no chat via AIBuildConfirmationCard, evitando duplicar o controle no topo do
// canvas. Se futuramente precisarmos de fallback para quando o chat esta fechado,
// podemos reintroduzir condicionalmente aqui.
const BuildOpsPanel = dynamic(() => import("@/components/workflow/build-ops-panel").then((m) => m.BuildOpsPanel), { ssr: false, loading: () => null })

/**
 * Reidrata o ``pinnedOutput`` salvo em ``node.data`` para um ``NodeExecState``.
 *
 * Três formatos suportados:
 *  - **v3** (atual): rows materializadas pelo backend — persiste offline.
 *    ``{__pinned_v: 3, rows, columns, row_count, total_rows, truncated,
 *    schema_fingerprint, pinned_at}``
 *  - **v2**: wrapper lean com referência DuckDB (ephemeral).
 *    ``{__pinned_v: 2, output, output_reference, row_count, execution_id}``
 *  - **legado (v1)**: o próprio output dict puro (pré-Fase 5).
 *
 * Centralizado aqui pra que os 3 sites de restore (workflow load, execute,
 * onUpdate via modal) tratem todos os formatos identicamente.
 */
function pinnedOutputToState(pinned: Record<string, unknown>): NodeExecState {
  if (pinned.__pinned_v === 3) {
    return {
      status: "success",
      // Reconstrói o output inline para o DataViewer detectar como "inline"
      output: {
        columns: pinned.columns as string[],
        rows: pinned.rows as Array<Record<string, unknown>>,
        row_count: pinned.row_count as number,
      },
      row_count: pinned.row_count as number,
      is_pinned: true,
      pin_truncated: (pinned.truncated as boolean) ?? false,
      pin_total_rows: (pinned.total_rows as number) ?? (pinned.row_count as number),
    }
  }
  if (pinned.__pinned_v === 2) {
    return {
      status: "success",
      output: (pinned.output as Record<string, unknown> | null) ?? undefined,
      output_reference: (pinned.output_reference as
        | { node_id: string; storage_type: string }
        | null) ?? null,
      row_count: (pinned.row_count as number | null) ?? null,
      execution_id: (pinned.execution_id as string | null) ?? undefined,
      is_pinned: true,
    }
  }
  return { status: "success", output: pinned, is_pinned: true }
}

/** Build nodeTypes map — all custom node types share one component */
function buildNodeTypes(): NodeTypes {
  const types: NodeTypes = {}
  for (const def of NODE_REGISTRY) {
    types[def.type] = WorkflowNode
  }
  return types
}

const EDGE_TYPES: EdgeTypes = { default: WorkflowEdge }

let nodeIdCounter = 0
function generateNodeId() {
  nodeIdCounter += 1
  return `node_${Date.now()}_${nodeIdCounter}`
}

interface WorkflowEditorProps {
  workflowId: string
  initialName?: string
  initialDescription?: string
  initialNodes?: Node[]
  initialEdges?: Edge[]
}

function WorkflowEditorInner({
  workflowId,
  initialName = "",
  initialDescription = "",
  initialNodes = [],
  initialEdges = [],
}: WorkflowEditorProps) {
  const nodeTypes = useMemo(() => buildNodeTypes(), [])
  const reactFlowWrapper = useRef<HTMLDivElement>(null)
  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance | null>(null)

  const { selectedWorkspace } = useDashboard()

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)

  const [name, setName] = useState(initialName || "Novo Fluxo")
  const [description, setDescription] = useState(initialDescription)
  const [tags, setTags] = useState<string[]>([])
  const [status, setStatus] = useState<"draft" | "published">("draft")
  const [workflowUpdatedAt, setWorkflowUpdatedAt] = useState<string | null>(null)
  const [isTemplate, setIsTemplate] = useState(false)
  const [isPublished, setIsPublished] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [isExecuting, setIsExecuting] = useState(false)
  const [isOpeningDialog, setIsOpeningDialog] = useState(false)
  const [isLoading, setIsLoading] = useState(workflowId !== "new")

  // Workflow workspace_id (needed for test endpoint auth scope)
  const [workflowWorkspaceId, setWorkflowWorkspaceId] = useState<string | undefined>(
    selectedWorkspace?.id,
  )

  // Modal aberto quando export retorna 422 com lista de nos nao suportados.
  const [unsupportedReport, setUnsupportedReport] = useState<{
    format: WorkflowExportFormat
    items: UnsupportedNodeReport[]
  } | null>(null)

  // Custom (composite_insert) node definitions available in this workspace
  const [customNodes, setCustomNodes] = useState<CustomNodeDefinition[]>([])

  const [showLibrary, setShowLibrary] = useState(false)
  const [selectedNode, setSelectedNode] = useState<Node | null>(null)
  const [canvasMode, setCanvasMode] = useState<"pan" | "select">("pan")

  // Aba ativa: "editor" (canvas) ou "executions" (historico de runs).
  const [activeTab, setActiveTab] = useState<"editor" | "executions">("editor")

  // Workflow metadata (player_id, workflow_type, …)
  const [workflowMeta, setWorkflowMeta] = useState<Record<string, unknown>>({})

  // ── I/O schema (inputs/outputs expostos quando chamado como sub-workflow) ──
  const [ioSchema, setIoSchema] = useState<WorkflowIOSchema>({
    inputs: [],
    outputs: [],
  })
  const [showIoSchemaEditor, setShowIoSchemaEditor] = useState(false)
  const [showPublishModal, setShowPublishModal] = useState(false)
  const [showVariablesPanel, setShowVariablesPanel] = useState(false)
  const [executeDialogMode, setExecuteDialogMode] = useState<
    | { kind: "execute" }
    | { kind: "preview" }
    | { kind: "test"; targetNodeId?: string }
    | null
  >(null)
  const [dirty, setDirty] = useState(false)

  // ── Workflow variables ───────────────────────────────────────────────────
  const {
    variables,
    setVariables,
    isSaving: isVariablesSaving,
    error: variablesError,
    save: saveVariables,
  } = useWorkflowVariables(workflowId)

  // ── Schedule state (cron agendado no APScheduler) ────────────────────────
  const [scheduleStatus, setScheduleStatus] = useState<WorkflowScheduleStatus | null>(null)

  // ── Variaveis herdadas de sub-workflows (call_workflow) — fetch sob demanda ──
  // O backend calcula olhando os nos ``call_workflow`` na definition persistida,
  // entao so faz sentido buscar apos salvar. Usado como visualizacao read-only
  // no VariablesPanel e para inflar o formulario no ExecuteWorkflowDialog.
  const [inheritedVariables, setInheritedVariables] = useState<InheritedVariable[]>([])
  const refreshInheritedVariables = useCallback(async () => {
    if (workflowId === "new") return
    try {
      const schema = await getVariablesSchema(workflowId)
      setInheritedVariables(schema.inherited_variables ?? [])
    } catch {
      // Silencioso — a lista vira vazia e o painel esconde a secao.
    }
  }, [workflowId])

  // ── Build mode (ghost nodes from Platform Agent FASE 3) ─────────────────
  const {
    buildState,
    sessionId: buildSessionId,
    pendingNodes,
    pendingEdges,
    enterBuildMode,
    setAwaiting: setBuildAwaiting,
    exitBuildMode,
    addPendingNode,
    addPendingEdge,
    updatePendingNode: updatePendingNodeInCtx,
    removePendingNode,
    removePendingEdge,
    flushPendingToReal,
    // confirmBuild nao e mais chamado aqui — o AIBuildConfirmationCard
    // consome o mesmo contexto e dispara a confirmacao direto no chat.
    cancelBuild,
    canUndo,
  } = useBuildMode()

  const pendingNodesRef = useRef<typeof pendingNodes>(pendingNodes)
  const pendingEdgesRef = useRef<typeof pendingEdges>(pendingEdges)
  pendingNodesRef.current = pendingNodes
  pendingEdgesRef.current = pendingEdges

  const isInBuildMode = buildState !== "idle"
  const toast = useToast()

  const buildModeStreamHandlers = useMemo<BuildModeHandlers>(
    () => ({
      onBuildStarted: (sessionId) => enterBuildMode(sessionId),
      onPendingNodeAdded: (node) => addPendingNode(node),
      onPendingEdgeAdded: (edge) => addPendingEdge(edge),
      onPendingNodeUpdated: (nodeId, patch) => updatePendingNodeInCtx(nodeId, patch),
      onPendingNodeRemoved: (nodeId) => removePendingNode(nodeId),
      onPendingEdgeRemoved: (edgeId) => removePendingEdge(edgeId),
      onBuildReady: () => setBuildAwaiting(),
      onBuildConfirmed: (_ghosts, _ghostEdges) => {
        // Promote ghosts → real usando o contexto, que acessa o valor mais
        // recente de pendingNodes/pendingEdges via setState updater — evita a
        // race condition dos refs (pendingNodesRef pode estar stale quando
        // build_confirmed chega no mesmo microtask batch de pending_node_added).
        // Os argumentos posicionais sao ignorados intencionalmente.
        const { nodeCount, edgeCount } = flushPendingToReal(setNodes, setEdges)
        exitBuildMode(true)
        const title = `${nodeCount} no${nodeCount !== 1 ? "s" : ""} adicionado${nodeCount !== 1 ? "s" : ""}`
        const description = `${edgeCount > 0 ? `${edgeCount} conexao${edgeCount !== 1 ? "es" : ""} criada${edgeCount !== 1 ? "s" : ""}. ` : ""}Use o painel lateral para desfazer.`
        toast.success(title, description)
      },
      onBuildCancelled: () => exitBuildMode(false),
      onSseDropDetected: () => {
        // SSE silent for 15s during build - auto-cancel to avoid stuck state
        void cancelBuild(workflowId)
      },
    }),
    [
      addPendingEdge,
      addPendingNode,
      toast,
      cancelBuild,
      enterBuildMode,
      exitBuildMode,
      flushPendingToReal,
      removePendingEdge,
      removePendingNode,
      setBuildAwaiting,
      setEdges,
      setNodes,
      updatePendingNodeInCtx,
      workflowId,
    ],
  )

  // ── Definition stream (SSE from Platform Agent write tools) ─────────────
  const localMutationIds = useRef<Set<string>>(new Set())
  const { status: streamStatus, registerLocalMutation } = useWorkflowDefinitionStream({
    workflowId,
    enabled: workflowId !== "new" && !isLoading,
    setNodes,
    setEdges,
    setVariables,
    localMutationIds,
    pendingNodesRef,
    pendingEdgesRef,
    // Drop detector deve rodar SO durante construcao ativa. Em
    // awaiting_confirmation o stream fica naturalmente silencioso porque
    // estamos esperando o usuario decidir — nao podemos auto-cancelar nesse
    // estado (bug: "a barra aparecia por um momento e sumia").
    buildModeActive: buildState === "building",
    buildModeHandlers: buildModeStreamHandlers,
  })

  const refreshScheduleStatus = useCallback(async () => {
    if (workflowId === "new") return
    try {
      const data = await getWorkflowSchedule(workflowId)
      setScheduleStatus(data)
    } catch {
      // Silencioso: status do schedule e opcional na UI
    }
  }, [workflowId])

  // ── Execution state ──────────────────────────────────────────────────────
  const [nodeExecStates, setNodeExecStates] = useState<Record<string, NodeExecState>>({})
  const [execEvents, setExecEvents] = useState<WorkflowTestEvent[]>([])
  const [showExecPanel, setShowExecPanel] = useState(false)
  // Fases visíveis no painel antes/durante o SSE — sem isso o painel fica
  // vazio (sensação de travado) enquanto o save HTTP roda.
  const [executionPhase, setExecutionPhase] = useState<
    "idle" | "saving" | "connecting" | "streaming"
  >("idle")
  const abortControllerRef = useRef<AbortController | null>(null)
  const executionIdRef = useRef<string | null>(null)

  const aiContext = useMemo(() => {
    if (isLoading || workflowId === "new") return null
    return {
      section: "workflow_editor" as const,
      workspaceId: selectedWorkspace?.id ?? null,
      workspaceName: selectedWorkspace?.name ?? null,
      projectId: null,
      projectName: null,
      userRole: {
        workspace: (selectedWorkspace?.my_role ?? null) as "VIEWER" | "CONSULTANT" | "MANAGER" | null,
        project: null,
      },
      workflow: {
        id: workflowId,
        name,
        status,
        nodeCount: nodes.length,
        lastSavedAt: workflowUpdatedAt,
      },
      selectedNodeIds: selectedNode ? [selectedNode.id] : [],
    }
  }, [isLoading, workflowId, name, status, nodes.length, workflowUpdatedAt, selectedNode, selectedWorkspace])

  useRegisterAIContext(aiContext)

  // ── Load existing workflow ───────────────────────────────────────────────
  useEffect(() => {
    if (workflowId === "new") return
    let cancelled = false
    setIsLoading(true)
    getWorkflow(workflowId)
      .then((wf: Workflow) => {
        if (cancelled) return
        setName(wf.name)
        setDescription(wf.description ?? "")
        setTags(wf.tags ?? [])
        setStatus(wf.status ?? "draft")
        setIsTemplate(wf.is_template ?? false)
        setIsPublished(wf.is_published ?? false)
        const def = wf.definition ?? {}
        // Expande corpos inline de loops (data.body) em nos-filho com
        // parentId — assim o usuario edita visualmente no canvas.
        const expanded = expandInlineLoopBodies(
          (def.nodes as Node[]) ?? [],
          (def.edges as Edge[]) ?? [],
        )
        const loadedNodes = expanded.nodes
        setNodes(loadedNodes)
        setEdges(expanded.edges)
        setWorkflowMeta((def.meta as Record<string, unknown>) ?? {})
        const loadedIoSchema = def.io_schema as WorkflowIOSchema | undefined
        setIoSchema({
          inputs: loadedIoSchema?.inputs ?? [],
          outputs: loadedIoSchema?.outputs ?? [],
        })
        setDirty(false)
        setWorkflowUpdatedAt(wf.updated_at)
        // Store workspace_id for later use (auth scope in test endpoint)
        if (wf.workspace_id) setWorkflowWorkspaceId(wf.workspace_id)
        // Pre-populate exec states from pinned outputs so data is visible immediately
        const pinnedStates: Record<string, NodeExecState> = {}
        for (const n of loadedNodes) {
          const pinned = (n.data as Record<string, unknown>)?.pinnedOutput as Record<string, unknown> | undefined
          if (pinned) pinnedStates[n.id] = pinnedOutputToState(pinned)
        }
        if (Object.keys(pinnedStates).length > 0) setNodeExecStates(pinnedStates)
      })
      .catch(() => {
        if (!cancelled) toast.error("Erro ao carregar workflow", "Tente recarregar a página.")
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    // Busca status atual do schedule (cron) — silencioso em caso de erro
    refreshScheduleStatus()
    // Variaveis herdadas: busca inicial (sera re-buscada apos saves)
    void refreshInheritedVariables()
    return () => {
      cancelled = true
    }
  }, [workflowId, setNodes, setEdges, refreshScheduleStatus])

  // ── Esc cancels build mode ───────────────────────────────────────────────
  useEffect(() => {
    if (!isInBuildMode) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") void cancelBuild(workflowId)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [isInBuildMode, cancelBuild, workflowId])

  // ── Load custom node definitions (composite_insert palette) ──────────────
  useEffect(() => {
    const wsId = workflowWorkspaceId ?? selectedWorkspace?.id
    if (!wsId) {
      setCustomNodes([])
      return
    }
    let cancelled = false
    listWorkspaceCustomNodeDefinitions(wsId)
      .then((list) => {
        if (cancelled) return
        setCustomNodes(list.filter((d) => d.is_published))
      })
      .catch(() => {
        if (!cancelled) setCustomNodes([])
      })
    return () => {
      cancelled = true
    }
  }, [workflowWorkspaceId, selectedWorkspace?.id])

  // ── Alignment helper lines (Figma-style smart guides during drag) ───────
  const [helperLines, setHelperLines] = useState<{
    horizontal?: GuideLine
    vertical?: GuideLine
  }>({})

  // ── Node/edge change wrappers that mark dirty for user-initiated changes ──
  const onNodesChangeDirty = useCallback(
    (changes: NodeChange[]) => {
      // Smart guides: only when a single node is being actively dragged
      const dragChange = changes.length === 1 && changes[0].type === "position" ? changes[0] : null
      if (dragChange && dragChange.dragging && dragChange.position) {
        const result = getHelperLines(dragChange, nodes)
        if (result.snapPosition.x != null) dragChange.position.x = result.snapPosition.x
        if (result.snapPosition.y != null) dragChange.position.y = result.snapPosition.y
        setHelperLines({ horizontal: result.horizontal, vertical: result.vertical })
      } else if (helperLines.horizontal || helperLines.vertical) {
        setHelperLines({})
      }

      onNodesChange(changes)
      if (changes.some((c) => c.type === "position" || c.type === "remove")) {
        setDirty(true)
      }
    },
    [onNodesChange, nodes, helperLines.horizontal, helperLines.vertical],
  )

  const onEdgesChangeDirty = useCallback(
    (changes: EdgeChange[]) => {
      onEdgesChange(changes)
      if (changes.some((c) => c.type === "remove")) {
        setDirty(true)
      }
    },
    [onEdgesChange],
  )

  // ── Edge connections ─────────────────────────────────────────────────────
  const onConnect = useCallback(
    (params: Connection) => {
      setEdges((eds) =>
        addEdge({ ...params, style: { strokeWidth: 2 }, animated: true }, eds),
      )
      setDirty(true)
    },
    [setEdges],
  )

  // ── Node selection ───────────────────────────────────────────────────────
  // Single click selects visually; double-click opens config modal
  const onNodeClick = useCallback((_event: React.MouseEvent, _node: Node) => {
    // Selection is handled by React Flow internally
  }, [])

  const onNodeDoubleClick = useCallback((_event: React.MouseEvent, node: Node) => {
    setSelectedNode(node)
  }, [])

  const onPaneClick = useCallback(() => {
    setSelectedNode(null)
  }, [])

  // ── Context menu (right-click em nó ou seleção) ─────────────────────────
  const [contextMenu, setContextMenu] = useState<
    | { x: number; y: number; nodeIds: string[] }
    | null
  >(null)

  const openContextMenu = useCallback(
    (event: React.MouseEvent, targetIds: string[]) => {
      event.preventDefault()
      if (isInBuildMode || targetIds.length === 0) return
      setContextMenu({ x: event.clientX, y: event.clientY, nodeIds: targetIds })
    },
    [isInBuildMode],
  )

  const closeContextMenu = useCallback(() => setContextMenu(null), [])

  const onNodeContextMenu = useCallback(
    (event: React.MouseEvent, node: Node) => {
      const selectedIds = nodes.filter((n) => n.selected).map((n) => n.id)
      const targetIds =
        selectedIds.includes(node.id) && selectedIds.length > 1
          ? selectedIds
          : [node.id]
      // Se o nó não estava selecionado, marque-o como único selecionado
      if (!selectedIds.includes(node.id)) {
        setNodes((nds) =>
          nds.map((n) => ({ ...n, selected: n.id === node.id })),
        )
      }
      openContextMenu(event, targetIds)
    },
    [nodes, setNodes, openContextMenu],
  )

  const onSelectionContextMenu = useCallback(
    (event: React.MouseEvent, selected: Node[]) => {
      openContextMenu(
        event,
        selected.map((n) => n.id),
      )
    },
    [openContextMenu],
  )

  const applyEnabled = useCallback(
    (ids: string[], enabled: boolean) => {
      const idSet = new Set(ids)
      setNodes((nds) =>
        nds.map((n) =>
          idSet.has(n.id)
            ? { ...n, data: { ...n.data, enabled } }
            : n,
        ),
      )
      setDirty(true)
      closeContextMenu()
    },
    [setNodes, closeContextMenu],
  )

  const duplicateNodes = useCallback(
    (ids: string[]) => {
      const idSet = new Set(ids)
      const originals = nodes.filter((n) => idSet.has(n.id))
      if (originals.length === 0) {
        closeContextMenu()
        return
      }
      const idMap = new Map<string, string>()
      const clones: Node[] = originals.map((n) => {
        const newId = generateNodeId()
        idMap.set(n.id, newId)
        return {
          ...n,
          id: newId,
          position: { x: n.position.x + 40, y: n.position.y + 40 },
          selected: true,
          data: { ...n.data },
        }
      })
      // Duplica também as arestas internas à seleção
      const edgeClones: Edge[] = edges
        .filter((e) => idMap.has(e.source) && idMap.has(e.target))
        .map((e) => ({
          ...e,
          id: `edge_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
          source: idMap.get(e.source)!,
          target: idMap.get(e.target)!,
          selected: false,
        }))
      setNodes((nds) => [
        ...nds.map((n) => ({ ...n, selected: false })),
        ...clones,
      ])
      if (edgeClones.length > 0) setEdges((eds) => [...eds, ...edgeClones])
      setDirty(true)
      closeContextMenu()
    },
    [nodes, edges, setNodes, setEdges, closeContextMenu],
  )

  const removeNodes = useCallback(
    (ids: string[]) => {
      const idSet = new Set(ids)
      setNodes((nds) => nds.filter((n) => !idSet.has(n.id)))
      setEdges((eds) =>
        eds.filter((e) => !idSet.has(e.source) && !idSet.has(e.target)),
      )
      setDirty(true)
      closeContextMenu()
    },
    [setNodes, setEdges, closeContextMenu],
  )

  // ── Drag & drop from library ─────────────────────────────────────────────
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = "move"
  }, [])

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault()
      const type = event.dataTransfer.getData("application/reactflow-type")
      if (!type || !reactFlowInstance) return

      const definition = getNodeDefinition(type)
      if (!definition) return

      const position = reactFlowInstance.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      })

      let data: Record<string, unknown> = {
        ...definition.defaultData,
        label: definition.label,
      }

      // composite_insert: snapshot blueprint from the custom definition
      if (type === "composite_insert") {
        const defId = event.dataTransfer.getData("application/reactflow-definition-id")
        const customDef = findCustomNode(customNodes, defId)
        if (!customDef) return
        data = {
          ...data,
          label: customDef.name,
          definition_id: customDef.id,
          definition_version: customDef.version,
          icon: customDef.icon ?? null,
          color: customDef.color ?? null,
          blueprint: customDef.blueprint,
          form_schema: customDef.form_schema ?? null,
          field_mapping: {},
        }
      }

      const newNode: Node = {
        id: generateNodeId(),
        type,
        position,
        data,
      }

      setNodes((nds) => [...nds, newNode])
      setDirty(true)
    },
    [reactFlowInstance, setNodes, customNodes],
  )

  // ── Update node data from config panel ───────────────────────────────────
  const onUpdateNodeData = useCallback(
    (nodeId: string, data: Record<string, unknown>) => {
      setNodes((nds) =>
        nds.map((n) => (n.id === nodeId ? { ...n, data } : n)),
      )
      setSelectedNode((prev) =>
        prev && prev.id === nodeId ? { ...prev, data } : prev,
      )
      // Update exec state: keep pinned data visible; clear stale output otherwise
      setNodeExecStates((prev) => {
        const pinned = (data as Record<string, unknown>)?.pinnedOutput as Record<string, unknown> | undefined
        if (pinned) {
          return { ...prev, [nodeId]: pinnedOutputToState(pinned) }
        }
        if (!prev[nodeId]) return prev
        const { [nodeId]: _, ...rest } = prev
        return rest
      })
      setDirty(true)
    },
    [setNodes],
  )

  // ── Build definition payload (strips execution state) ────────────────────
  function buildDefinition() {
    // Empacota filhos de loops inline (parentId) de volta em data.body
    // antes de serializar — o backend espera body.nodes/body.edges,
    // nao parentId no array flat.
    const collapsed = collapseInlineLoopBodies(nodes, edges)
    return {
      nodes: collapsed.nodes.map((n) => ({
        id: n.id,
        type: n.type,
        position: n.position,
        data: n.data,
      })),
      edges: collapsed.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle ?? null,
        targetHandle: e.targetHandle ?? null,
      })),
      meta: workflowMeta,
      io_schema: ioSchema,
      variables,
    }
  }

  // Mark dirty only on metadata changes (not nodes/edges — those use inline setDirty)
  useEffect(() => {
    if (!isLoading) setDirty(true)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, description, workflowMeta, ioSchema])

  // ── Export workflow as JSON file ─────────────────────────────────────────
  const handleExport = useCallback(() => {
    const payload = {
      name,
      description: description || null,
      status,
      is_template: isTemplate,
      is_published: isPublished,
      definition: buildDefinition(),
      exported_at: new Date().toISOString(),
    }
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" })
    const url = URL.createObjectURL(blob)
    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "")
    const a = document.createElement("a")
    a.href = url
    a.download = `workflow-${slug || "export"}.json`
    a.click()
    URL.revokeObjectURL(url)
    toast.success("Workflow exportado", "Arquivo JSON gerado com sucesso.")
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, description, status, isTemplate, isPublished, nodes, edges, workflowMeta, variables, ioSchema])

  // ── Import workflow from JSON file ──────────────────────────────────────
  const handleImport = useCallback(() => {
    const input = document.createElement("input")
    input.type = "file"
    input.accept = ".json"
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      try {
        const text = await file.text()
        const data = JSON.parse(text)
        const def = data.definition
        if (!def || !Array.isArray(def.nodes) || !Array.isArray(def.edges)) {
          toast.error("Arquivo JSON inválido", "Estrutura de workflow não encontrada.")
          return
        }
        // Apply to canvas
        setNodes(def.nodes as Node[])
        setEdges(def.edges as Edge[])
        if (def.meta) setWorkflowMeta(def.meta as Record<string, unknown>)
        if (def.io_schema) {
          const imported = def.io_schema as WorkflowIOSchema
          setIoSchema({
            inputs: imported.inputs ?? [],
            outputs: imported.outputs ?? [],
          })
        }
        if (Array.isArray(def.variables)) {
          setVariables(def.variables as WorkflowVariable[])
        }
        if (typeof data.name === "string" && data.name) setName(data.name)
        if (typeof data.description === "string") setDescription(data.description)
        if (data.status === "draft" || data.status === "published") setStatus(data.status)
        if (typeof data.is_template === "boolean") setIsTemplate(data.is_template)
        if (typeof data.is_published === "boolean") setIsPublished(data.is_published)
        // Clear execution states (imported flow hasn't been run)
        setNodeExecStates({})
        setDirty(true)
        toast.success("Workflow importado", "Clique em Salvar para persistir as alterações.")
      } catch {
        toast.error("Erro ao importar", "Não foi possível ler o arquivo JSON.")
      }
    }
    input.click()
  }, [setNodes, setEdges])

  // ── Export workflow as SQL/Python/YAML via backend ───────────────────────
  const handleExportFormat = useCallback(
    async (format: WorkflowExportFormat) => {
      if (workflowId === "new") {
        toast.error("Salve o fluxo primeiro", "Workflows novos precisam ser salvos antes de exportar.")
        return
      }
      try {
        const { blob, filename } = await exportWorkflow(workflowId, format)
        const url = URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = filename
        a.click()
        URL.revokeObjectURL(url)
        toast.success("Workflow exportado", `Arquivo ${filename} gerado.`)
      } catch (err) {
        if (err instanceof WorkflowExportError) {
          setUnsupportedReport({ format, items: err.unsupported })
          toast.error(
            "Não foi possível exportar",
            `${err.unsupported.length} nó(s) não suportado(s) neste formato.`,
          )
          return
        }
        toast.error("Erro ao exportar", err instanceof Error ? err.message : "Falha desconhecida.")
      }
    },
    [workflowId, toast],
  )

  // ── Import workflow from YAML via backend ────────────────────────────────
  const handleImportYaml = useCallback(() => {
    const input = document.createElement("input")
    input.type = "file"
    input.accept = ".yaml,.yml"
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      try {
        // Para YAML import, criamos um novo workflow no workspace ativo;
        // o usuario depois decide se transfere para um projeto especifico.
        if (!workflowWorkspaceId) {
          toast.error("Workspace não selecionado", "Selecione um workspace antes de importar.")
          return
        }
        const created = await importWorkflowYaml(file, { workspaceId: workflowWorkspaceId })
        toast.success(
          "Workflow importado",
          `Criado como '${created.name}'. Abrindo o novo fluxo…`,
        )
        // Redireciona para o fluxo recem-criado.
        if (typeof window !== "undefined") {
          window.location.href = `/workflows/${created.id}`
        }
      } catch (err) {
        toast.error("Erro ao importar", err instanceof Error ? err.message : "Arquivo invalido.")
      }
    }
    input.click()
  }, [workflowWorkspaceId, toast])

  // ── Save ─────────────────────────────────────────────────────────────────
  const handleSave = useCallback(async () => {
    if (workflowId === "new") return
    setIsSaving(true)
    try {
      await updateWorkflow(workflowId, {
        name,
        description: description || null,
        tags,
        definition: buildDefinition(),
      })
      setDirty(false)
      toast.success("Fluxo salvo", "Todas as alterações foram persistidas.")
      // Reflete eventuais mudancas no agendamento (adicao/remocao de no cron)
      refreshScheduleStatus()
      // Re-coleta variaveis herdadas — adicionar/remover call_workflow altera a lista.
      void refreshInheritedVariables()
    } catch (err: unknown) {
      toast.error("Erro ao salvar", err instanceof Error ? err.message : "Tente novamente.")
    } finally {
      setIsSaving(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflowId, name, description, tags, nodes, edges, workflowMeta, variables, ioSchema, refreshScheduleStatus, toast])

  // ── Settings changes (persist immediately) ───────────────────────────────
  const handleStatusChange = useCallback(async (newStatus: "draft" | "published") => {
    if (workflowId === "new") return
    setStatus(newStatus)
    try {
      await updateWorkflow(workflowId, { status: newStatus })
      // Mudanca de Teste <-> Producao ativa/desativa o schedule
      refreshScheduleStatus()
    } catch (err: unknown) {
      toast.error("Erro ao alterar status", err instanceof Error ? err.message : "Tente novamente.")
    }
  }, [workflowId, refreshScheduleStatus])

  const handleIsTemplateChange = useCallback(async (value: boolean) => {
    if (workflowId === "new") return
    setIsTemplate(value)
    try {
      await updateWorkflow(workflowId, { is_template: value })
    } catch (err: unknown) {
      toast.error("Erro ao alterar template", err instanceof Error ? err.message : "Tente novamente.")
    }
  }, [workflowId])

  const handleIsPublishedChange = useCallback(async (value: boolean) => {
    if (workflowId === "new") return
    setIsPublished(value)
    try {
      await updateWorkflow(workflowId, { is_published: value })
    } catch (err: unknown) {
      toast.error("Erro ao alterar publicação", err instanceof Error ? err.message : "Tente novamente.")
    }
  }, [workflowId])

  // ── Sweep: fecha nos presos em "running" quando a execucao termina ──────
  // Chamado em todo ponto terminal (execution_complete, error, onError,
  // onDone, abort). Defesa contra casos em que o backend encerra sem emitir
  // node_complete/node_error para um no (ex.: crash do runner, SSE cortada
  // no meio, irmao em paralelo que o runner nao drenou). Sem isso, a UI
  // fica com spinner eterno no no.
  const sweepRunningNodes = useCallback((reason: string) => {
    setNodeExecStates((prev) => {
      let changed = false
      const next: Record<string, NodeExecState> = {}
      for (const [id, st] of Object.entries(prev)) {
        if (st?.status === "running") {
          changed = true
          next[id] = { status: "aborted", error: reason }
        } else {
          next[id] = st
        }
      }
      return changed ? next : prev
    })
  }, [])

  // ── Execute (SSE streaming test) ─────────────────────────────────────────
  const handleExecute = useCallback(async (
    targetNodeId?: string,
    variableValues?: Record<string, unknown>,
  ) => {
    if (workflowId === "new") return

    // Cancel any in-flight execution
    abortControllerRef.current?.abort()
    const controller = new AbortController()
    abortControllerRef.current = controller

    // Reset state — preserve pinned node outputs so they remain visible
    const pinnedStates: Record<string, NodeExecState> = {}
    for (const n of nodes) {
      const pinned = (n.data as Record<string, unknown>)?.pinnedOutput as Record<string, unknown> | undefined
      if (pinned) pinnedStates[n.id] = pinnedOutputToState(pinned)
    }
    setNodeExecStates(pinnedStates)
    setExecEvents([])
    setShowExecPanel(true)
    setIsExecuting(true)

    // Salva apenas quando há alteração local — clique consecutivo em
    // "Executar" sem editar nada paga rede zero. ``dirty`` é setado pelos
    // wrappers de change em nodes/edges/metadata; ver setDirty(true) acima.
    if (dirty) {
      setExecutionPhase("saving")
      try {
        await updateWorkflow(workflowId, {
          name,
          description: description || null,
          tags,
          definition: buildDefinition(),
        })
        setDirty(false)
      } catch (err: unknown) {
        setIsExecuting(false)
        setExecutionPhase("idle")
        toast.error(
          "Erro ao salvar antes de executar",
          err instanceof Error ? err.message : "Tente novamente.",
        )
        return
      }
    }
    setExecutionPhase("connecting")

    const scopeId = workflowWorkspaceId ?? selectedWorkspace?.id

    // Mock inputs declarados no nó workflow_input — usados apenas ao testar
    // o sub-workflow isoladamente. Em chamadas reais via call_workflow, o pai
    // sobrescreve estes valores.
    const inputNode = nodes.find((n) => n.type === "workflow_input")
    const mockInputs = (inputNode?.data as Record<string, unknown> | undefined)?.mock_inputs
    const baseInput =
      mockInputs && typeof mockInputs === "object" && !Array.isArray(mockInputs)
        ? (mockInputs as Record<string, unknown>)
        : undefined
    const inputData =
      variableValues && Object.keys(variableValues).length > 0
        ? { ...(baseInput ?? {}), variable_values: variableValues }
        : baseInput

    await testWorkflowStream(
      workflowId,
      scopeId,
      {
        onEvent: (event) => {
          setExecEvents((prev) => [...prev, event])

          if (event.type === "execution_start") {
            executionIdRef.current = event.execution_id
            setExecutionPhase("streaming")
          } else if (event.type === "node_start") {
            setNodeExecStates((prev) => ({
              ...prev,
              [event.node_id]: { status: "running" },
            }))
          } else if (event.type === "node_complete") {
            const execId = executionIdRef.current ?? undefined
            setNodeExecStates((prev) => ({
              ...prev,
              [event.node_id]: {
                status: (event.status as NodeExecState["status"]) ?? "success",
                duration_ms: event.duration_ms,
                output_reference: event.output_reference,
                row_count: event.row_count,
                columns: Array.isArray(event.columns) ? (event.columns as string[]) : null,
                failed_rows_count:
                  typeof event.failed_rows_count === "number" ? event.failed_rows_count : null,
                execution_id: execId,
                error: event.error,
                is_pinned: event.is_pinned === true,
              },
            }))
          } else if (event.type === "node_error") {
            setNodeExecStates((prev) => ({
              ...prev,
              [event.node_id]: {
                status: "error",
                duration_ms: event.duration_ms,
                error: event.error,
              },
            }))
          } else if (event.type === "node_progress") {
            // Atualiza o progresso sem sair do estado "running". Se o evento
            // chegar depois do terminal (race), preservamos o status final.
            setNodeExecStates((prev) => {
              const current = prev[event.node_id]
              if (current && current.status !== "running") return prev
              return {
                ...prev,
                [event.node_id]: {
                  ...(current ?? { status: "running" }),
                  status: "running",
                  progress: {
                    current: event.current,
                    total: event.total,
                    succeeded: event.succeeded,
                    failed: event.failed,
                  },
                },
              }
            })
          } else if (event.type === "execution_complete") {
            setIsExecuting(false)
            setExecutionPhase("idle")
            sweepRunningNodes("Execução encerrada antes da conclusão deste nó.")
          } else if (event.type === "error") {
            toast.error("Erro na execução", event.error)
            setIsExecuting(false)
            setExecutionPhase("idle")
            sweepRunningNodes("Execução encerrada antes da conclusão deste nó.")
          }
        },
        onError: (msg) => {
          toast.error("Erro na execução", msg)
          setIsExecuting(false)
          setExecutionPhase("idle")
          sweepRunningNodes("Execução encerrada antes da conclusão deste nó.")
        },
        onDone: () => {
          setIsExecuting(false)
          setExecutionPhase("idle")
          sweepRunningNodes("Execução encerrada antes da conclusão deste nó.")
        },
      },
      controller.signal,
      targetNodeId,
      inputData,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflowId, dirty, name, description, tags, nodes, edges, workflowMeta, variables, ioSchema, workflowWorkspaceId, selectedWorkspace])

  // ── Execute with variable values (regular POST, not SSE) ────────────────
  const handleExecuteWithVars = useCallback(
    async (variableValues: Record<string, unknown>) => {
      if (workflowId === "new") return
      // Save latest definition first
      await updateWorkflow(workflowId, {
        name,
        description: description || null,
        tags,
        definition: buildDefinition(),
      })
      await executeWorkflowWithVars(workflowId, variableValues)
      setActiveTab("executions")
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [workflowId, name, description, nodes, edges, workflowMeta, variables, ioSchema],
  )

  // ── Open execute dialog (saves first so schema endpoint sees fresh refs) ─
  const openExecuteDialog = useCallback(
    async (mode: { kind: "test"; targetNodeId?: string } | { kind: "preview" }) => {
      if (workflowId === "new") return
      setIsOpeningDialog(true)
      if (dirty) {
        try {
          await updateWorkflow(workflowId, {
            name,
            description: description || null,
            tags,
            definition: buildDefinition(),
          })
          setDirty(false)
          // Apos salvar, re-coleta herdadas para o dialog refletir mudancas
          // (ex.: trocar workflow_id em um no call_workflow).
          void refreshInheritedVariables()
        } catch (err: unknown) {
          setIsOpeningDialog(false)
          toast.error(
            "Erro ao salvar",
            err instanceof Error ? err.message : "Tente novamente.",
          )
          return
        }
      }
      setIsOpeningDialog(false)
      setExecuteDialogMode(mode)
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [workflowId, dirty, name, description, tags, nodes, edges, workflowMeta, variables, ioSchema, toast, refreshInheritedVariables],
  )

  const handleAbortExecution = useCallback(() => {
    abortControllerRef.current?.abort()
    setIsExecuting(false)
    setExecutionPhase("idle")
    sweepRunningNodes("Execução cancelada pelo usuário.")
    setExecEvents((prev) => [
      ...prev,
      {
        type: "error" as const,
        error: "Execução cancelada pelo usuário.",
      },
    ])
  }, [sweepRunningNodes])

  // Keep selected node in sync with nodes state
  const currentSelectedNode = selectedNode
    ? nodes.find((n) => n.id === selectedNode.id) ?? null
    : null

  // Compute upstream outputs via BFS to collect ALL ancestors (not just direct parents)
  const upstreamOutputs: UpstreamOutput[] = useMemo(() => {
    if (!currentSelectedNode) return []

    const visited = new Set<string>()
    const queue: Array<{ nodeId: string; depth: number }> = [{ nodeId: currentSelectedNode.id, depth: 0 }]
    const ordered: Array<{ nodeId: string; depth: number }> = []

    while (queue.length > 0) {
      const item = queue.shift()!
      const parents = edges
        .filter((e) => e.target === item.nodeId)
        .map((e) => e.source)
      for (const parentId of parents) {
        if (!visited.has(parentId)) {
          visited.add(parentId)
          ordered.push({ nodeId: parentId, depth: item.depth + 1 })
          queue.push({ nodeId: parentId, depth: item.depth + 1 })
        }
      }
    }

    return ordered.map(({ nodeId, depth }) => {
      const srcNode = nodes.find((n) => n.id === nodeId)
      const srcData = (srcNode?.data ?? {}) as Record<string, unknown>
      const state = nodeExecStates[nodeId]
      // SSE node_complete é "lean": só carrega output_reference + row_count
      // + columns, não traz dados inline. Sintetizamos o shape esperado pelo
      // DataViewer (que detecta {output_reference, ...} como kind=execution_preview
      // e busca a prévia sob demanda via /executions/{id}/nodes/{id}/preview).
      // O ``columns`` aqui alimenta useUpstreamFields() — pickers/auto-map de
      // nós downstream (Mapper, Filter, Bulk Insert, etc.) ficavam vazios sem isso.
      const output: Record<string, unknown> | null = state?.output
        ?? (state?.output_reference
          ? {
              output_reference: state.output_reference,
              row_count: state.row_count ?? null,
              columns: state.columns ?? null,
            }
          : null)
      return {
        nodeId,
        label: (srcData.label as string) ?? srcNode?.type ?? nodeId,
        nodeType: srcNode?.type ?? "unknown",
        output,
        executionId: state?.execution_id ?? null,
        depth,
      }
    })
  }, [currentSelectedNode, edges, nodes, nodeExecStates])

  // Current node's execution state for the OUTPUT panel
  const selectedNodeExecState = currentSelectedNode
    ? nodeExecStates[currentSelectedNode.id] ?? null
    : null

  // Must be declared before any early return (Rules of Hooks)
  const nodeActionsValue = useMemo(
    () => ({ onExecuteNode: (_nodeId: string) => handleExecute() }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [handleExecute],
  )

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center bg-background">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <MorphLoader className="size-4" />
          Carregando workflow…
        </div>
      </div>
    )
  }

  return (
    <WorkflowVariablesContext.Provider value={{ variables }}>
    <CustomNodesContext.Provider value={customNodes}>
    <NodeActionsContext.Provider value={nodeActionsValue}>
    <NodeExecutionContext.Provider value={nodeExecStates}>
      <div className="flex h-full flex-col overflow-hidden bg-background">
        <WorkflowToolbar
          name={name}
          description={description}
          tags={tags}
          status={status}
          isTemplate={isTemplate}
          isPublished={isPublished}
          onNameChange={setName}
          onDescriptionChange={setDescription}
          onTagsChange={setTags}
          onStatusChange={handleStatusChange}
          onIsTemplateChange={handleIsTemplateChange}
          onIsPublishedChange={handleIsPublishedChange}
          onSave={handleSave}
          onExecute={() => void openExecuteDialog({ kind: "test" })}
          onExport={handleExport}
          onExportFormat={handleExportFormat}
          onImport={handleImport}
          onImportYaml={handleImportYaml}
          onOpenIoSchema={workflowId !== "new" ? () => setShowIoSchemaEditor(true) : undefined}
          onOpenVariables={workflowId !== "new" ? () => setShowVariablesPanel(true) : undefined}
          variableCount={variables.length}
          onOpenPublish={
            workflowId !== "new"
              ? () => {
                  if (!isIoSchemaValid(ioSchema)) {
                    toast.error(
                      "Schema de I/O inválido",
                      "Corrija nomes duplicados ou com padrão inválido antes de publicar.",
                    )
                    setShowIoSchemaEditor(true)
                    return
                  }
                  setShowPublishModal(true)
                }
              : undefined
          }
          scheduleStatus={scheduleStatus}
          isSaving={isSaving}
          isExecuting={isExecuting || isOpeningDialog}
          activeTab={activeTab}
          onTabChange={setActiveTab}
        />

        {/* Build mode bar foi movida para o chat (AIBuildConfirmationCard) para
            evitar duplicar o controle de confirmacao. O card no chat consome o
            mesmo BuildModeContext e chama confirmBuild/cancelBuild. */}

        {/* Build ops panel — lateral overlay listing proposed ops + undo */}
        {(isInBuildMode || canUndo) && (
          <div className="absolute right-3 top-3 z-10 pointer-events-auto">
            <BuildOpsPanel
              workflowId={workflowId}
              sessionId={buildSessionId}
              onSelectNode={(nodeId) => {
                setNodes((prev) => prev.map((n) => ({ ...n, selected: n.id === nodeId })))
              }}
            />
          </div>
        )}

        {/* Editor body wrapper — relative pra ancorar a sidebar da Biblioteca
            de Nos (full-height) sobre canvas + execution panel. */}
        <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">

        {/* Main area: canvas + config panel */}
        <div className={cn(
          "flex min-h-0 flex-1 overflow-hidden",
          activeTab !== "editor" && "hidden",
        )}>
          {/* Canvas */}
          <div className="relative flex-1" ref={reactFlowWrapper}>
            {/* Canvas mode toggle + Biblioteca — toolbar superior esquerdo.
                Pan, Select, e Biblioteca agrupados pra UX consistente
                (Figma/n8n-style). Biblioteca abre o sidebar; quando aberto,
                o botao some pra evitar redundancia visual. */}
            <div className="absolute left-3 top-3 z-20 flex flex-col overflow-hidden rounded-md border border-border bg-card shadow-sm">
              <button
                type="button"
                onClick={() => setCanvasMode("pan")}
                aria-label="Modo arrastar: mover o canvas"
                title="Modo arrastar — clique e arraste para mover o canvas"
                aria-pressed={canvasMode === "pan"}
                className={`flex size-9 items-center justify-center transition-colors ${
                  canvasMode === "pan"
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                <Hand className="size-4" />
              </button>
              <div className="h-px bg-border" />
              <button
                type="button"
                onClick={() => setCanvasMode("select")}
                aria-label="Modo seleção: selecionar múltiplos nós"
                title="Modo seleção — arraste para selecionar vários nós (use espaço+arrastar para mover o canvas)"
                aria-pressed={canvasMode === "select"}
                className={`flex size-9 items-center justify-center transition-colors ${
                  canvasMode === "select"
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                <MousePointer2 className="size-4" />
              </button>
              {!showLibrary && (
                <>
                  <div className="h-px bg-border" />
                  <button
                    type="button"
                    onClick={() => setShowLibrary(true)}
                    aria-label="Abrir biblioteca de nós"
                    title="Abrir biblioteca de nós"
                    className="flex size-9 items-center justify-center text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    <LayoutGrid className="size-4" />
                  </button>
                </>
              )}
            </div>

            {/* Agent stream status — temporariamente oculto enquanto o Agente
                fica desativado em producao. Pra reativar: remover este {false &&}. */}
            {false && workflowId !== "new" && !isLoading && (
              <div
                className="absolute bottom-3 right-14 z-20 flex h-[34px] items-center gap-1.5 rounded-[10px] border border-slate-900/10 bg-white/95 px-2.5 text-[11px] font-medium text-slate-600 shadow-[0_1px_0_rgba(255,255,255,0.9)_inset,0_6px_18px_-8px_rgba(15,23,42,0.25)] backdrop-blur dark:border-slate-400/20 dark:bg-slate-800/90 dark:text-slate-300"
                title={
                  streamStatus === "connected"
                    ? "Agente conectado"
                    : streamStatus === "connecting"
                      ? "Conectando ao agente..."
                      : streamStatus === "reconnecting"
                        ? "Reconectando..."
                        : "Agente desconectado"
                }
              >
                <span
                  className={cn(
                    "size-1.5 rounded-full",
                    streamStatus === "connected" && "bg-green-500",
                    streamStatus === "connecting" && "bg-yellow-400 animate-pulse",
                    streamStatus === "reconnecting" && "bg-yellow-400 animate-pulse",
                    streamStatus === "error" && "bg-red-400",
                  )}
                />
                <span>
                  {streamStatus === "connected" && "Agente"}
                  {streamStatus === "connecting" && "Conectando..."}
                  {streamStatus === "reconnecting" && "Reconectando..."}
                  {streamStatus === "error" && "Desconectado"}
                </span>
              </div>
            )}

            {/* Read-only overlay during build mode */}
            {isInBuildMode && (
              <div className="pointer-events-none absolute inset-0 z-10 rounded-sm ring-2 ring-inset ring-violet-400/30" />
            )}

            <ReactFlow
              nodes={isInBuildMode ? [...nodes, ...pendingNodes] : nodes}
              edges={isInBuildMode ? [...edges, ...pendingEdges] : edges}
              onNodesChange={isInBuildMode ? undefined : onNodesChangeDirty}
              onEdgesChange={isInBuildMode ? undefined : onEdgesChangeDirty}
              onConnect={isInBuildMode ? undefined : onConnect}
              onNodeClick={onNodeClick}
              onNodeDoubleClick={isInBuildMode ? undefined : onNodeDoubleClick}
              onNodeContextMenu={isInBuildMode ? undefined : onNodeContextMenu}
              onSelectionContextMenu={isInBuildMode ? undefined : onSelectionContextMenu}
              onPaneClick={onPaneClick}
              onDragOver={isInBuildMode ? undefined : onDragOver}
              onDrop={isInBuildMode ? undefined : onDrop}
              onInit={setReactFlowInstance}
              nodeTypes={nodeTypes}
              edgeTypes={EDGE_TYPES}
              fitView
              minZoom={0.1}
              maxZoom={3}
              deleteKeyCode={isInBuildMode ? null : ["Backspace", "Delete"]}
              nodesDraggable={!isInBuildMode}
              nodesConnectable={!isInBuildMode}
              elementsSelectable={!isInBuildMode}
              edgesFocusable={!isInBuildMode}
              panOnDrag={canvasMode === "pan" ? [0, 1, 2] : [1, 2]}
              selectionOnDrag={!isInBuildMode && canvasMode === "select"}
              selectionMode={SelectionMode.Partial}
              multiSelectionKeyCode={["Shift", "Meta", "Control"]}
              panActivationKeyCode="Space"
              className={`workflow-canvas workflow-canvas--${canvasMode}`}
              proOptions={{ hideAttribution: true }}
              defaultEdgeOptions={{
                animated: false,
              }}
            >
              <Background
                variant={BackgroundVariant.Dots}
                gap={20}
                size={1}
                className="!bg-background"
              />
              <HelperLines horizontal={helperLines.horizontal} vertical={helperLines.vertical} />
            </ReactFlow>

            {/* Floating zoom controls — bottom-left */}
            <ZoomControls />
          </div>

        </div>

        {/* Executions tab — monta somente quando ativa para evitar poll desnecessario */}
        {activeTab === "executions" && (
          <div className="flex min-h-0 flex-1 overflow-hidden">
            <ExecutionsTab workflowId={workflowId} active={activeTab === "executions"} />
          </div>
        )}

        {/* Execution log panel — fica DENTRO do wrapper relative pra que a
            sidebar da Biblioteca consiga sobrepor/empurrar quando aberta. */}
        {showExecPanel && (
          <ExecutionPanel
            events={execEvents}
            isRunning={isExecuting}
            phase={executionPhase}
            onAbort={handleAbortExecution}
            onClose={() => setShowExecPanel(false)}
            libraryOpen={showLibrary}
          />
        )}

        {/* Node library — sidebar full-height cobrindo canvas + execution panel */}
        <NodeLibrary open={showLibrary} onClose={() => setShowLibrary(false)} />

        </div>{/* /editor body wrapper */}

        {/* Node config modal (3-column: INPUT | PARAMS | OUTPUT) */}
        {currentSelectedNode && (
          <NodeConfigModal
            node={currentSelectedNode}
            workflowId={workflowId}
            upstreamOutputs={upstreamOutputs}
            currentOutput={selectedNodeExecState}
            isExecuting={isExecuting}
            ioSchema={ioSchema}
            onClose={() => setSelectedNode(null)}
            onUpdate={onUpdateNodeData}
            onExecute={() => {
              if (variables.length > 0) {
                void openExecuteDialog({ kind: "test", targetNodeId: currentSelectedNode.id })
              } else {
                void handleExecute(currentSelectedNode.id)
              }
            }}
            onWebhookTestEvent={(capture) => {
              // Expoe o payload recebido pelo "Listen for test event" no
              // painel OUTPUT do no selecionado.
              setNodeExecStates((prev) => ({
                ...prev,
                [currentSelectedNode.id]: {
                  status: "success",
                  output: {
                    method: capture.method,
                    headers: capture.headers,
                    query_params: capture.query_params,
                    data: capture.body,
                  },
                },
              }))
            }}
          />
        )}

        {/* I/O Schema drawer */}
        {showIoSchemaEditor && (
          <div
            className="fixed inset-0 z-40 flex items-stretch justify-end bg-black/30 backdrop-blur-[2px]"
            onClick={() => setShowIoSchemaEditor(false)}
          >
            <div
              className="flex h-full w-full max-w-3xl flex-col border-l border-border bg-background shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              <header className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
                <div>
                  <h2 className="text-sm font-semibold text-foreground">
                    Schema de I/O
                  </h2>
                  <p className="text-[10px] text-muted-foreground">
                    Declare os inputs e outputs expostos quando este workflow é
                    chamado como sub-workflow.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setShowIoSchemaEditor(false)}
                  aria-label="Fechar"
                  className="flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  <X className="size-4" />
                </button>
              </header>
              <IoSchemaEditor value={ioSchema} onChange={setIoSchema} />
              <footer className="flex shrink-0 items-center justify-end border-t border-border px-4 py-2">
                <button
                  type="button"
                  onClick={() => setShowIoSchemaEditor(false)}
                  className="inline-flex h-8 items-center rounded-md bg-primary px-3 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
                >
                  Aplicar
                </button>
              </footer>
            </div>
          </div>
        )}

        {/* Variables panel */}
        {showVariablesPanel && workflowId !== "new" && (
          <VariablesPanel
            workflowId={workflowId}
            variables={variables}
            inheritedVariables={inheritedVariables}
            isSaving={isVariablesSaving}
            error={variablesError}
            onClose={() => setShowVariablesPanel(false)}
            onChange={setVariables}
            onSave={saveVariables}
            onPreview={() => void openExecuteDialog({ kind: "preview" })}
          />
        )}

        {/* Context menu (botão direito em nó / seleção) */}
        {contextMenu && (
          <NodeContextMenu
            x={contextMenu.x}
            y={contextMenu.y}
            nodeIds={contextMenu.nodeIds}
            nodes={nodes}
            onEnable={(ids) => applyEnabled(ids, true)}
            onDisable={(ids) => applyEnabled(ids, false)}
            onDuplicate={duplicateNodes}
            onRemove={removeNodes}
            onClose={closeContextMenu}
          />
        )}

        {/* Execute / preview dialog */}
        {executeDialogMode !== null && workflowId !== "new" && (
          <ExecuteWorkflowDialog
            workflowId={workflowId}
            previewOnly={executeDialogMode.kind === "preview"}
            onClose={() => setExecuteDialogMode(null)}
            onDirectExecute={() => {
              const mode = executeDialogMode
              setExecuteDialogMode(null)
              if (mode?.kind === "test") {
                void handleExecute(mode.targetNodeId)
              } else {
                void handleExecute()
              }
            }}
            onExecuteWithVars={async (values) => {
              if (executeDialogMode?.kind === "test") {
                await handleExecute(executeDialogMode.targetNodeId, values)
                return
              }
              await handleExecuteWithVars(values)
            }}
          />
        )}

        {/* Publish version modal */}
        {showPublishModal && workflowId !== "new" && (
          <PublishVersionModal
            workflowId={workflowId}
            ioSchema={ioSchema}
            hasUnsavedChanges={dirty}
            onSaveBeforePublish={handleSave}
            onClose={() => setShowPublishModal(false)}
            onPublished={(v) => {
              toast.success(`Versão v${v.version} publicada`, "A nova versão já está disponível.")
            }}
          />
        )}

        {unsupportedReport && (
          <UnsupportedNodesDialog
            format={unsupportedReport.format}
            items={unsupportedReport.items}
            onClose={() => setUnsupportedReport(null)}
            onFocus={(nodeId) => {
              const node = nodes.find((n) => n.id === nodeId)
              if (node) {
                setNodes((cur) =>
                  cur.map((n) => ({ ...n, selected: n.id === nodeId })),
                )
              }
              setUnsupportedReport(null)
            }}
          />
        )}

      </div>
    </NodeExecutionContext.Provider>
    </NodeActionsContext.Provider>
    </CustomNodesContext.Provider>
    </WorkflowVariablesContext.Provider>
  )
}

function UnsupportedNodesDialog({
  format,
  items,
  onClose,
  onFocus,
}: {
  format: WorkflowExportFormat
  items: UnsupportedNodeReport[]
  onClose: () => void
  onFocus: (nodeId: string) => void
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-lg border border-border bg-card p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-foreground">
              Não foi possível exportar para {format.toUpperCase()}
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {items.length} nó(s) não são suportados na V1 deste formato.
              Clique em um item para selecioná-lo no canvas.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="Fechar"
          >
            <X className="size-4" />
          </button>
        </div>

        <ul className="max-h-80 overflow-y-auto rounded-md border border-border">
          {items.map((item) => (
            <li
              key={item.node_id}
              className="border-b border-border last:border-0"
            >
              <button
                type="button"
                onClick={() => onFocus(item.node_id)}
                className="flex w-full flex-col gap-0.5 px-3 py-2 text-left transition-colors hover:bg-muted"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-mono text-xs font-medium text-foreground">
                    {item.node_id}
                  </span>
                  <span className="rounded bg-amber-500/15 px-1.5 py-0.5 font-mono text-[10px] font-medium text-amber-700 dark:text-amber-400">
                    {item.node_type}
                  </span>
                </div>
                <span className="text-[11px] text-muted-foreground">
                  {item.reason}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}


function ZoomControls() {
  const { zoomIn, zoomOut, fitView } = useReactFlow()
  return (
    <div className="absolute bottom-3 right-3 z-20 flex flex-col overflow-hidden rounded-md border border-border bg-card shadow-sm">
      <button
        type="button"
        onClick={() => zoomIn()}
        aria-label="Aumentar zoom"
        title="Aumentar zoom"
        className="flex size-9 items-center justify-center text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <ZoomIn className="size-4" />
      </button>
      <div className="h-px bg-border" />
      <button
        type="button"
        onClick={() => zoomOut()}
        aria-label="Diminuir zoom"
        title="Diminuir zoom"
        className="flex size-9 items-center justify-center text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <ZoomOut className="size-4" />
      </button>
      <div className="h-px bg-border" />
      <button
        type="button"
        onClick={() => fitView({ padding: 0.2, duration: 300 })}
        aria-label="Ajustar ao canvas"
        title="Ajustar ao canvas"
        className="flex size-9 items-center justify-center text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <Maximize2 className="size-4" />
      </button>
    </div>
  )
}

export function WorkflowEditor(props: WorkflowEditorProps) {
  // BuildModeProvider subiu para o layout privado (app/(private)/layout.tsx)
  // para que o AIPanel possa consumir o mesmo state. Aqui nao re-instanciamos.
  return (
    <ReactFlowProvider>
      <WorkflowEditorInner {...props} />
    </ReactFlowProvider>
  )
}

// ─── Context menu para nós selecionados ─────────────────────────────────────
interface NodeContextMenuProps {
  x: number
  y: number
  nodeIds: string[]
  nodes: Node[]
  onEnable: (ids: string[]) => void
  onDisable: (ids: string[]) => void
  onDuplicate: (ids: string[]) => void
  onRemove: (ids: string[]) => void
  onClose: () => void
}

function NodeContextMenu({
  x,
  y,
  nodeIds,
  nodes,
  onEnable,
  onDisable,
  onDuplicate,
  onRemove,
  onClose,
}: NodeContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ x, y })

  // Clamp: ajusta posição para não estourar a viewport
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const { innerWidth, innerHeight } = window
    const rect = el.getBoundingClientRect()
    let nx = x
    let ny = y
    if (x + rect.width > innerWidth - 8) nx = Math.max(8, innerWidth - rect.width - 8)
    if (y + rect.height > innerHeight - 8) ny = Math.max(8, innerHeight - rect.height - 8)
    setPos({ x: nx, y: ny })
  }, [x, y])

  useEffect(() => {
    function onDown(e: MouseEvent) {
      const target = e.target as globalThis.Node | null
      if (ref.current && target && !ref.current.contains(target)) onClose()
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("mousedown", onDown)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onDown)
      document.removeEventListener("keydown", onKey)
    }
  }, [onClose])

  const count = nodeIds.length
  const targets = nodes.filter((n) => nodeIds.includes(n.id))
  const allEnabled = targets.every(
    (n) => (n.data as Record<string, unknown>)?.enabled !== false,
  )
  const allDisabled = targets.every(
    (n) => (n.data as Record<string, unknown>)?.enabled === false,
  )

  const label = count === 1 ? "1 nó" : `${count} nós`

  return (
    <div
      ref={ref}
      onContextMenu={(e) => e.preventDefault()}
      className="fixed z-[60] min-w-[220px] overflow-hidden rounded-lg border border-border bg-card shadow-xl"
      style={{ left: pos.x, top: pos.y }}
    >
      <div className="border-b border-border bg-muted/40 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label} selecionado{count > 1 ? "s" : ""}
      </div>
      <div className="p-1">
        {!allEnabled && (
          <button
            type="button"
            onClick={() => onEnable(nodeIds)}
            className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs text-foreground transition-colors hover:bg-muted"
          >
            <Power className="size-3.5 text-emerald-600" />
            Ativar {count > 1 ? "selecionados" : ""}
          </button>
        )}
        {!allDisabled && (
          <button
            type="button"
            onClick={() => onDisable(nodeIds)}
            className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs text-foreground transition-colors hover:bg-muted"
          >
            <PowerOff className="size-3.5 text-muted-foreground" />
            Desativar {count > 1 ? "selecionados" : ""}
          </button>
        )}
        <button
          type="button"
          onClick={() => onDuplicate(nodeIds)}
          className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs text-foreground transition-colors hover:bg-muted"
        >
          <Copy className="size-3.5 text-muted-foreground" />
          Duplicar {count > 1 ? "selecionados" : ""}
        </button>
        <div className="my-1 h-px bg-border" />
        <button
          type="button"
          onClick={() => onRemove(nodeIds)}
          className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs text-destructive transition-colors hover:bg-destructive/10"
        >
          <Trash2 className="size-3.5" />
          Remover {count > 1 ? "selecionados" : ""}
        </button>
      </div>
    </div>
  )
}
