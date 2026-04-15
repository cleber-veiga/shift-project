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
  type NodeTypes,
  type EdgeTypes,
  ReactFlowProvider,
  type ReactFlowInstance,
  BackgroundVariant,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"

import { WorkflowNode } from "@/components/workflow/workflow-node"
import { WorkflowEdge } from "@/components/workflow/workflow-edge"
import { WorkflowToolbar } from "@/components/workflow/workflow-toolbar"
import { NodeLibrary } from "@/components/workflow/node-library"
import { NodeConfigModal, type UpstreamOutput } from "@/components/workflow/node-config-modal"
import { ExecutionPanel } from "@/components/workflow/execution-panel"
import { getNodeDefinition, NODE_REGISTRY } from "@/lib/workflow/types"
import { NodeExecutionContext, type NodeExecState } from "@/lib/workflow/execution-context"
import { NodeActionsContext } from "@/lib/workflow/node-actions-context"
import { Loader2, Plus } from "lucide-react"
import {
  getWorkflow,
  updateWorkflow,
  testWorkflowStream,
  type Workflow,
  type WorkflowTestEvent,
} from "@/lib/auth"
import { useDashboard } from "@/lib/context/dashboard-context"

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
  const [isSaving, setIsSaving] = useState(false)
  const [isExecuting, setIsExecuting] = useState(false)
  const [isLoading, setIsLoading] = useState(workflowId !== "new")
  const [statusMessage, setStatusMessage] = useState<string | null>(null)

  // Workflow workspace_id (needed for test endpoint auth scope)
  const [workflowWorkspaceId, setWorkflowWorkspaceId] = useState<string | undefined>(
    selectedWorkspace?.id,
  )

  const [showLibrary, setShowLibrary] = useState(false)
  const [selectedNode, setSelectedNode] = useState<Node | null>(null)

  // Workflow metadata (player_id, workflow_type, …)
  const [workflowMeta, setWorkflowMeta] = useState<Record<string, unknown>>({})

  // ── Execution state ──────────────────────────────────────────────────────
  const [nodeExecStates, setNodeExecStates] = useState<Record<string, NodeExecState>>({})
  const [execEvents, setExecEvents] = useState<WorkflowTestEvent[]>([])
  const [showExecPanel, setShowExecPanel] = useState(false)
  const abortControllerRef = useRef<AbortController | null>(null)

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
        const def = wf.definition ?? {}
        const loadedNodes = (def.nodes as Node[]) ?? []
        setNodes(loadedNodes)
        setEdges((def.edges as Edge[]) ?? [])
        setWorkflowMeta((def.meta as Record<string, unknown>) ?? {})
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
    return () => {
      cancelled = true
    }
  }, [workflowId, setNodes, setEdges])

  // ── Edge connections ─────────────────────────────────────────────────────
  const onConnect = useCallback(
    (params: Connection) => {
      setEdges((eds) =>
        addEdge({ ...params, style: { strokeWidth: 2 }, animated: true }, eds),
      )
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

      const newNode: Node = {
        id: generateNodeId(),
        type,
        position,
        data: { ...definition.defaultData, label: definition.label },
      }

      setNodes((nds) => [...nds, newNode])
    },
    [reactFlowInstance, setNodes],
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
    }
  }

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
      setStatusMessage("Salvo com sucesso!")
      setTimeout(() => setStatusMessage(null), 2500)
    } catch (err: unknown) {
      setStatusMessage(err instanceof Error ? err.message : "Erro ao salvar")
    } finally {
      setIsSaving(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflowId, name, description, nodes, edges, workflowMeta])

  // ── Execute (SSE streaming test) ─────────────────────────────────────────
  const handleExecute = useCallback(async (targetNodeId?: string) => {
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
            setNodeExecStates((prev) => ({
              ...prev,
              [event.node_id]: {
                status: isSkipped ? "skipped" : "success",
                duration_ms: event.duration_ms,
                output: event.output,
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
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflowId, name, description, nodes, edges, workflowMeta, workflowWorkspaceId, selectedWorkspace])

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

  // Compute upstream outputs for the selected node's INPUT panel
  const upstreamOutputs: UpstreamOutput[] = useMemo(() => {
    if (!currentSelectedNode) return []
    const sourceEdges = edges.filter((e) => e.target === currentSelectedNode.id)
    return sourceEdges.map((e) => {
      const srcNode = nodes.find((n) => n.id === e.source)
      const srcData = (srcNode?.data ?? {}) as Record<string, unknown>
      return {
        nodeId: e.source,
        label: (srcData.label as string) ?? srcNode?.type ?? e.source,
        nodeType: srcNode?.type ?? "unknown",
        output: nodeExecStates[e.source]?.output ?? null,
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
    <NodeActionsContext.Provider value={nodeActionsValue}>
    <NodeExecutionContext.Provider value={nodeExecStates}>
      <div className="flex h-full flex-col overflow-hidden bg-background">
        <WorkflowToolbar
          name={name}
          description={description}
          onNameChange={setName}
          onDescriptionChange={setDescription}
          onSave={handleSave}
          onExecute={handleExecute}
          isSaving={isSaving}
          isExecuting={isExecuting}
        />

        {/* Status message bar */}
        {statusMessage && (
          <div className="flex h-7 shrink-0 items-center justify-center bg-muted/50 text-xs text-muted-foreground">
            {statusMessage}
          </div>
        )}

        {/* Main area: canvas + config panel */}
        <div className="flex min-h-0 flex-1 overflow-hidden">
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

            {/* Node library overlay — fixed so it floats above all overflow containers */}
            {showLibrary && (
              <div
                className="fixed z-50"
                style={{ top: libraryPos.top, left: libraryPos.left, height: libraryPos.height }}
              >
                <NodeLibrary onClose={() => setShowLibrary(false)} />
              </div>
            )}

            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeClick={onNodeClick}
              onNodeDoubleClick={onNodeDoubleClick}
              onPaneClick={onPaneClick}
              onDragOver={onDragOver}
              onDrop={onDrop}
              onInit={setReactFlowInstance}
              nodeTypes={nodeTypes}
              edgeTypes={EDGE_TYPES}
              fitView
              deleteKeyCode={["Backspace", "Delete"]}
              className="workflow-canvas"
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

        {/* Node config modal (3-column: INPUT | PARAMS | OUTPUT) */}
        {currentSelectedNode && (
          <NodeConfigModal
            node={currentSelectedNode}
            upstreamOutputs={upstreamOutputs}
            currentOutput={selectedNodeExecState}
            isExecuting={isExecuting}
            onClose={() => setSelectedNode(null)}
            onUpdate={onUpdateNodeData}
            onExecute={() => handleExecute(currentSelectedNode.id)}
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
  )
}

export function WorkflowEditor(props: WorkflowEditorProps) {
  return (
    <ReactFlowProvider>
      <WorkflowEditorInner {...props} />
    </ReactFlowProvider>
  )
}
