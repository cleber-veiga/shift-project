import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ValueInput, isSingleChipTemplate } from "../ValueInput"
import { TransformsBar } from "../TransformsBar"
import { parseExprTokens } from "../ExpressionEditor"
import type { ParameterValue, TransformEntry } from "@/lib/workflow/parameter-value"
import { createFixed, createDynamic } from "@/lib/workflow/parameter-value"

// ── Mock ExpressionEditor so contentEditable doesn't block tests ──────────────
vi.mock("../ExpressionEditor", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../ExpressionEditor")>()
  return {
    ...actual,
    ExpressionEditor: ({
      template,
      onChange,
    }: {
      template: string
      onChange: (t: string) => void
      upstreamFields: unknown[]
      allowVariables: boolean
    }) => (
      <input
        data-testid="expr-editor"
        value={template}
        onChange={(e) => onChange(e.target.value)}
      />
    ),
  }
})

// ─── parseExprTokens (pure function, no DOM needed) ──────────────────────────

describe("parseExprTokens", () => {
  it("returns plain text segment", () => {
    expect(parseExprTokens("hello")).toEqual([{ type: "text", value: "hello" }])
  })

  it("returns a field token", () => {
    expect(parseExprTokens("{{NAME}}")).toEqual([{ type: "field", value: "NAME" }])
  })

  it("returns a sysvar token", () => {
    expect(parseExprTokens("$now")).toEqual([{ type: "sysvar", value: "$now" }])
  })

  it("parses mixed template correctly", () => {
    const result = parseExprTokens("Rua {{STREET}} em $now")
    expect(result).toEqual([
      { type: "text",   value: "Rua "    },
      { type: "field",  value: "STREET"  },
      { type: "text",   value: " em "    },
      { type: "sysvar", value: "$now"    },
    ])
  })

  it("handles empty string", () => {
    expect(parseExprTokens("")).toEqual([])
  })

  it("handles adjacent tokens", () => {
    const result = parseExprTokens("{{A}}{{B}}")
    expect(result).toEqual([
      { type: "field", value: "A" },
      { type: "field", value: "B" },
    ])
  })
})

// ─── ValueInput — mode toggle ─────────────────────────────────────────────────

describe("ValueInput — mode toggle", () => {
  it("renders fixed mode with a text input", () => {
    const onChange = vi.fn()
    render(<ValueInput value={createFixed("hello")} onChange={onChange} />)
    const input = screen.getByRole("textbox")
    expect(input).toHaveValue("hello")
    expect(screen.queryByTestId("expr-editor")).toBeNull()
  })

  it("renders dynamic mode with ExpressionEditor", () => {
    const onChange = vi.fn()
    // Multi-token template → not compact → renders ExpressionEditor
    render(<ValueInput value={createDynamic("{{X}} texto")} onChange={onChange} />)
    expect(screen.getByTestId("expr-editor")).toBeInTheDocument()
    expect(screen.queryByRole("textbox", { name: /valor/i })).toBeNull()
  })

  it("switches from fixed to dynamic when toggle clicked", async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<ValueInput value={createFixed("abc")} onChange={onChange} />)

    const toggle = screen.getByRole("button")
    await user.click(toggle)

    expect(onChange).toHaveBeenCalledOnce()
    const emitted = onChange.mock.calls[0][0] as ParameterValue
    expect(emitted.mode).toBe("dynamic")
  })

  it("switches from dynamic to fixed when toggle clicked", async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    // Multi-token → not compact → toggle title is "Dinâmico · clique para valor fixo"
    render(<ValueInput value={createDynamic("{{X}} texto")} onChange={onChange} />)

    const toggle = screen.getByRole("button", { name: /dinâmico/i })
    await user.click(toggle)

    expect(onChange).toHaveBeenCalledOnce()
    const emitted = onChange.mock.calls[0][0] as ParameterValue
    expect(emitted.mode).toBe("fixed")
  })

  it("emits valid ParameterValue on fixed text change", async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<ValueInput value={createFixed("")} onChange={onChange} />)

    const input = screen.getByRole("textbox")
    await user.type(input, "a")

    const last = onChange.mock.calls.at(-1)![0] as ParameterValue
    expect(last.mode).toBe("fixed")
    if (last.mode === "fixed") expect(last.value).toContain("a")
  })

  it("emits valid ParameterValue on template change", async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<ValueInput value={createDynamic("")} onChange={onChange} />)

    const editor = screen.getByTestId("expr-editor")
    await user.type(editor, "x")

    const last = onChange.mock.calls.at(-1)![0] as ParameterValue
    expect(last.mode).toBe("dynamic")
  })

  it("hides TransformsBar in fixed mode", () => {
    render(<ValueInput value={createFixed("v")} onChange={vi.fn()} />)
    expect(screen.queryByText("Maiúsculo")).toBeNull()
  })

  it("shows TransformsBar in dynamic mode", () => {
    // Multi-token → not compact → TransformsBar is visible
    render(<ValueInput value={createDynamic("{{X}} texto")} onChange={vi.fn()} />)
    expect(screen.getByText("Maiúsculo")).toBeInTheDocument()
  })

  it("hides TransformsBar when allowTransforms=false", () => {
    render(
      <ValueInput value={createDynamic("{{X}}")} onChange={vi.fn()} allowTransforms={false} />
    )
    expect(screen.queryByText("Maiúsculo")).toBeNull()
  })

  it("drag of field onto fixed input calls onChange with dynamic+chip", () => {
    const onChange = vi.fn()
    render(<ValueInput value={createFixed("")} onChange={onChange} />)

    const input = screen.getByRole("textbox")
    fireEvent.dragOver(input, {
      dataTransfer: { types: ["application/x-shift-field"] },
    })
    fireEvent.drop(input, {
      dataTransfer: {
        getData: (type: string) =>
          type === "application/x-shift-field" ? "NOME" : "",
      },
    })

    expect(onChange).toHaveBeenCalledOnce()
    const emitted = onChange.mock.calls[0][0] as ParameterValue
    expect(emitted.mode).toBe("dynamic")
    if (emitted.mode === "dynamic") expect(emitted.template).toBe("{{NOME}}")
  })
})

