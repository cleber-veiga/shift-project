/**
 * Tests for the ghost __pending flag in BuildModeProvider.
 *
 * Coverage:
 *  - addPendingNode injects __pending: true
 *  - addPendingNode preserves other data fields
 *  - addPendingEdge injects __pending: true into data
 *  - updatePendingNode preserves __pending after patch
 *  - updatePendingNode does not let patch overwrite __pending to false
 *  - exitBuildMode clears pendingNodes and pendingEdges
 */

import { renderHook, act } from "@testing-library/react"
import { BuildModeProvider, useBuildMode } from "@/lib/workflow/build-mode-context"
import type { ReactNode } from "react"

// Suppress "getValidSession" import — only needed for API calls, not state ops
vi.mock("@/lib/auth", () => ({
  getValidSession: vi.fn().mockResolvedValue({ accessToken: "test-token" }),
}))

const wrapper = ({ children }: { children: ReactNode }) => (
  <BuildModeProvider>{children}</BuildModeProvider>
)

// ---------------------------------------------------------------------------
// addPendingNode
// ---------------------------------------------------------------------------

describe("addPendingNode", () => {
  it("injects __pending: true into node data", () => {
    const { result } = renderHook(() => useBuildMode(), { wrapper })

    act(() => {
      result.current.addPendingNode({
        id: "node_1",
        type: "sql_script",
        position: { x: 100, y: 200 },
        data: { query: "SELECT 1" },
      })
    })

    expect(result.current.pendingNodes).toHaveLength(1)
    expect(result.current.pendingNodes[0].data.__pending).toBe(true)
  })

  it("preserves other fields in data alongside __pending", () => {
    const { result } = renderHook(() => useBuildMode(), { wrapper })

    act(() => {
      result.current.addPendingNode({
        id: "node_2",
        type: "filter",
        position: { x: 0, y: 0 },
        data: { label: "Filtro A", conditions: [{ field: "age", op: "gt", value: 18 }] },
      })
    })

    const data = result.current.pendingNodes[0].data as Record<string, unknown>
    expect(data.__pending).toBe(true)
    expect(data.label).toBe("Filtro A")
    expect(data.conditions).toHaveLength(1)
  })

  it("sets __pending when data is omitted", () => {
    const { result } = renderHook(() => useBuildMode(), { wrapper })

    act(() => {
      result.current.addPendingNode({
        id: "node_3",
        type: "mapper",
        position: { x: 0, y: 0 },
        // no data field
      })
    })

    expect(result.current.pendingNodes[0].data.__pending).toBe(true)
  })

  it("does not duplicate a node added twice", () => {
    const { result } = renderHook(() => useBuildMode(), { wrapper })

    act(() => {
      result.current.addPendingNode({ id: "node_dup", type: "t", position: { x: 0, y: 0 }, data: {} })
      result.current.addPendingNode({ id: "node_dup", type: "t", position: { x: 0, y: 0 }, data: {} })
    })

    expect(result.current.pendingNodes).toHaveLength(1)
  })
})

// ---------------------------------------------------------------------------
// addPendingEdge
// ---------------------------------------------------------------------------

describe("addPendingEdge", () => {
  it("injects __pending: true into edge data", () => {
    const { result } = renderHook(() => useBuildMode(), { wrapper })

    act(() => {
      result.current.addPendingEdge({
        id: "edge_1",
        source: "node_a",
        target: "node_b",
        data: { weight: 42 },
      })
    })

    expect(result.current.pendingEdges).toHaveLength(1)
    const data = result.current.pendingEdges[0].data as Record<string, unknown>
    expect(data.__pending).toBe(true)
    expect(data.weight).toBe(42)
  })

  it("sets __pending when edge has no data field", () => {
    const { result } = renderHook(() => useBuildMode(), { wrapper })

    act(() => {
      result.current.addPendingEdge({
        id: "edge_2",
        source: "node_a",
        target: "node_b",
      })
    })

    const data = result.current.pendingEdges[0].data as Record<string, unknown>
    expect(data.__pending).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// updatePendingNode — preserves __pending
// ---------------------------------------------------------------------------

describe("updatePendingNode", () => {
  it("preserves __pending: true after a data patch", () => {
    const { result } = renderHook(() => useBuildMode(), { wrapper })

    act(() => {
      result.current.addPendingNode({
        id: "node_upd",
        type: "sql_script",
        position: { x: 0, y: 0 },
        data: { query: "SELECT 1" },
      })
    })

    act(() => {
      result.current.updatePendingNode("node_upd", { query: "SELECT 2", timeout: 30 })
    })

    const data = result.current.pendingNodes[0].data as Record<string, unknown>
    expect(data.__pending).toBe(true)
    expect(data.query).toBe("SELECT 2")
    expect(data.timeout).toBe(30)
  })

  it("__pending stays true even if patch tries to unset it", () => {
    const { result } = renderHook(() => useBuildMode(), { wrapper })

    act(() => {
      result.current.addPendingNode({
        id: "node_ovrw",
        type: "filter",
        position: { x: 0, y: 0 },
        data: {},
      })
    })

    act(() => {
      // Patch that would overwrite __pending — must be ignored
      result.current.updatePendingNode("node_ovrw", { __pending: false } as Record<string, unknown>)
    })

    const data = result.current.pendingNodes[0].data as Record<string, unknown>
    expect(data.__pending).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// exitBuildMode — clears pending collections
// ---------------------------------------------------------------------------

describe("exitBuildMode", () => {
  it("clears pendingNodes and pendingEdges", () => {
    const { result } = renderHook(() => useBuildMode(), { wrapper })

    act(() => {
      result.current.addPendingNode({ id: "n1", type: "t", position: { x: 0, y: 0 }, data: {} })
      result.current.addPendingEdge({ id: "e1", source: "n1", target: "n2" })
    })

    expect(result.current.pendingNodes).toHaveLength(1)
    expect(result.current.pendingEdges).toHaveLength(1)

    act(() => {
      result.current.exitBuildMode()
    })

    expect(result.current.pendingNodes).toHaveLength(0)
    expect(result.current.pendingEdges).toHaveLength(0)
  })
})
