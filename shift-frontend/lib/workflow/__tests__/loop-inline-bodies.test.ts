import { describe, it, expect } from "vitest"
import type { Edge, Node } from "@xyflow/react"
import {
  expandInlineLoopBodies,
  collapseInlineLoopBodies,
} from "../loop-inline-bodies"

function loop(
  id: string,
  bodyMode: "external" | "inline" | undefined,
  body?: { nodes?: Node[]; edges?: Edge[] },
): Node {
  return {
    id,
    type: "loop",
    position: { x: 0, y: 0 },
    data: {
      type: "loop",
      ...(bodyMode ? { body_mode: bodyMode } : {}),
      ...(body ? { body } : {}),
    },
  }
}

function plainNode(id: string, type = "mapper"): Node {
  return {
    id,
    type,
    position: { x: 0, y: 0 },
    data: { type },
  }
}

function edge(id: string, source: string, target: string): Edge {
  return { id, source, target }
}

describe("expandInlineLoopBodies", () => {
  it("leaves non-loop nodes untouched", () => {
    const nodes = [plainNode("a"), plainNode("b")]
    const edges = [edge("e1", "a", "b")]
    const out = expandInlineLoopBodies(nodes, edges)
    expect(out.nodes).toEqual(nodes)
    expect(out.edges).toEqual(edges)
  })

  it("leaves external loops untouched", () => {
    const ext = loop("L", "external")
    const out = expandInlineLoopBodies([ext], [])
    expect(out.nodes).toEqual([ext])
  })

  it("expands inline loop body into children with parentId", () => {
    const child1 = plainNode("c1", "http_request")
    const child2 = plainNode("c2", "mapper")
    const bodyEdge = edge("be1", "c1", "c2")
    const lp = loop("L", "inline", { nodes: [child1, child2], edges: [bodyEdge] })
    const out = expandInlineLoopBodies([lp], [])

    expect(out.nodes).toHaveLength(3)
    const expandedLoop = out.nodes.find((n) => n.id === "L")!
    expect(
      (expandedLoop.data as Record<string, unknown>).body,
    ).toBeUndefined()

    const c1 = out.nodes.find((n) => n.id === "c1") as Node & { parentId?: string }
    const c2 = out.nodes.find((n) => n.id === "c2") as Node & { parentId?: string }
    expect(c1.parentId).toBe("L")
    expect(c2.parentId).toBe("L")
    expect(c1.extent).toBe("parent")

    expect(out.edges).toContainEqual(bodyEdge)
  })

  it("treats data.type='loop' even when node.type differs", () => {
    const lp: Node = {
      id: "L",
      type: "customLoop",
      position: { x: 0, y: 0 },
      data: { type: "loop", body_mode: "inline", body: { nodes: [plainNode("c")], edges: [] } },
    }
    const out = expandInlineLoopBodies([lp], [])
    const c = out.nodes.find((n) => n.id === "c") as Node & { parentId?: string }
    expect(c?.parentId).toBe("L")
  })
})

describe("collapseInlineLoopBodies", () => {
  it("packs children with parentId back into data.body", () => {
    const expandedLoop = loop("L", "inline")
    const child1 = { ...plainNode("c1"), parentId: "L", extent: "parent" as const }
    const child2 = { ...plainNode("c2"), parentId: "L", extent: "parent" as const }
    const bodyEdge = edge("be1", "c1", "c2")

    const out = collapseInlineLoopBodies(
      [expandedLoop, child1, child2],
      [bodyEdge],
    )

    expect(out.nodes).toHaveLength(1)
    const lp = out.nodes[0]
    const body = (lp.data as Record<string, unknown>).body as {
      nodes: Node[]
      edges: Edge[]
    }
    expect(body.nodes.map((n) => n.id)).toEqual(["c1", "c2"])
    // parentId/extent NAO devem ir pro snapshot.
    for (const n of body.nodes) {
      expect((n as Node & { parentId?: string }).parentId).toBeUndefined()
      expect((n as Node & { extent?: unknown }).extent).toBeUndefined()
    }
    expect(body.edges).toEqual([bodyEdge])
    expect(out.edges).toEqual([])
  })

  it("keeps boundary-crossing edges in the flat array", () => {
    const lp = loop("L", "inline")
    const child = { ...plainNode("c1"), parentId: "L", extent: "parent" as const }
    const outsider = plainNode("out")
    const crossing = edge("e-cross", "c1", "out")

    const out = collapseInlineLoopBodies([lp, child, outsider], [crossing])
    expect(out.edges).toEqual([crossing])
    const body = (out.nodes.find((n) => n.id === "L")!.data as Record<string, unknown>).body as {
      edges: Edge[]
    }
    expect(body.edges).toEqual([])
  })

  it("is a no-op when there are no inline loops", () => {
    const nodes = [plainNode("a"), plainNode("b")]
    const edges = [edge("e1", "a", "b")]
    const out = collapseInlineLoopBodies(nodes, edges)
    expect(out.nodes).toBe(nodes)
    expect(out.edges).toBe(edges)
  })

  it("round-trips through expand+collapse without loss", () => {
    const child = plainNode("c1", "http_request")
    const bodyEdge = edge("be1", "c1", "c1")
    const lp = loop("L", "inline", { nodes: [child], edges: [bodyEdge] })
    const expanded = expandInlineLoopBodies([lp], [])
    const collapsed = collapseInlineLoopBodies(expanded.nodes, expanded.edges)
    const lpOut = collapsed.nodes.find((n) => n.id === "L")!
    expect((lpOut.data as Record<string, unknown>).body).toEqual({
      nodes: [child],
      edges: [bodyEdge],
    })
  })
})