// ─── isSingleChipTemplate (pure helper) ──────────────────────────────────────

describe("isSingleChipTemplate", () => {
  it("returns true for single-chip dynamic with no transforms", () => {
    expect(isSingleChipTemplate(createDynamic("{{NOME}}"))).toBe(true)
  })

  it("returns false when template has text around chip", () => {
    expect(isSingleChipTemplate(createDynamic("Olá {{NOME}}"))).toBe(false)
  })

  it("returns false when template has two chips", () => {
    expect(isSingleChipTemplate(createDynamic("{{A}}{{B}}"))).toBe(false)
  })

  it("returns false when dynamic has transforms", () => {
    expect(isSingleChipTemplate(createDynamic("{{X}}", [{ kind: "upper" }]))).toBe(false)
  })

  it("returns false for fixed mode", () => {
    expect(isSingleChipTemplate(createFixed("{{X}}"))).toBe(false)
  })

  it("returns false for empty dynamic template", () => {
    expect(isSingleChipTemplate(createDynamic(""))).toBe(false)
  })
})

// ─── ValueInput — compact mode ────────────────────────────────────────────────

describe("ValueInput — compact mode", () => {
  it("renders chip pill (not ExpressionEditor) for single-chip template", () => {
    render(<ValueInput value={createDynamic("{{NOME}}")} onChange={vi.fn()} />)
    expect(screen.queryByTestId("expr-editor")).toBeNull()
    expect(screen.getByText("NOME")).toBeInTheDocument()
  })

  it("shows '+ transformação' button in compact mode", () => {
    render(<ValueInput value={createDynamic("{{NOME}}")} onChange={vi.fn()} />)
    expect(screen.getByText("transformação")).toBeInTheDocument()
  })

  it("hides '+ transformação' when allowTransforms=false", () => {
    render(
      <ValueInput value={createDynamic("{{NOME}}")} onChange={vi.fn()} allowTransforms={false} />
    )
    expect(screen.queryByText("transformação")).toBeNull()
  })

  it("clicking '+ transformação' reveals ExpressionEditor", async () => {
    const user = userEvent.setup()
    render(<ValueInput value={createDynamic("{{NOME}}")} onChange={vi.fn()} />)
    await user.click(screen.getByText("transformação"))
    expect(screen.getByTestId("expr-editor")).toBeInTheDocument()
  })

  it("clicking '+ transformação' shows TransformsBar", async () => {
    const user = userEvent.setup()
    render(<ValueInput value={createDynamic("{{NOME}}")} onChange={vi.fn()} />)
    await user.click(screen.getByText("transformação"))
    expect(screen.getByText("Maiúsculo")).toBeInTheDocument()
  })

  it("toggle in compact mode switches to fixed and emits fixed PV", async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<ValueInput value={createDynamic("{{NOME}}")} onChange={onChange} />)
    const toggle = screen.getByRole("button", { name: /campo linkado/i })
    await user.click(toggle)
    expect(onChange).toHaveBeenCalledOnce()
    const emitted = onChange.mock.calls[0][0] as ParameterValue
    expect(emitted.mode).toBe("fixed")
  })

  it("multi-token dynamic renders ExpressionEditor (not compact)", () => {
    render(<ValueInput value={createDynamic("{{A}} e {{B}}")} onChange={vi.fn()} />)
    expect(screen.getByTestId("expr-editor")).toBeInTheDocument()
    expect(screen.queryByText("transformação")).toBeNull()
  })

  it("dynamic with transforms renders ExpressionEditor (not compact)", () => {
    render(
      <ValueInput
        value={createDynamic("{{NOME}}", [{ kind: "upper" }])}
        onChange={vi.fn()}
      />
    )
    expect(screen.getByTestId("expr-editor")).toBeInTheDocument()
  })
})

