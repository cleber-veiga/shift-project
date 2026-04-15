"use client"

import { useEffect, useState } from "react"
import CodeMirror, { type Extension } from "@uiw/react-codemirror"
import { sql } from "@codemirror/lang-sql"
import { githubLight, githubDark } from "@uiw/codemirror-theme-github"
import { useTheme } from "next-themes"
import { EditorView } from "@codemirror/view"

interface SqlEditorProps {
  value: string
  onChange: (value: string) => void
  onRun?: () => void
  placeholder?: string
  className?: string
  height?: string
}

const baseTheme = EditorView.theme({
  "&": {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSize: "13px",
  },
  ".cm-content": {
    padding: "10px 0",
  },
  ".cm-line": {
    padding: "0 12px",
  },
  ".cm-gutters": {
    borderRight: "1px solid hsl(var(--border))",
    paddingRight: "4px",
    minWidth: "36px",
  },
  ".cm-lineNumbers .cm-gutterElement": {
    padding: "0 6px 0 8px",
    minWidth: "28px",
  },
  "&.cm-focused": {
    outline: "none",
  },
})

export function SqlEditor({
  value,
  onChange,
  onRun,
  placeholder = "SELECT * FROM tabela LIMIT 100",
  className = "",
  height = "100%",
}: SqlEditorProps) {
  const { resolvedTheme } = useTheme()
  const [mounted, setMounted] = useState(false)

  useEffect(() => setMounted(true), [])

  const extensions: Extension[] = [
    sql(),
    baseTheme,
    EditorView.lineWrapping,
  ]

  if (onRun) {
    extensions.push(
      EditorView.domEventHandlers({
        keydown(e) {
          if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
            e.preventDefault()
            onRun()
          }
        },
      })
    )
  }

  if (!mounted) {
    return (
      <div
        className={`flex-1 w-full bg-background px-4 py-3 font-mono text-sm text-muted-foreground ${className}`}
        style={{ height }}
      >
        {placeholder}
      </div>
    )
  }

  return (
    <CodeMirror
      value={value}
      height={height}
      theme={resolvedTheme === "dark" ? githubDark : githubLight}
      extensions={extensions}
      onChange={onChange}
      placeholder={placeholder}
      basicSetup={{
        lineNumbers: true,
        foldGutter: false,
        dropCursor: false,
        allowMultipleSelections: false,
        indentOnInput: true,
        bracketMatching: true,
        closeBrackets: true,
        autocompletion: true,
        highlightActiveLine: true,
        highlightActiveLineGutter: true,
        syntaxHighlighting: true,
        searchKeymap: false,
      }}
      className={`h-full w-full overflow-auto ${className}`}
      style={{ height }}
    />
  )
}
