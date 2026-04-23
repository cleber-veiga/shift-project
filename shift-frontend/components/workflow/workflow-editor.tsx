"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  ReactFlow,
  Background,
  addEdge,
  useNodesState,
  useEdgesState,
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
import { WorkflowToolbar } from "@/components/workflow/workflow-toolbar"
import { NodeLibrary } from "@/components/workflow/node-library"
import { NodeConfigModal, type UpstreamOutput } from "@/components/workflow/node-config-modal"
import { ExecutionPanel } from "@/components/workflow/execution-panel"
import { ExecutionsTab } from "@/components/workflow/executions/executions-tab"
import { IoSchemaEditor, isIoSchemaValid } from "@/components/workflow/io-schema-editor"
import { PublishVersionModal } from "@/components/workflow/publish-version-modal"
import { VariablesPanel } from "@/components/workflow/variables-panel"
import { ExecuteWorkflowDialog } from "@/components/workflow/execute-workflow-dialog"
import type { WorkflowIOSchema } from "@/lib/api/workflow-versions"
import { useWorkflowVariables } from "@/lib/workflow/use-workflow-variables"
import { executeWorkflowWithVars } from "@/lib/api/workflow-variables"
import { getNodeDefinition, NODE_REGISTRY, type WorkflowVariable } from "@/lib/workflow/types"
import { NodeExecutionContext, type NodeExecState } from "@/lib/workflow/execution-context"
import { NodeActionsContext } from "@/lib/workflow/node-actions-context"
import { WorkflowVariablesContext } from "@/lib/workflow/workflow-variables-context"
import { Hand, History, Loader2, MousePointer2, Plus, Workflow as WorkflowIcon, X } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  getWorkflow,
  getWorkflowSchedule,
  updateWorkflow,
  testWorkflowStream,
  listWorkspaceCustomNodeDefinitions,
  type CustomNodeDefinition,
  type Workflow,
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
import { BuildOpsPanel } from "@/components/workflow/build-ops-panel"

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
  const libraryButtonRef = useRef<HTMLButtonElement>(null)
  const [libraryPos, setLibraryPos] = useState<{ top: number; left: number; height: number }>({
    top: 0,
    left: 0,
    height: 500,
  })
  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance | null>(null)

  const { selectedWorkspace } = useDashboard()

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)

  const [name, setName] = useState(initialName || "Novo Fluxo")
  const [description, setDescription] = useState(initialDescription)
  const [status, setStatus] = useState<"draft" | "published">("draft")
  const [workflowUpdatedAt, setWorkflowUpdatedAt] = useState<string | null>(null)
  const [isTemplate, setIsTemplate] = useState(false)
  const [isPublished, setIsPublished] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [isExecuting, setIsExecuting] = useState(false)
  const [isLoading, setIsLoading] = useState(workflowId !== "new")
  const [statusMessage, setStatusMessage] = useState<string | null>(null)

  // Workflow workspace_id (needed for test endpoint auth scope)
  const [workflowWorkspaceId, setWorkflowWorkspaceId] = useState<string | undefined>(
    selectedWorkspace?.id,
  )

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

  // ── Schedule state (cron agendado no Prefect) ───────────────────────────
  const [scheduleStatus, setScheduleStatus] = useState<WorkflowScheduleStatus | null>(null)

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
  const abortControllerRef = useRef<AbortController | null>(null)

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
        setStatus(wf.status ?? "draft")
        setIsTemplate(wf.is_template ?? false)
        setIsPublished(wf.is_published ?? false)
        const def = wf.definition ?? {}
        const loadedNodes = (def.nodes as Node[]) ?? []
        setNodes(loadedNodes)
        setEdges((def.edges as Edge[]) ?? [])
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
          if (pinned) pinnedStates[n.id] = { status: "success", output: pinned, is_pinned: true }
        }
        if (Object.keys(pinnedStates).length > 0) setNodeExecStates(pinnedStates)
      })
      .catch(() => {
        if (!cancelled) setStatusMessage("Erro ao carregar workflow")
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    // Busca status atual do schedule (cron) — silencioso em caso de erro
    refreshScheduleStatus()
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

  // ── Node/edge change wrappers that mark dirty for user-initiated changes ──
  const onNodesChangeDirty = useCallback(
    (changes: NodeChange[]) => {
      onNodesChange(changes)
      if (changes.some((c) => c.type === "position" || c.type === "remove")) {
        setDirty(true)
      }
    },
    [onNodesChange],
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
          return { ...prev, [nodeId]: { status: "success", output: pinned, is_pinned: true } }
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
    return {
      nodes: nodes.map((n) => ({
        id: n.id,
        type: n.type,
        position: n.position,
        data: n.data,
      })),
      edges: edges.map((e) => ({
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
    setStatusMessage("Workflow exportado!")
    setTimeout(() => setStatusMessage(null), 2500)
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
          setStatusMessage("Arquivo JSON invalido: estrutura de workflow nao encontrada.")
          setTimeout(() => setStatusMessage(null), 4000)
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
        setStatusMessage("Workflow importado! Clique em Salvar para persistir.")
        setTimeout(() => setStatusMessage(null), 4000)
      } catch {
        setStatusMessage("Erro ao ler o arquivo JSON.")
        setTimeout(() => setStatusMessage(null), 4000)
      }
    }
    input.click()
  }, [setNodes, setEdges])

  // ── Save ─────────────────────────────────────────────────────────────────
  const handleSave = useCallback(async () => {
    if (workflowId === "new") return
    setIsSaving(true)
    setStatusMessage(null)
    try {
      await updateWorkflow(workflowId, {
        name,
        description: description || null,
        definition: buildDefinition(),
      })
      setDirty(false)
      setStatusMessage("Salvo com sucesso!")
      setTimeout(() => setStatusMessage(null), 2500)
      // Reflete eventuais mudancas no agendamento (adicao/remocao de no cron)
      refreshScheduleStatus()
    } catch (err: unknown) {
      setStatusMessage(err instanceof Error ? err.message : "Erro ao salvar")
    } finally {
      setIsSaving(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflowId, name, description, nodes, edges, workflowMeta, variables, ioSchema, refreshScheduleStatus])

  // ── Settings changes (persist immediately) ───────────────────────────────
  const handleStatusChange = useCallback(async (newStatus: "draft" | "published") => {
    if (workflowId === "new") return
    setStatus(newStatus)
    try {
      await updateWorkflow(workflowId, { status: newStatus })
      // Mudanca de Teste <-> Producao ativa/desativa o schedule
      refreshScheduleStatus()
    } catch (err: unknown) {
      setStatusMessage(err instanceof Error ? err.message : "Erro ao alterar status")
    }
  }, [workflowId, refreshScheduleStatus])

  const handleIsTemplateChange = useCallback(async (value: boolean) => {
    if (workflowId === "new") return
    setIsTemplate(value)
    try {
      await updateWorkflow(workflowId, { is_template: value })
    } catch (err: unknown) {
      setStatusMessage(err instanceof Error ? err.message : "Erro ao alterar template")
    }
  }, [workflowId])

  const handleIsPublishedChange = useCallback(async (value: boolean) => {
    if (workflowId === "new") return
    setIsPublished(value)
    try {
      await updateWorkflow(workflowId, { is_published: value })
    } catch (err: unknown) {
      setStatusMessage(err instanceof Error ? err.message : "Erro ao alterar publicação")
    }
  }, [workflowId])

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
      if (pinned) pinnedStates[n.id] = { status: "success", output: pinned, is_pinned: true }
    }
    setNodeExecStates(pinnedStates)
    setExecEvents([])
    setShowExecPanel(true)
    setIsExecuting(true)
    setStatusMessage(null)

    // Save first so the backend sees the latest definition
    try {
      await updateWorkflow(workflowId, {
        name,
        description: description || null,
        definition: buildDefinition(),
      })
    } catch (err: unknown) {
      setIsExecuting(false)
      setStatusMessage(err instanceof Error ? err.message : "Erro ao salvar antes de executar")
      return
    }

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

          if (event.type === "node_start") {
            setNodeExecStates((prev) => ({
              ...prev,
              [event.node_id]: { status: "running" },
            }))
          } else if (event.type === "node_complete") {
            const isSkipped = event.output?.status === "skipped"
            const isHandledError = event.output?.status === "handled_error"
            setNodeExecStates((prev) => ({
              ...prev,
              [event.node_id]: {
                status: isSkipped ? "skipped" : isHandledError ? "handled_error" : "success",
                duration_ms: event.duration_ms,
                output: event.output,
                error:
                  isHandledError && typeof event.output?.error === "string"
                    ? event.output.error
                    : undefined,
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
          } else if (event.type === "execution_complete") {
            setIsExecuting(false)
          } else if (event.type === "error") {
            setStatusMessage(event.error)
            setIsExecuting(false)
          }
        },
        onError: (msg) => {
          setStatusMessage(msg)
          setIsExecuting(false)
        },
        onDone: () => {
          setIsExecuting(false)
        },
      },
      controller.signal,
      targetNodeId,
      inputData,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflowId, name, description, nodes, edges, workflowMeta, variables, ioSchema, workflowWorkspaceId, selectedWorkspace])

  // ── Execute with variable values (regular POST, not SSE) ────────────────
  const handleExecuteWithVars = useCallback(
    async (variableValues: Record<string, unknown>) => {
      if (workflowId === "new") return
      // Save latest definition first
      await updateWorkflow(workflowId, {
        name,
        description: description || null,
        definition: buildDefinition(),
      })
      await executeWorkflowWithVars(workflowId, variableValues)
      setActiveTab("executions")
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [workflowId, name, description, nodes, edges, workflowMeta, variables, ioSchema],
  )

  const handleAbortExecution = useCallback(() => {
    abortControllerRef.current?.abort()
    setIsExecuting(false)
    setExecEvents((prev) => [
      ...prev,
      {
        type: "error" as const,
        error: "Execução cancelada pelo usuário.",
      },
    ])
  }, [])

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
      return {
        nodeId,
        label: (srcData.label as string) ?? srcNode?.type ?? nodeId,
        nodeType: srcNode?.type ?? "unknown",
        output: nodeExecStates[nodeId]?.output ?? null,
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
          <Loader2 className="size-4 animate-spin" />
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
          status={status}
          isTemplate={isTemplate}
          isPublished={isPublished}
          onNameChange={setName}
          onDescriptionChange={setDescription}
          onStatusChange={handleStatusChange}
          onIsTemplateChange={handleIsTemplateChange}
          onIsPublishedChange={handleIsPublishedChange}
          onSave={handleSave}
          onExecute={() => setExecuteDialogMode({ kind: "test" })}
          onExport={handleExport}
          onImport={handleImport}
          onOpenIoSchema={workflowId !== "new" ? () => setShowIoSchemaEditor(true) : undefined}
          onOpenVariables={workflowId !== "new" ? () => setShowVariablesPanel(true) : undefined}
          variableCount={variables.length}
          onOpenPublish={
            workflowId !== "new"
              ? () => {
                  if (!isIoSchemaValid(ioSchema)) {
                    setStatusMessage(
                      "Schema de I/O inválido: corrija nomes duplicados ou com padrão inválido antes de publicar.",
                    )
                    setTimeout(() => setStatusMessage(null), 4000)
                    setShowIoSchemaEditor(true)
                    return
                  }
                  setShowPublishModal(true)
                }
              : undefined
          }
          scheduleStatus={scheduleStatus}
          isSaving={isSaving}
          isExecuting={isExecuting}
        />

        {/* Status message bar */}
        {statusMessage && (
          <div className="flex h-7 shrink-0 items-center justify-center bg-muted/50 text-xs text-muted-foreground">
            {statusMessage}
          </div>
        )}

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

        {/* Agent stream status indicator */}
        {workflowId !== "new" && !isLoading && (
          <div className="flex h-5 shrink-0 items-center gap-1.5 border-b border-border bg-muted/10 px-3">
            <span
              className={cn(
                "size-1.5 rounded-full",
                streamStatus === "connected" && "bg-green-500",
                streamStatus === "connecting" && "bg-yellow-400 animate-pulse",
                streamStatus === "reconnecting" && "bg-yellow-400 animate-pulse",
                streamStatus === "error" && "bg-red-400",
              )}
            />
            <span className="text-[10px] text-muted-foreground">
              {streamStatus === "connected" && "Agente conectado"}
              {streamStatus === "connecting" && "Conectando ao agente..."}
              {streamStatus === "reconnecting" && "Reconectando..."}
              {streamStatus === "error" && "Agente desconectado"}
            </span>
          </div>
        )}

        {/* Tabs: Editor (canvas) | Executions (historico) */}
        <div className="flex shrink-0 items-center gap-1 border-b border-border bg-muted/20 px-4">
          <TabSwitch
            active={activeTab === "editor"}
            onClick={() => setActiveTab("editor")}
            icon={<WorkflowIcon className="size-3.5" />}
            label="Editor"
          />
          <TabSwitch
            active={activeTab === "executions"}
            onClick={() => setActiveTab("executions")}
            icon={<History className="size-3.5" />}
            label="Executions"
          />
        </div>

        {/* Main area: canvas + config panel */}
        <div className={cn(
          "flex min-h-0 flex-1 overflow-hidden",
          activeTab !== "editor" && "hidden",
        )}>
          {/* Canvas */}
          <div className="relative flex-1" ref={reactFlowWrapper}>
            {/* + button to toggle node library */}
            <button
              ref={libraryButtonRef}
              type="button"
              onClick={() => {
                if (!showLibrary && libraryButtonRef.current) {
                  const rect = libraryButtonRef.current.getBoundingClientRect()
                  const top = rect.bottom + 8
                  const height = Math.min(560, window.innerHeight - top - 16)
                  setLibraryPos({ top, left: rect.left, height })
                }
                setShowLibrary((v) => !v)
              }}
              className="absolute left-3 top-3 z-20 flex size-9 items-center justify-center rounded-md border border-border bg-card text-muted-foreground shadow-sm transition-colors hover:bg-muted hover:text-foreground"
              aria-label={showLibrary ? "Fechar biblioteca de nós" : "Adicionar nó"}
            >
              <Plus className={`size-4 transition-transform duration-200 ${showLibrary ? "rotate-45" : ""}`} />
            </button>

            {/* Canvas mode toggle — pan (hand) vs select (multi-selection) */}
            <div className="absolute left-3 top-14 z-20 flex flex-col overflow-hidden rounded-md border border-border bg-card shadow-sm">
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
            </div>

            {/* Node library overlay — fixed so it floats above all overflow containers */}
            {showLibrary && (
              <div
                className="fixed z-50"
                style={{ top: libraryPos.top, left: libraryPos.left, height: libraryPos.height }}
              >
                <NodeLibrary onClose={() => setShowLibrary(false)} />
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
              onPaneClick={onPaneClick}
              onDragOver={isInBuildMode ? undefined : onDragOver}
              onDrop={isInBuildMode ? undefined : onDrop}
              onInit={setReactFlowInstance}
              nodeTypes={nodeTypes}
              edgeTypes={EDGE_TYPES}
              fitView
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
                style: { strokeWidth: 2 },
                animated: true,
              }}
            >
              <Background
                variant={BackgroundVariant.Dots}
                gap={20}
                size={1}
                className="!bg-background"
              />
            </ReactFlow>
          </div>

        </div>

        {/* Executions tab — monta somente quando ativa para evitar poll desnecessario */}
        {activeTab === "executions" && (
          <div className="flex min-h-0 flex-1 overflow-hidden">
            <ExecutionsTab workflowId={workflowId} active={activeTab === "executions"} />
          </div>
        )}

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
                setExecuteDialogMode({ kind: "test", targetNodeId: currentSelectedNode.id })
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
            isSaving={isVariablesSaving}
            error={variablesError}
            onClose={() => setShowVariablesPanel(false)}
            onChange={setVariables}
            onSave={saveVariables}
            onPreview={() => setExecuteDialogMode({ kind: "preview" })}
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
              setStatusMessage(`Versão v${v.version} publicada com sucesso!`)
              setTimeout(() => setStatusMessage(null), 4000)
            }}
          />
        )}

        {/* Execution log panel */}
        {showExecPanel && (
          <ExecutionPanel
            events={execEvents}
            isRunning={isExecuting}
            onAbort={handleAbortExecution}
            onClose={() => setShowExecPanel(false)}
          />
        )}
      </div>
    </NodeExecutionContext.Provider>
    </NodeActionsContext.Provider>
    </CustomNodesContext.Provider>
    </WorkflowVariablesContext.Provider>
  )
}

function TabSwitch({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  label: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-xs transition-colors",
        active
          ? "border-primary font-semibold text-foreground"
          : "border-transparent text-muted-foreground hover:text-foreground",
      )}
    >
      {icon}
      {label}
    </button>
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
