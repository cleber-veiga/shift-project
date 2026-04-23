"use client"

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react"
import type { Edge, Node } from "@xyflow/react"
import { getValidSession } from "@/lib/auth"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type BuildModeState = "idle" | "building" | "awaiting_confirmation"

/** Op summary shown in the BuildOpsPanel. */
export interface PendingOp {
  id: string           // node_id or edge_id
  kind: "node" | "edge"
  nodeType?: string    // e.g. "filter", "mapper"
  label: string
  status: "pending" | "applied" | "failed"
}

export interface BuildModeContextValue {
  buildState: BuildModeState
  sessionId: string | null
  pendingNodes: Node[]
  pendingEdges: Edge[]
  pendingOps: PendingOp[]

  // Called from SSE handler when build_started arrives
  enterBuildMode: (sessionId: string) => void
  // Called from SSE handler when build_ready arrives
  setAwaiting: () => void
  // Called from SSE handler when build_cancelled / build_confirmed arrive
  // Pass confirmed=true when called from build_confirmed to mark ops as applied
  exitBuildMode: (confirmed?: boolean) => void

  // Called from SSE handler to add/update/remove ghost nodes/edges
  addPendingNode: (node: Record<string, unknown>) => void
  addPendingEdge: (edge: Record<string, unknown>) => void
  updatePendingNode: (nodeId: string, dataPatch: Record<string, unknown>) => void
  removePendingNode: (nodeId: string) => void
  removePendingEdge: (edgeId: string) => void

  // Promove ghost nodes/edges para o canvas real de forma sincrona, evitando
  // race de refs stale quando build_confirmed chega colado em pending_node_added.
  // Os updaters recebidos sao os setters reais (setNodes/setEdges do editor).
  flushPendingToReal: (
    setRealNodes: (updater: (prev: Node[]) => Node[]) => void,
    setRealEdges: (updater: (prev: Edge[]) => Edge[]) => void,
  ) => { nodeCount: number; edgeCount: number }

  // Dispensa o painel de operacoes propostas apos um confirm bem sucedido
  // (sem executar undo). Limpa canUndo e pendingOps.
  dismissConfirmedOps: () => void

  // Called from BuildModeBar buttons
  confirmBuild: (workflowId: string, registerMutation?: (id: string) => void) => Promise<void>
  cancelBuild: (workflowId: string) => Promise<void>
  /** Desfaz a ultima sessao confirmada (disponivel por ~5min apos confirm). */
  undoBuild: (workflowId: string) => Promise<void>

