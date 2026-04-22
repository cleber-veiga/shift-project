/**
 * Integration tests — ExpressionEditor is NOT mocked.
 *
 * Unlike ValueInput.test.tsx (which replaces ExpressionEditor with a trivial
 * <input>), these tests exercise the real contentEditable implementation.
 *
 * jsdom limitations and workarounds:
 *
 * 1. Selection / caret placement
 *    jsdom's element.focus() does NOT place a caret inside contentEditable
 *    elements — getSelection().rangeCount stays 0 after focus().
 *    insertAtCursor() guards on rangeCount > 0 and returns early when it's 0.
 *    Fix: call placeCaretAt(el) to manually add a Range before any test that
 *    exercises the quick-insert bar or drop-onto-editor path.
 *
 * 2. DataTransfer
 *    jsdom does not implement a real DataTransfer constructor, so
 *    `new DataTransfer()` throws in fireEvent synthetic props.
 *    Fix: pass plain objects { getData(type), types } directly.
 *
 * 3. chip DOM access
 *    Chips are created imperatively by renderToDOM() (not via React render),
 *    so Testing Library's role/text queries work on them, but the most
 *    reliable selector is `document.querySelector('[data-token="{{X}}"]')`.
 */

import { describe, it, expect, vi, afterEach } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ValueInput } from "../ValueInput"
import { ExpressionEditor } from "../ExpressionEditor"
import type { ParameterValue } from "@/lib/workflow/parameter-value"

afterEach(() => {
  // Testing Library auto-cleanup removes the DOM; clear selection too.
  window.getSelection()?.removeAllRanges()
})

/**
 * Places a collapsed Range at the start of `el` so that insertAtCursor()
 * passes its `sel.rangeCount > 0` guard. Must be called after render().
 */
function placeCaretAt(el: Element) {
  const range = document.createRange()
  range.selectNodeContents(el)
  range.collapse(true)
  const sel = window.getSelection()!
  sel.removeAllRanges()
  sel.addRange(range)
}

// ─── Chip presence in real DOM ────────────────────────────────────────────────

describe("ExpressionEditor — chips rendered in DOM", () => {
  it("mounts and creates chip span via renderToDOM", () => {
    render(
      <ExpressionEditor template="{{NOME}}" onChange={vi.fn()} upstreamFields={[]} />
    )
    const chip = document.querySelector('[data-token="{{NOME}}"]') as HTMLElement
    expect(chip).not.toBeNull()
    expect(chip.textContent).toBe("NOME")
  })

  it("chip has tabIndex=0 and descriptive aria-label for keyboard navigation", () => {
    render(
      <ExpressionEditor template="{{ESTAB}}" onChange={vi.fn()} upstreamFields={[]} />
    )
    const chip = document.querySelector('[data-token="{{ESTAB}}"]') as HTMLElement
    expect(chip.tabIndex).toBe(0)
    expect(chip.getAttribute("aria-label")).toBe(
      "Campo ESTAB — pressione Delete para remover"
    )
  })

  it("vars.X chip gets 'Variável X' aria-label", () => {
    render(
      <ExpressionEditor
        template="{{vars.Cidade}}"
        onChange={vi.fn()}
        upstreamFields={[]}
      />
    )
    const chip = document.querySelector('[data-token="{{vars.Cidade}}"]') as HTMLElement
    expect(chip.getAttribute("aria-label")).toBe(
      "Variável Cidade — pressione Delete para remover"
    )
  })

  it("contentEditable div has role=textbox and aria-multiline", () => {
    render(
      <ExpressionEditor template="" onChange={vi.fn()} upstreamFields={[]} />
    )
    const editor = screen.getByRole("textbox")
    expect(editor).toHaveAttribute("aria-multiline", "true")
  })
})

// ─── Scenario 1: compact single-chip display ──────────────────────────────────

describe("ValueInput integration — scenario 1: compact single-chip display", () => {
  it("single-chip template renders chip pill and hides TransformsBar by default", () => {
    render(
      <ValueInput
        value={{ mode: "dynamic", template: "{{NOME}}", transforms: [] }}
        onChange={vi.fn()}
      />
    )
    // Chip pill shows the field name
    expect(screen.getByText("NOME")).toBeInTheDocument()
    // TransformsBar is NOT shown in compact mode
    expect(screen.queryByText("Maiúsculo")).toBeNull()
    // Toggle button title signals "Campo linkado" (linked-field / dynamic mode)
    expect(screen.getByTitle(/campo linkado/i)).toBeInTheDocument()
  })
})

// ─── Scenario 2: drop on fixed input promotes to dynamic ─────────────────────

describe("ValueInput integration — scenario 2: drop field onto fixed input", () => {
  it("drop of x-shift-field promotes fixed to dynamic with {{ESTAB}} template", () => {
    const onChange = vi.fn()
    render(<ValueInput value={{ mode: "fixed", value: "" }} onChange={onChange} />)

    const input = screen.getByRole("textbox")
    // DataTransfer workaround: plain objects satisfy fireEvent's duck-typing
    fireEvent.dragOver(input, {
      dataTransfer: { types: ["application/x-shift-field"] },
    })
    fireEvent.drop(input, {
      dataTransfer: {
        getData: (type: string) =>
          type === "application/x-shift-field" ? "ESTAB" : "",
      },
    })

    expect(onChange).toHaveBeenCalledOnce()
    const pv = onChange.mock.calls[0][0] as ParameterValue
    expect(pv.mode).toBe("dynamic")
    if (pv.mode === "dynamic") expect(pv.template).toBe("{{ESTAB}}")
  })
})