// ─── TransformsBar ────────────────────────────────────────────────────────────

describe("TransformsBar", () => {
  const noTransforms: TransformEntry[] = []

  it("renders all transform chips", () => {
    render(<TransformsBar transforms={noTransforms} onChange={vi.fn()} />)
    expect(screen.getByText("Maiúsculo")).toBeInTheDocument()
    expect(screen.getByText("Minúsculo")).toBeInTheDocument()
    expect(screen.getByText("Sem espaços")).toBeInTheDocument()
    expect(screen.getByText("Somente dígitos")).toBeInTheDocument()
    expect(screen.getByText("Remover especiais")).toBeInTheDocument()
    expect(screen.getByText("Substituir")).toBeInTheDocument()
    expect(screen.getByText("Truncar")).toBeInTheDocument()
  })

  it("adds a transform on chip click", async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<TransformsBar transforms={noTransforms} onChange={onChange} />)
    await user.click(screen.getByText("Maiúsculo"))
    expect(onChange).toHaveBeenCalledWith([{ kind: "upper" }])
  })

  it("removes an active transform on chip click", async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    const active: TransformEntry[] = [{ kind: "upper" }]
    render(<TransformsBar transforms={active} onChange={onChange} />)
    await user.click(screen.getByText("Maiúsculo"))
    expect(onChange).toHaveBeenCalledWith([])
  })

  it("adds a parametrized transform with empty default args", async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<TransformsBar transforms={noTransforms} onChange={onChange} />)
    await user.click(screen.getByText("Substituir"))
    const emitted = onChange.mock.calls[0][0] as TransformEntry[]
    expect(emitted).toHaveLength(1)
    expect(emitted[0].kind).toBe("replace")
    expect(emitted[0].args).toBeDefined()
  })

  it("shows param inputs for active parametrized transform", () => {
    const active: TransformEntry[] = [{ kind: "replace", args: { old: "-", new: "" } }]
    render(<TransformsBar transforms={active} onChange={vi.fn()} />)
    expect(screen.getByPlaceholderText("texto a substituir")).toBeInTheDocument()
    expect(screen.getByPlaceholderText("vazio = remover")).toBeInTheDocument()
  })

  it("updates a transform param", async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    const active: TransformEntry[] = [{ kind: "replace", args: { old: "", new: "" } }]
    render(<TransformsBar transforms={active} onChange={onChange} />)

    const fromInput = screen.getByPlaceholderText("texto a substituir")
    await user.type(fromInput, "-")

    const last = onChange.mock.calls.at(-1)![0] as TransformEntry[]
    expect(last[0].args?.old).toBe("-")
  })

  it("preserves other transforms when toggling one", async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    const active: TransformEntry[] = [{ kind: "upper" }, { kind: "trim" }]
    render(<TransformsBar transforms={active} onChange={onChange} />)

    // Remove upper, trim should remain
    await user.click(screen.getByText("Maiúsculo"))
    const emitted = onChange.mock.calls[0][0] as TransformEntry[]
    expect(emitted).toEqual([{ kind: "trim" }])
  })

  it("truncate param input accepts a number", async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    const active: TransformEntry[] = [{ kind: "truncate", args: { length: 0 } }]
    render(<TransformsBar transforms={active} onChange={onChange} />)

    const input = screen.getByPlaceholderText("ex: 3")
    await user.type(input, "5")

    const last = onChange.mock.calls.at(-1)![0] as TransformEntry[]
    expect(Number(last[0].args?.length)).toBeGreaterThan(0)
  })
})
