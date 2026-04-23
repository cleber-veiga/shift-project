/**
 * Render tests for WorkflowNode ghost (pending) appearance.
 *
 * Coverage:
 *  - ghost node has border-dashed and opacity-60 classes
 *  - ghost node renders the "IA" badge
 *  - non-ghost node does NOT have border-dashed / opacity-60
 *  - non-ghost node does NOT render the "IA" badge
 */

import { render, screen } from "@testing-library/react"
import { WorkflowNode } from "@/components/workflow/workflow-node"
import type { NodeProps } from "@xyflow/react"

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

vi.mock("@xyflow/react", () => ({
  Handle: () => null,
  Position: { Left: "left", Right: "right" },
  useReactFlow: () => ({
    deleteElements: vi.fn(),
    setNodes: vi.fn(),
    getNode: vi.fn(),
  }),
}))

vi.mock("@/lib/workflow/execution-context", () => ({
  useNodeExecution: () => null,
}))

vi.mock("@/lib/workflow/node-actions-context", () => ({
  useNodeActions: () => ({ onExecuteNode: vi.fn() }),
}))

vi.mock("@/lib/workflow/types", () => ({
  getNodeDefinition: () => ({
    type: "sql_script",
    label: "SQL Script",
    description: "Executa SQL",
    color: "blue",
    icon: "Database",
    category: "transform",
  }),
  NODE_REGISTRY: [],
}))

vi.mock("@/lib/workflow/node-icons", () => ({
  getNodeIcon: () => () => <span data-testid="node-icon" />,
}))

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function makeProps(data: Record<string, unknown>): NodeProps {
  return {
    id: "test-node",
    type: "sql_script",
    data,
    selected: false,
    dragging: false,
    isConnectable: true,
    zIndex: 0,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
    width: 240,
    height: 100,
  } as unknown as NodeProps
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("WorkflowNode — ghost (pending) state", () => {
  it("ghost node has border-dashed class when __pending is true", () => {
    const { container } = render(<WorkflowNode {...makeProps({ __pending: true })} />)
    const root = container.firstElementChild as HTMLElement
    expect(root.className).toContain("border-dashed")
  })

  it("ghost node has opacity-60 class when __pending is true", () => {
    const { container } = render(<WorkflowNode {...makeProps({ __pending: true })} />)
    const root = container.firstElementChild as HTMLElement
    expect(root.className).toContain("opacity-60")
  })

  it("ghost node renders the IA badge", () => {
    render(<WorkflowNode {...makeProps({ __pending: true })} />)
    expect(screen.getByText("IA")).toBeInTheDocument()
  })

  it("normal node does NOT have border-dashed when __pending is absent", () => {
    const { container } = render(<WorkflowNode {...makeProps({ query: "SELECT 1" })} />)
    const root = container.firstElementChild as HTMLElement
    expect(root.className).not.toContain("border-dashed")
  })

  it("normal node does NOT have opacity-60 when __pending is absent", () => {
    const { container } = render(<WorkflowNode {...makeProps({ query: "SELECT 1" })} />)
    const root = container.firstElementChild as HTMLElement
    expect(root.className).not.toContain("opacity-60")
  })

  it("normal node does NOT render the IA badge", () => {
    render(<WorkflowNode {...makeProps({ query: "SELECT 1" })} />)
    expect(screen.queryByText("IA")).not.toBeInTheDocument()
  })

  it("__pending: false behaves like non-ghost", () => {
    const { container } = render(<WorkflowNode {...makeProps({ __pending: false })} />)
    const root = container.firstElementChild as HTMLElement
    expect(root.className).not.toContain("border-dashed")
    expect(screen.queryByText("IA")).not.toBeInTheDocument()
  })
})