// ─── Scenario 3: quick-insert bar button ──────────────────────────────────────

describe("ExpressionEditor integration — scenario 3: quick-insert bar", () => {
  it("clicking a field button inserts the chip token via onChange", () => {
    const onChange = vi.fn()
    render(
      <ExpressionEditor
        template=""
        onChange={onChange}
        upstreamFields={[{ name: "CIDADE" }, { name: "ESTAB" }]}
      />
    )

    // jsdom workaround: manually place a caret so insertAtCursor() doesn't
    // bail out at the `sel.rangeCount === 0` guard.
    const editor = screen.getByRole("textbox")
    placeCaretAt(editor)

    // The quick-insert buttons have aria-label "Inserir campo <NAME>"
    // (added in the a11y pass on ExpressionEditor).
    fireEvent.click(screen.getByRole("button", { name: "Inserir campo CIDADE" }))

    expect(onChange).toHaveBeenCalled()
    const template = onChange.mock.calls.at(-1)![0] as string
    expect(template).toContain("{{CIDADE}}")
  })

  it("quick-insert button for second field works the same way", () => {
    const onChange = vi.fn()
    render(
      <ExpressionEditor
        template=""
        onChange={onChange}
        upstreamFields={[{ name: "UF" }]}
      />
    )

    placeCaretAt(screen.getByRole("textbox"))
    fireEvent.click(screen.getByRole("button", { name: "Inserir campo UF" }))

    expect(onChange).toHaveBeenCalled()
    const template = onChange.mock.calls.at(-1)![0] as string
    expect(template).toContain("{{UF}}")
  })
})

// ─── Scenario 4: chip removal via Delete key ─────────────────────────────────

describe("ExpressionEditor integration — scenario 4: chip deletion via keyboard", () => {
  it("Delete on a focused chip removes it and calls onChange without the chip token", () => {
    const onChange = vi.fn()
    render(
      <ExpressionEditor
        template="{{NOME}}"
        onChange={onChange}
        upstreamFields={[]}
      />
    )

    // renderToDOM creates the chip imperatively; find it by data-token.
    const chip = document.querySelector('[data-token="{{NOME}}"]') as HTMLElement
    expect(chip).not.toBeNull()

    // Focus the chip (tabIndex=0 makes it focusable).
    // The Delete keyDown bubbles from the chip to the parent contentEditable div
    // where React's onKeyDown handler checks e.target.dataset.token.
    chip.focus()
    fireEvent.keyDown(chip, { key: "Delete" })

    expect(onChange).toHaveBeenCalled()
    const emitted = onChange.mock.calls.at(-1)![0] as string
    expect(emitted).not.toContain("{{NOME}}")
  })

  it("Backspace on a focused chip also removes it", () => {
    const onChange = vi.fn()
    render(
      <ExpressionEditor
        template="{{CPF}}"
        onChange={onChange}
        upstreamFields={[]}
      />
    )

    const chip = document.querySelector('[data-token="{{CPF}}"]') as HTMLElement
    chip.focus()
    fireEvent.keyDown(chip, { key: "Backspace" })

    expect(onChange).toHaveBeenCalled()
    const emitted = onChange.mock.calls.at(-1)![0] as string
    expect(emitted).not.toContain("{{CPF}}")
  })

  it("Delete on the editor div itself (not a chip) does not call onChange", () => {
    const onChange = vi.fn()
    render(
      <ExpressionEditor
        template="{{NOME}}"
        onChange={onChange}
        upstreamFields={[]}
      />
    )

    // Firing Delete on the editor root (no dataset.token) should not trigger
    // the chip-removal branch.
    const editor = screen.getByRole("textbox")
    fireEvent.keyDown(editor, { key: "Delete" })

    // The Backspace branch runs when selection is at text boundary;
    // with no selection set up in jsdom, it should also be a no-op.
    expect(onChange).not.toHaveBeenCalled()
  })
})

// ─── Scenario 5: add transform from compact mode ─────────────────────────────

describe("ValueInput integration — scenario 5: add transform from compact mode", () => {
  it("'+ transformação' expands compact chip; 'Maiúsculo' emits PV with upper transform", async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(
      <ValueInput
        value={{ mode: "dynamic", template: "{{NOME}}", transforms: [] }}
        onChange={onChange}
      />
    )

    // Compact mode is shown (chip pill + expand button). Expand it.
    await user.click(screen.getByText("transformação"))

    // TransformsBar is now visible after expansion.
    expect(screen.getByText("Maiúsculo")).toBeInTheDocument()

    // Click Maiúsculo — triggers handleTransformsChange([{ kind: "upper" }])
    await user.click(screen.getByText("Maiúsculo"))

    // Find the onChange call that carries the transform.
    const pvCalls = onChange.mock.calls.map((c) => c[0] as ParameterValue)
    const withTransform = pvCalls.find(
      (pv) => pv.mode === "dynamic" && (pv.transforms ?? []).length > 0
    )
    expect(withTransform).toBeDefined()
    if (withTransform?.mode === "dynamic") {
      expect(withTransform.transforms).toEqual([{ kind: "upper" }])
      // Template must be preserved from the original compact value.
      expect(withTransform.template).toBe("{{NOME}}")
    }
  })
})