  isConfirming: boolean
  isCancelling: boolean
  isUndoing: boolean
  /** Set a true apos confirm bem-sucedido; limpo apos undo ou timeout. */
  canUndo: boolean
  error: string | null
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const BuildModeContext = createContext<BuildModeContextValue | null>(null)

function getApiBaseUrl() {
  const value = process.env.NEXT_PUBLIC_API_BASE_URL
  return value && value.trim().length > 0 ? value.trim() : "http://localhost:8000/api/v1"
}

async function authedPost(
  path: string,
  body?: unknown,
  extraHeaders?: Record<string, string>,
): Promise<Response> {
  const session = await getValidSession()
  return fetch(`${getApiBaseUrl()}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${session?.accessToken ?? ""}`,
      ...extraHeaders,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function BuildModeProvider({ children }: { children: ReactNode }) {
  const [buildState, setBuildState] = useState<BuildModeState>("idle")
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [pendingNodes, setPendingNodes] = useState<Node[]>([])
  const [pendingEdges, setPendingEdges] = useState<Edge[]>([])
  const [pendingOps, setPendingOps] = useState<PendingOp[]>([])
  const [isConfirming, setIsConfirming] = useState(false)
  const [isCancelling, setIsCancelling] = useState(false)
  const [isUndoing, setIsUndoing] = useState(false)
  const [canUndo, setCanUndo] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const undoTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const confirmSseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const sessionIdRef = useRef<string | null>(null)
  const workflowIdRef = useRef<string | null>(null)
  // Preserved after exitBuildMode so undoBuild can still reference the confirmed session.
  const confirmedSessionIdRef = useRef<string | null>(null)
  const confirmedWorkflowIdRef = useRef<string | null>(null)
  // Mirrors de pendingNodes/pendingEdges. Usados em flushPendingToReal para
  // ler o valor mais recente sem precisar chamar setPendingNodes com um
  // updater que, por sua vez, invocava setRealNodes — padrao proibido pelo
  // React (setState de outro componente durante render/updater de setState).
  const pendingNodesRef = useRef<Node[]>([])
  const pendingEdgesRef = useRef<Edge[]>([])

  // ---------------------------------------------------------------------------
  // State transitions (called from SSE hook)
  // ---------------------------------------------------------------------------

  const enterBuildMode = useCallback((sid: string) => {
    setSessionId(sid)
    sessionIdRef.current = sid
    pendingNodesRef.current = []
    pendingEdgesRef.current = []
    setPendingNodes([])
    setPendingEdges([])
    setPendingOps([])
    setBuildState("building")
    setCanUndo(false)
    setError(null)
  }, [])

  const setAwaiting = useCallback(() => {
    setBuildState("awaiting_confirmation")
  }, [])

  const exitBuildMode = useCallback((confirmed?: boolean) => {
    if (confirmSseTimerRef.current) {
      clearTimeout(confirmSseTimerRef.current)
      confirmSseTimerRef.current = null
    }
    setBuildState("idle")
    setSessionId(null)
    sessionIdRef.current = null
    pendingNodesRef.current = []
    pendingEdgesRef.current = []
    setPendingNodes([])
    setPendingEdges([])
    if (confirmed) {
      // Mark all ops as applied when confirmed via SSE
      setPendingOps((prev) => prev.map((op) => ({ ...op, status: "applied" as const })))
      setCanUndo(true)
      if (undoTimerRef.current) clearTimeout(undoTimerRef.current)
      undoTimerRef.current = setTimeout(() => setCanUndo(false), 5 * 60 * 1000)
    } else {
      setPendingOps([])
    }
    setIsConfirming(false)
    setIsCancelling(false)
    setIsUndoing(false)
    setError(null)
  }, [])

  // ---------------------------------------------------------------------------
  // Ghost node/edge mutations (called from SSE hook)
  // ---------------------------------------------------------------------------

  const addPendingNode = useCallback((raw: Record<string, unknown>) => {
    const node: Node = {
      id: raw.id as string,
      type: raw.type as string,
      position: raw.position as { x: number; y: number },
      data: { ...((raw.data as Record<string, unknown>) ?? {}), __pending: true },
    }
    // Ref e source of truth: atualizado sincronamente para que eventos SSE
    // consecutivos (antes do React renderizar) nao sofram race. setState
    // apenas sincroniza a UI.
    if (pendingNodesRef.current.some((n) => n.id === node.id)) return
    pendingNodesRef.current = [...pendingNodesRef.current, node]
    setPendingNodes(pendingNodesRef.current)
    setPendingOps((prev) => {
      if (prev.some((op) => op.id === node.id)) return prev
      const data = node.data as Record<string, unknown>
      return [
        ...prev,
        {
          id: node.id,
          kind: "node",
          nodeType: node.type,
          label: (data?.label as string) || node.type || node.id,
          status: "pending",
        },
      ]
    })
  }, [])

  const addPendingEdge = useCallback((raw: Record<string, unknown>) => {
    const edge: Edge = {
      id: raw.id as string,
      source: raw.source as string,
      target: raw.target as string,
      sourceHandle: (raw.sourceHandle as string) ?? null,
      targetHandle: (raw.targetHandle as string) ?? null,
      data: { ...((raw.data as Record<string, unknown>) ?? {}), __pending: true },
      style: { strokeWidth: 2, strokeDasharray: "6 4" },
      animated: true,
    }
    if (pendingEdgesRef.current.some((e) => e.id === edge.id)) return
    pendingEdgesRef.current = [...pendingEdgesRef.current, edge]
    setPendingEdges(pendingEdgesRef.current)
    setPendingOps((prev) => {
      if (prev.some((op) => op.id === edge.id)) return prev
      return [
        ...prev,
        {
          id: edge.id,
          kind: "edge",
          label: `${edge.source} → ${edge.target}`,
          status: "pending",
        },
      ]
    })
  }, [])

  const updatePendingNode = useCallback(
    (nodeId: string, dataPatch: Record<string, unknown>) => {
      pendingNodesRef.current = pendingNodesRef.current.map((n) =>
        n.id === nodeId
          ? { ...n, data: { ...n.data, ...dataPatch, __pending: true } }
          : n,
      )
      setPendingNodes(pendingNodesRef.current)
    },
    [],
  )

  const removePendingNode = useCallback((nodeId: string) => {
    pendingNodesRef.current = pendingNodesRef.current.filter(
      (n) => n.id !== nodeId,
    )
    pendingEdgesRef.current = pendingEdgesRef.current.filter(
      (e) => e.source !== nodeId && e.target !== nodeId,
    )
    setPendingNodes(pendingNodesRef.current)
    setPendingEdges(pendingEdgesRef.current)
  }, [])

  const removePendingEdge = useCallback((edgeId: string) => {
    pendingEdgesRef.current = pendingEdgesRef.current.filter(
      (e) => e.id !== edgeId,
    )
    setPendingEdges(pendingEdgesRef.current)
  }, [])

  // Sincronamente promove ghost nodes/edges para o canvas real. Le o valor
  // mais recente de pendingNodes/pendingEdges de refs espelho (sincronizados
  // em useEffect). Antes usavamos setPendingNodes com updater para capturar
  // o valor fresco, mas isso disparava setRealNodes DE DENTRO de um updater
  // — padrao proibido pelo React ("Cannot update a component while rendering
  // a different component") porque updaters podem ser reexecutados em
  // StrictMode/Concurrent. Agora cada setState e chamado no escopo plano do
  // callback, sem aninhamento.
  const flushPendingToReal = useCallback<BuildModeContextValue["flushPendingToReal"]>(
    (setRealNodes, setRealEdges) => {
      const currentNodes = pendingNodesRef.current
      const currentEdges = pendingEdgesRef.current
      const nodeCount = currentNodes.length
      const edgeCount = currentEdges.length

      if (nodeCount > 0) {
        const promoted = currentNodes.map((g) => ({
          ...g,
          data: { ...(g.data as Record<string, unknown>), __pending: undefined },
        }))
        setRealNodes((prevReal) => {
          const fresh = promoted.filter((p) => !prevReal.some((n) => n.id === p.id))
          return [...prevReal, ...fresh]
        })
      }

      if (edgeCount > 0) {
        const promoted = currentEdges.map((g) => ({
          ...g,
          data: { ...(g.data as Record<string, unknown>), __pending: undefined },
          style: { strokeWidth: 2 },
          animated: true,
        }))
        setRealEdges((prevReal) => {
          const fresh = promoted.filter((p) => !prevReal.some((e) => e.id === p.id))
          return [...prevReal, ...fresh]
        })
      }

      // Limpa o estado de ghosts apos promover: refs sao a source of truth,
      // setState apenas sincroniza a UI.
      if (nodeCount > 0) {
        pendingNodesRef.current = []
        setPendingNodes([])
      }
      if (edgeCount > 0) {
        pendingEdgesRef.current = []
        setPendingEdges([])
      }

      return { nodeCount, edgeCount }
    },
    [],
  )

  const dismissConfirmedOps = useCallback(() => {
    if (undoTimerRef.current) {
      clearTimeout(undoTimerRef.current)
      undoTimerRef.current = null
    }
    setCanUndo(false)
    setPendingOps([])
    confirmedSessionIdRef.current = null
    confirmedWorkflowIdRef.current = null
  }, [])

  // ---------------------------------------------------------------------------
  // Confirm / Cancel (called from BuildModeBar)
  // ---------------------------------------------------------------------------

  const confirmBuild = useCallback(
    async (workflowId: string, registerMutation?: (id: string) => void) => {
      if (!sessionId || isConfirming) return
      workflowIdRef.current = workflowId
      confirmedWorkflowIdRef.current = workflowId
      confirmedSessionIdRef.current = sessionId
      setIsConfirming(true)
      setError(null)
      const mutationId = crypto.randomUUID()
      registerMutation?.(mutationId)
      try {
        const res = await authedPost(
          `/workflows/${workflowId}/build-sessions/${sessionId}/confirm`,
          undefined,
          { "X-Client-Mutation-Id": mutationId },
        )
        if (!res.ok) {
          const err = (await res.json().catch(() => ({}))) as { detail?: string }
          throw new Error(err.detail ?? `Erro ${res.status}`)
        }
        // Mark ops as "applying" — "applied" only after build_confirmed SSE arrives
        setPendingOps((prev) => prev.map((op) => ({ ...op, status: "pending" as const })))
        // 10s safety timeout: warn user if SSE confirmation never arrives
        if (confirmSseTimerRef.current) clearTimeout(confirmSseTimerRef.current)
        confirmSseTimerRef.current = setTimeout(() => {
          setError("Confirmação demorou; verifique a conexão e tente novamente.")
          setIsConfirming(false)
        }, 10_000)
      } catch (e) {
        setError(e instanceof Error ? e.message : "Erro ao confirmar build.")
        setIsConfirming(false)
      }
    },
    [sessionId, isConfirming],
  )

  const cancelBuild = useCallback(
    async (workflowId: string) => {
      if (!sessionId || isCancelling) return
      setIsCancelling(true)
      setError(null)
      try {
        const res = await authedPost(
          `/workflows/${workflowId}/build-sessions/${sessionId}/cancel`,
        )
        if (!res.ok) {
          const err = (await res.json().catch(() => ({}))) as { detail?: string }
          throw new Error(err.detail ?? `Erro ${res.status}`)
        }
        // exitBuildMode will be called when build_cancelled SSE arrives
      } catch (e) {
        setError(e instanceof Error ? e.message : "Erro ao cancelar build.")
        setIsCancelling(false)
      }
    },
    [sessionId, isCancelling],
  )

  const undoBuild = useCallback(
    async (workflowId: string) => {
      const sid = confirmedSessionIdRef.current ?? sessionIdRef.current ?? sessionId
      const wid = workflowId || confirmedWorkflowIdRef.current
      if (!sid || !wid || isUndoing || !canUndo) return
      setIsUndoing(true)
      setError(null)
      try {
        const res = await authedPost(
          `/workflows/${wid}/build-sessions/${sid}/undo`,
        )
        if (!res.ok) {
          const err = (await res.json().catch(() => ({}))) as { detail?: string }
          throw new Error(err.detail ?? `Erro ${res.status}`)
        }
        setCanUndo(false)
        if (undoTimerRef.current) clearTimeout(undoTimerRef.current)
        setPendingOps([])
        confirmedSessionIdRef.current = null
        confirmedWorkflowIdRef.current = null
      } catch (e) {
        setError(e instanceof Error ? e.message : "Erro ao desfazer build.")
      } finally {
        setIsUndoing(false)
      }
    },
    [sessionId, isUndoing, canUndo],
  )

  // Esc key: cancel build mode (with confirmation if many ops pending)
  useEffect(() => {
    if (buildState === "idle") return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return
      const wid = workflowIdRef.current
      if (!wid) return
      if (pendingNodes.length > 3) {
        if (!window.confirm(`Cancelar build e perder ${pendingNodes.length} operações?`)) return
      }
      void cancelBuild(wid)
    }
    document.addEventListener("keydown", handleKeyDown)
    return () => document.removeEventListener("keydown", handleKeyDown)
  }, [buildState, pendingNodes.length, cancelBuild])

  // Heartbeat: ping every 10s while in build/awaiting state
  useEffect(() => {
    if (buildState === "idle") {
      if (heartbeatRef.current) clearInterval(heartbeatRef.current)
      return
    }
    heartbeatRef.current = setInterval(async () => {
      const sid = sessionIdRef.current
      const wid = workflowIdRef.current
      if (!sid || !wid) return
      try {
        await authedPost(`/workflows/${wid}/build-sessions/${sid}/heartbeat`)
      } catch {
        // heartbeat failures are non-fatal; backend will eventually clean up
      }
    }, 10_000)
    return () => {
      if (heartbeatRef.current) clearInterval(heartbeatRef.current)
    }
  }, [buildState])

  return (
    <BuildModeContext.Provider
      value={{
        buildState,
        sessionId,
        pendingNodes,
        pendingEdges,
        pendingOps,
        enterBuildMode,
        setAwaiting,
        exitBuildMode,
        addPendingNode,
        addPendingEdge,
        updatePendingNode,
        removePendingNode,
        removePendingEdge,
        flushPendingToReal,
        dismissConfirmedOps,
        confirmBuild,
        cancelBuild,
        undoBuild,
        isConfirming,
        isCancelling,
        isUndoing,
        canUndo,
        error,
      }}
    >
      {children}
    </BuildModeContext.Provider>
  )
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useBuildMode(): BuildModeContextValue {
  const ctx = useContext(BuildModeContext)
  if (!ctx) throw new Error("useBuildMode must be used inside BuildModeProvider")
  return ctx
}
