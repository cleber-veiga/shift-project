"use client"

import dynamic from "next/dynamic"
import { use, useCallback, useEffect, useMemo, useState, useRef } from "react"
import { useRouter } from "next/navigation"
import {
  ArrowLeft,
  Bookmark,
  ChevronDown,
  ChevronRight,
  Clock,
  Database,
  FlaskConical,
  MessageSquare,
  Play,
  RefreshCw,
  Save,
  Table2,
  Columns3,
  Copy,
  Check,
  Search,
  Trash2,
  Pencil,
  X,
} from "lucide-react"
import {
  getConnection,
  getConnectionSchema,
  executePlaygroundQuery,
  listSavedQueries,
  createSavedQuery,
  updateSavedQuery,
  deleteSavedQuery,
  type Connection,
  type SchemaTable,
  type PlaygroundQueryResponse,
  type SavedQuery,
} from "@/lib/auth"
import { useToast } from "@/lib/context/toast-context"
import { useDashboard } from "@/lib/context/dashboard-context"
import { useRegisterAIContext } from "@/lib/context/ai-context"
import { MorphLoader } from "@/components/ui/morph-loader"
import { SqlEditor } from "@/components/ui/sql-editor"
import { Tooltip } from "@/components/ui/tooltip"

const ChatPanel = dynamic(
  () => import("@/components/playground/chat-panel").then((m) => m.ChatPanel),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full w-full items-center justify-center p-4">
        <div className="h-2 w-24 animate-pulse rounded bg-muted" />
      </div>
    ),
  },
)

interface PageProps {
  params: Promise<{ connectionId: string }>
}

// ─── Schema Sidebar ──────────────────────────────────────────────────────────

function SchemaTableItem({ table }: { table: SchemaTable }) {
  const [open, setOpen] = useState(false)

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-muted"
      >
        {open ? (
          <ChevronDown className="size-3 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-3 shrink-0 text-muted-foreground" />
        )}
        <Table2 className="size-3.5 shrink-0 text-primary" />
        <span className="truncate font-medium text-foreground">{table.name}</span>
        <span className="ml-auto text-[10px] text-muted-foreground">{table.columns.length}</span>
      </button>

      {open && (
        <div className="ml-4 border-l border-border pl-2">
          {table.columns.map((col) => (
            <div
              key={col.name}
              className="flex items-center gap-1.5 px-2 py-1 text-[11px]"
            >
              <Columns3 className="size-3 shrink-0 text-muted-foreground/60" />
              <span className="truncate text-foreground">{col.name}</span>
              <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                {col.type}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function SchemaGroup({ schemaName, tables }: { schemaName: string | null; tables: SchemaTable[] }) {
  const [open, setOpen] = useState(true)
  const label = schemaName ?? "PADRÃO"

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left transition-colors hover:bg-muted"
      >
        {open ? (
          <ChevronDown className="size-3 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-3 shrink-0 text-muted-foreground" />
        )}
        <Database className="size-3.5 shrink-0 text-amber-500" />
        <span className="truncate text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {label}
        </span>
        <span className="ml-auto text-[10px] text-muted-foreground">{tables.length}</span>
      </button>
      {open && (
        <div className="ml-3 border-l border-border pl-1">
          {tables.map((t) => (
            <SchemaTableItem key={`${t.schema ?? ""}__${t.name}`} table={t} />
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Results Table ──────────────────────────────────────────────────────────

const COL_WIDTH = 160
const ROW_NUM_WIDTH = 48

function ResultsTable({ data }: { data: PlaygroundQueryResponse }) {
  const totalWidth = ROW_NUM_WIDTH + data.columns.length * COL_WIDTH

  return (
    <div className="h-full overflow-auto text-xs">
      <table
        className="border-collapse"
        style={{ width: totalWidth, tableLayout: "fixed" }}
      >
        <colgroup>
          <col style={{ width: ROW_NUM_WIDTH }} />
          {data.columns.map((col) => (
            <col key={col} style={{ width: COL_WIDTH }} />
          ))}
        </colgroup>
        <thead className="sticky top-0 z-20">
          <tr className="border-b border-border bg-muted">
            <th className="sticky left-0 z-30 bg-muted px-3 py-2 text-left text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              #
            </th>
            {data.columns.map((col) => (
              <th
                key={col}
                className="overflow-hidden truncate whitespace-nowrap px-3 py-2 text-left text-[10px] font-bold uppercase tracking-wider text-muted-foreground"
                title={col}
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {data.rows.map((row, i) => (
            <tr key={i} className="transition-colors hover:bg-muted/20">
              <td className="sticky left-0 z-10 bg-background px-3 py-1.5 text-muted-foreground tabular-nums">
                {i + 1}
              </td>
              {row.map((cell, j) => (
                <td
                  key={j}
                  className="overflow-hidden truncate whitespace-nowrap px-3 py-1.5 text-foreground"
                  title={cell === null ? "NULL" : String(cell)}
                >
                  {cell === null ? (
                    <span className="italic text-muted-foreground/50">NULL</span>
                  ) : (
                    String(cell)
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── Resizable Panels ────────────────────────────────────────────────────────

function useResizable(
  initial: number,
  min: number,
  max: number,
  axis: "x" | "y" | "x-inv",
) {
  const [size, setSize] = useState(initial)
  const dragging = useRef(false)
  const startPos = useRef(0)
  const startSize = useRef(0)

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragging.current = true
    startPos.current = axis === "y" ? e.clientY : e.clientX
    startSize.current = size
    document.body.style.cursor = axis === "y" ? "row-resize" : "col-resize"
    document.body.style.userSelect = "none"

    function onMouseMove(ev: MouseEvent) {
      if (!dragging.current) return
      const pos = axis === "y" ? ev.clientY : ev.clientX
      const delta = pos - startPos.current
      const newSize = axis === "x-inv"
        ? startSize.current - delta
        : startSize.current + delta
      setSize(Math.max(min, Math.min(newSize, max)))
    }

    function onMouseUp() {
      dragging.current = false
      document.body.style.cursor = ""
      document.body.style.userSelect = ""
      document.removeEventListener("mousemove", onMouseMove)
      document.removeEventListener("mouseup", onMouseUp)
    }

    document.addEventListener("mousemove", onMouseMove)
    document.addEventListener("mouseup", onMouseUp)
  }, [size, min, max, axis])

  return { size, onMouseDown }
}


// ─── Main Page ────────────────────────────────────────────────────────────────

export default function PlaygroundPage({ params }: PageProps) {
  const { connectionId } = use(params)
  const router = useRouter()
  const toast = useToast()
  const { selectedWorkspace, selectedProject } = useDashboard()

  const [connection, setConnection] = useState<Connection | null>(null)
  const [tables, setTables] = useState<SchemaTable[]>([])
  const [schemaLoading, setSchemaLoading] = useState(true)

  const aiContext = useMemo(() => {
    if (!connection) return null
    return {
      section: "playground" as const,
      workspaceId: selectedWorkspace?.id ?? null,
      workspaceName: selectedWorkspace?.name ?? null,
      projectId: selectedProject?.id ?? null,
      projectName: selectedProject?.name ?? null,
      userRole: {
        workspace: (selectedWorkspace?.my_role ?? null) as "VIEWER" | "CONSULTANT" | "MANAGER" | null,
        project: null,
      },
      connection: {
        id: connection.id,
        name: connection.name,
        type: connection.type,
      },
    }
  }, [connection, selectedWorkspace, selectedProject])

  useRegisterAIContext(aiContext)
  const [schemaRefreshing, setSchemaRefreshing] = useState(false)
  const [schemaUpdatedAt, setSchemaUpdatedAt] = useState<string | null>(null)
  const [schemaCached, setSchemaCached] = useState(false)
  const [schemaSearch, setSchemaSearch] = useState("")

  const [query, setQuery] = useState("")
  const [executing, setExecuting] = useState(false)
  const [result, setResult] = useState<PlaygroundQueryResponse | null>(null)
  const [queryError, setQueryError] = useState("")
  const [copied, setCopied] = useState(false)

  const [chatOpen, setChatOpen] = useState(false)
  const [sidebarTab, setSidebarTab] = useState<"schema" | "saved">("schema")

  // Saved queries
  const [savedQueries, setSavedQueries] = useState<SavedQuery[]>([])
  const [savedLoading, setSavedLoading] = useState(false)
  const [saveDialogOpen, setSaveDialogOpen] = useState(false)
  const [saveName, setSaveName] = useState("")
  const [saveDesc, setSaveDesc] = useState("")
  const [saving, setSaving] = useState(false)

  // Edit saved query
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [editingQuery, setEditingQuery] = useState<SavedQuery | null>(null)
  const [editName, setEditName] = useState("")
  const [editDesc, setEditDesc] = useState("")
  const [editSql, setEditSql] = useState("")
  const [editSaving, setEditSaving] = useState(false)

  const { size: sidebarWidth, onMouseDown: onSidebarDrag } = useResizable(224, 140, 480, "x")
  const { size: editorHeight, onMouseDown: onEditorDrag } = useResizable(220, 80, 600, "y")
  const { size: chatWidth, onMouseDown: onChatDrag } = useResizable(380, 280, 600, "x-inv")

  // ── Load connection + schema ──
  useEffect(() => {
    let active = true
    async function load() {
      try {
        const [conn, schema] = await Promise.all([
          getConnection(connectionId),
          getConnectionSchema(connectionId),
        ])
        if (!active) return
        setConnection(conn)
        setTables(schema.tables)
        setSchemaUpdatedAt(schema.updated_at)
        setSchemaCached(schema.is_cached)
      } catch (err) {
        if (!active) return
        toast.error("Erro ao carregar", err instanceof Error ? err.message : "Falha ao carregar conexão.")
      } finally {
        if (active) setSchemaLoading(false)
      }
    }
    void load()
    return () => { active = false }
  }, [connectionId, toast])

  // ── Force refresh schema ──
  const handleRefreshSchema = useCallback(async () => {
    setSchemaRefreshing(true)
    try {
      const schema = await getConnectionSchema(connectionId, true)
      setTables(schema.tables)
      setSchemaUpdatedAt(schema.updated_at)
      setSchemaCached(false)
      toast.success("Schema atualizado", `${schema.tables.length} tabelas carregadas do banco.`)
    } catch (err) {
      toast.error("Erro ao atualizar schema", err instanceof Error ? err.message : "Falha ao buscar schema.")
    } finally {
      setSchemaRefreshing(false)
    }
  }, [connectionId, toast])

  const filteredTables = tables.filter((t) => {
    if (!schemaSearch.trim()) return true
    const q = schemaSearch.toLowerCase()
    return (
      t.name.toLowerCase().includes(q) ||
      (t.schema?.toLowerCase() ?? "").includes(q)
    )
  })

  // Agrupa por schema — só quando há mais de um schema distinto
  const schemaGroups = useMemo(() => {
    const keys = [...new Set(filteredTables.map((t) => t.schema ?? null))]
    if (keys.length <= 1) return null // sem agrupamento: lista plana
    const map = new Map<string | null, SchemaTable[]>()
    for (const k of keys) map.set(k, [])
    for (const t of filteredTables) map.get(t.schema ?? null)!.push(t)
    return map
  }, [filteredTables])

  // ── Load saved queries ──
  const loadSavedQueries = useCallback(async () => {
    setSavedLoading(true)
    try {
      const { items } = await listSavedQueries(connectionId, { size: 200 })
      setSavedQueries(items)
    } catch {
      // silencioso — conexão pode não ter player vinculado
      setSavedQueries([])
    } finally {
      setSavedLoading(false)
    }
  }, [connectionId])

  useEffect(() => {
    if (sidebarTab === "saved" && savedQueries.length === 0) {
      void loadSavedQueries()
    }
  }, [sidebarTab, savedQueries.length, loadSavedQueries])

  // ── Save current query ──
  const handleSaveQuery = useCallback(async () => {
    if (!saveName.trim() || !query.trim()) return
    setSaving(true)
    try {
      await createSavedQuery(connectionId, {
        name: saveName.trim(),
        description: saveDesc.trim() || undefined,
        query: query,
      })
      toast.success("Consulta salva", `"${saveName.trim()}" salva com sucesso.`)
      setSaveDialogOpen(false)
      setSaveName("")
      setSaveDesc("")
      // Reload list
      void loadSavedQueries()
    } catch (err) {
      toast.error("Erro ao salvar", err instanceof Error ? err.message : "Falha ao salvar consulta.")
    } finally {
      setSaving(false)
    }
  }, [connectionId, query, saveName, saveDesc, toast, loadSavedQueries])

  // ── Edit saved query ──
  function handleOpenEdit(sq: SavedQuery) {
    setEditingQuery(sq)
    setEditName(sq.name)
    setEditDesc(sq.description ?? "")
    setEditSql(sq.query)
    setEditDialogOpen(true)
  }

  const handleUpdateQuery = useCallback(async () => {
    if (!editingQuery || !editName.trim() || !editSql.trim()) return
    setEditSaving(true)
    try {
      const updated = await updateSavedQuery(editingQuery.id, {
        name: editName.trim(),
        description: editDesc.trim() || undefined,
        query: editSql.trim(),
      })
      setSavedQueries((prev) => prev.map((q) => q.id === updated.id ? updated : q))
      toast.success("Consulta atualizada", `"${updated.name}" atualizada com sucesso.`)
      setEditDialogOpen(false)
      setEditingQuery(null)
    } catch (err) {
      toast.error("Erro ao atualizar", err instanceof Error ? err.message : "Falha ao atualizar consulta.")
    } finally {
      setEditSaving(false)
    }
  }, [editingQuery, editName, editDesc, editSql, toast])

  // ── Delete saved query ──
  const handleDeleteSaved = useCallback(async (sq: SavedQuery) => {
    try {
      await deleteSavedQuery(sq.id)
      setSavedQueries((prev) => prev.filter((q) => q.id !== sq.id))
      toast.success("Removida", `"${sq.name}" foi excluída.`)
    } catch (err) {
      toast.error("Erro ao excluir", err instanceof Error ? err.message : "Falha ao excluir consulta.")
    }
  }, [toast])

  // ── Load saved query into editor ──
  function handleLoadSaved(sq: SavedQuery) {
    setQuery(sq.query)
    toast.info("Consulta carregada", `"${sq.name}" carregada no editor.`)
  }

  // ── Execute query ──
  const handleRun = useCallback(async () => {
    if (!query.trim()) return
    setExecuting(true)
    setQueryError("")
    setResult(null)
    try {
      const res = await executePlaygroundQuery(connectionId, query)
      setResult(res)
      if (res.truncated) {
        toast.warning("Resultado truncado", `Exibindo ${res.row_count} de mais linhas disponíveis.`)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erro ao executar consulta."
      setQueryError(msg)
    } finally {
      setExecuting(false)
    }
  }, [connectionId, query, toast])

  function handleCopyError() {
    void navigator.clipboard.writeText(queryError)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (schemaLoading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <MorphLoader className="size-8" />
      </div>
    )
  }

  return (
    <div className="flex h-[calc(100vh-3.5rem)] w-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-border px-4 py-2">
        <Tooltip text="Voltar" side="bottom">
          <button
            type="button"
            onClick={() => router.back()}
            className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <ArrowLeft className="size-4" />
          </button>
        </Tooltip>

        <div className="flex items-center gap-2">
          <FlaskConical className="size-4 text-primary" />
          <h1 className="text-sm font-semibold text-foreground">Playground</h1>
        </div>

        {connection && (
          <div className="flex items-center gap-2 rounded-md border border-border bg-muted/30 px-2.5 py-1">
            <Database className="size-3.5 text-muted-foreground" />
            <span className="text-xs font-medium text-foreground">{connection.name}</span>
            <span className="text-[10px] text-muted-foreground">
              {connection.type.toUpperCase()} — {connection.host}:{connection.port}
            </span>
          </div>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Chat toggle */}
        <Tooltip text={chatOpen ? "Fechar assistente" : "Assistente SQL"} side="bottom">
          <button
            type="button"
            onClick={() => setChatOpen(!chatOpen)}
            className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors ${
              chatOpen
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            }`}
          >
            <MessageSquare className="size-4" />
            <span className="hidden sm:inline">Assistente</span>
          </button>
        </Tooltip>
      </div>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden min-w-0 min-h-0">
        {/* Sidebar */}
        <div className="flex shrink-0 flex-col bg-card" style={{ width: sidebarWidth }}>
          {/* Tabs */}
          <div className="flex border-b border-border">
            <button
              type="button"
              onClick={() => setSidebarTab("schema")}
              className={`flex-1 px-3 py-2 text-[10px] font-bold uppercase tracking-wider transition-colors ${
                sidebarTab === "schema"
                  ? "border-b-2 border-primary text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Schema
            </button>
            <button
              type="button"
              onClick={() => setSidebarTab("saved")}
              className={`flex-1 px-3 py-2 text-[10px] font-bold uppercase tracking-wider transition-colors ${
                sidebarTab === "saved"
                  ? "border-b-2 border-primary text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Salvos
              {savedQueries.length > 0 && (
                <span className="ml-1 text-[9px] font-normal">({savedQueries.length})</span>
              )}
            </button>
          </div>

          {sidebarTab === "schema" ? (
            <>
              {/* Schema filter + refresh */}
              <div className="border-b border-border px-3 py-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5" />
                </div>
                <div className="mt-1 flex items-center gap-1">
                  <input
                    type="text"
                    value={schemaSearch}
                    onChange={(e) => setSchemaSearch(e.target.value)}
                    placeholder="Filtrar tabelas..."
                    className="h-7 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-1 focus:ring-ring/20"
                  />
                  <Tooltip text="Atualizar schema" side="bottom">
                    <button
                      type="button"
                      onClick={() => void handleRefreshSchema()}
                      disabled={schemaRefreshing}
                      className="flex size-7 shrink-0 items-center justify-center rounded-md border border-input bg-background text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
                    >
                      <RefreshCw className={`size-3.5 ${schemaRefreshing ? "animate-spin" : ""}`} />
                    </button>
                  </Tooltip>
                </div>
              </div>
              {/* Schema table list */}
              <div className="flex-1 overflow-y-auto p-1.5">
                {filteredTables.length === 0 ? (
                  <p className="px-2 py-4 text-center text-[11px] text-muted-foreground">
                    {tables.length === 0 ? "Nenhuma tabela encontrada" : "Nenhum resultado"}
                  </p>
                ) : schemaGroups ? (
                  [...schemaGroups.entries()].map(([schema, schemaTables]) => (
                    <SchemaGroup key={schema ?? "__default__"} schemaName={schema} tables={schemaTables} />
                  ))
                ) : (
                  filteredTables.map((table) => (
                    <SchemaTableItem key={`${table.schema ?? ""}__${table.name}`} table={table} />
                  ))
                )}
              </div>
              {/* Schema footer */}
              <div className="border-t border-border px-3 py-1.5">
                <p className="text-[11px] text-muted-foreground">
                  {tables.length} tabela{tables.length !== 1 ? "s" : ""}
                </p>
                {schemaUpdatedAt && (
                  <p className="mt-0.5 text-[10px] text-muted-foreground/60">
                    Atualizado em{" "}
                    {new Date(schemaUpdatedAt).toLocaleDateString("pt-BR", {
                      day: "2-digit",
                      month: "2-digit",
                      year: "numeric",
                    })}
                  </p>
                )}
              </div>
            </>
          ) : (
            <>
              {/* Saved queries list */}
              <div className="flex-1 overflow-y-auto p-1.5">
                {savedLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <MorphLoader className="size-5" />
                  </div>
                ) : !connection?.player_id ? (
                  <div className="px-2 py-6 text-center">
                    <Bookmark className="mx-auto size-8 text-muted-foreground/30" />
                    <p className="mt-2 text-[11px] text-muted-foreground">
                      Vincule um sistema a esta conexão para salvar consultas.
                    </p>
                  </div>
                ) : savedQueries.length === 0 ? (
                  <div className="px-2 py-6 text-center">
                    <Bookmark className="mx-auto size-8 text-muted-foreground/30" />
                    <p className="mt-2 text-[11px] text-muted-foreground">
                      Nenhuma consulta salva ainda.
                    </p>
                    <p className="mt-1 text-[10px] text-muted-foreground/60">
                      Use o botão Salvar na barra de ferramentas.
                    </p>
                  </div>
                ) : (
                  savedQueries.map((sq) => (
                    <div
                      key={sq.id}
                      className="group rounded-md px-2 py-2 transition-colors hover:bg-muted/50"
                    >
                      <div className="flex items-start justify-between gap-1">
                        <button
                          type="button"
                          onClick={() => handleLoadSaved(sq)}
                          className="min-w-0 text-left"
                        >
                          <p className="truncate text-xs font-medium text-foreground">
                            {sq.name}
                          </p>
                          {sq.description && (
                            <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
                              {sq.description}
                            </p>
                          )}
                        </button>
                        <div className="flex shrink-0 items-center gap-0.5">
                          <button
                            type="button"
                            onClick={() => handleOpenEdit(sq)}
                            className="rounded p-1 text-muted-foreground/0 transition-colors group-hover:text-muted-foreground/70 hover:!text-foreground"
                          >
                            <Pencil className="size-3" />
                          </button>
                          <button
                            type="button"
                            onClick={() => void handleDeleteSaved(sq)}
                            className="rounded p-1 text-muted-foreground/0 transition-colors group-hover:text-destructive/70 hover:!text-destructive"
                          >
                            <Trash2 className="size-3" />
                          </button>
                        </div>
                      </div>
                      <p className="mt-1 line-clamp-2 font-mono text-[10px] text-muted-foreground/70">
                        {sq.query}
                      </p>
                    </div>
                  ))
                )}
              </div>
              {/* Saved queries footer */}
              <div className="border-t border-border px-3 py-1.5">
                <button
                  type="button"
                  onClick={() => void loadSavedQueries()}
                  className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
                >
                  <RefreshCw className="mr-1 inline size-3" />
                  Atualizar lista
                </button>
              </div>
            </>
          )}
        </div>

        {/* Sidebar Drag Handle (vertical) */}
        <div
          onMouseDown={onSidebarDrag}
          className="group flex w-1.5 shrink-0 cursor-col-resize items-center justify-center border-x border-border bg-muted/30 transition-colors hover:bg-primary/10"
        >
          <div className="h-8 w-0.5 rounded-full bg-muted-foreground/20 transition-colors group-hover:bg-primary/50" />
        </div>

        {/* Editor + Results */}
        <div className="flex flex-1 flex-col overflow-hidden min-w-0">
          {/* SQL Editor */}
          <div className="flex flex-col overflow-hidden" style={{ height: editorHeight }}>
            <SqlEditor
              value={query}
              onChange={setQuery}
              onRun={() => void handleRun()}
              height={`${editorHeight}px`}
            />
          </div>

          {/* Editor/Results Drag Handle (horizontal) */}
          <div
            onMouseDown={onEditorDrag}
            className="group flex h-1.5 shrink-0 cursor-row-resize items-center justify-center border-y border-border bg-muted/30 transition-colors hover:bg-primary/10"
          >
            <div className="h-0.5 w-8 rounded-full bg-muted-foreground/20 transition-colors group-hover:bg-primary/50" />
          </div>

          {/* Toolbar */}
          <div className="flex items-center justify-between border-b border-border bg-muted/20 px-4 py-1.5">
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => void handleRun()}
                disabled={executing || !query.trim()}
                className="inline-flex h-7 items-center gap-2 rounded-md bg-primary px-3.5 text-xs font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {executing ? <MorphLoader className="size-3.5" /> : <Play className="size-3.5" />}
                Run
              </button>
              <span className="text-[11px] text-muted-foreground">
                Ctrl + Enter
              </span>

              {/* Save button */}
              <Tooltip text={connection?.player_id ? "Salvar consulta" : "Vincule um sistema para salvar"} side="bottom">
                <button
                  type="button"
                  onClick={() => setSaveDialogOpen(true)}
                  disabled={!query.trim() || !connection?.player_id}
                  className="inline-flex h-7 items-center gap-1.5 rounded-md border border-input px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
                >
                  <Save className="size-3.5" />
                  Salvar
                </button>
              </Tooltip>
            </div>

            {result && (
              <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
                <span className="flex items-center gap-1">
                  <Clock className="size-3" />
                  {result.execution_time_ms}ms
                </span>
                <span>
                  {result.row_count} linha{result.row_count !== 1 ? "s" : ""}
                  {result.truncated ? " (truncado)" : ""}
                </span>
              </div>
            )}
          </div>

          {/* Results area */}
          <div className="flex-1 overflow-auto bg-card min-w-0 min-h-0">
            {executing ? (
              <div className="flex h-full items-center justify-center">
                <MorphLoader className="size-6" />
              </div>
            ) : queryError ? (
              <div className="p-4">
                <div className="flex items-start gap-3 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3">
                  <div className="flex-1 text-sm text-red-600 dark:text-red-400">
                    {queryError}
                  </div>
                  <button
                    type="button"
                    onClick={handleCopyError}
                    className="shrink-0 rounded-md p-1 text-red-400 transition-colors hover:bg-red-500/10 hover:text-red-300"
                  >
                    {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
                  </button>
                </div>
              </div>
            ) : result ? (
              result.row_count === 0 ? (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                  Consulta executada com sucesso — nenhuma linha retornada.
                </div>
              ) : (
                <ResultsTable data={result} />
              )
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-muted-foreground/50">
                <FlaskConical className="size-10" />
                <p className="text-sm">Escreva uma consulta SQL e clique em Run</p>
              </div>
            )}
          </div>
        </div>

        {/* Chat Sidebar */}
        {chatOpen && (
          <>
            {/* Chat Drag Handle (vertical, inverted) */}
            <div
              onMouseDown={onChatDrag}
              className="group flex w-1.5 shrink-0 cursor-col-resize items-center justify-center border-x border-border bg-muted/30 transition-colors hover:bg-primary/10"
            >
              <div className="h-8 w-0.5 rounded-full bg-muted-foreground/20 transition-colors group-hover:bg-primary/50" />
            </div>
            <div className="flex shrink-0 flex-col bg-card" style={{ width: chatWidth }}>
              <ChatPanel
                connectionId={connectionId}
                onClose={() => setChatOpen(false)}
                onApplyQuery={(sql) => setQuery(sql)}
              />
            </div>
          </>
        )}
      </div>

      {/* Edit saved query dialog */}
      {editDialogOpen && editingQuery && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-xl border border-border bg-card p-5 shadow-xl">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-foreground">Editar Consulta</h2>
              <button
                type="button"
                onClick={() => setEditDialogOpen(false)}
                className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X className="size-4" />
              </button>
            </div>

            <div className="mt-4 space-y-3">
              <div>
                <label className="text-xs font-medium text-foreground">Nome *</label>
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  placeholder="Ex: Listar todos os CFOPs"
                  className="mt-1 h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-1 focus:ring-ring/20"
                  autoFocus
                />
              </div>
              <div>
                <label className="text-xs font-medium text-foreground">Descrição</label>
                <input
                  type="text"
                  value={editDesc}
                  onChange={(e) => setEditDesc(e.target.value)}
                  placeholder="Descrição opcional..."
                  className="mt-1 h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-1 focus:ring-ring/20"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-foreground">SQL *</label>
                <textarea
                  value={editSql}
                  onChange={(e) => setEditSql(e.target.value)}
                  rows={5}
                  className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-[11px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-1 focus:ring-ring/20 resize-none"
                />
              </div>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditDialogOpen(false)}
                className="h-8 rounded-md px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => void handleUpdateQuery()}
                disabled={!editName.trim() || !editSql.trim() || editSaving}
                className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-4 text-xs font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {editSaving ? <MorphLoader className="size-3.5" /> : <Save className="size-3.5" />}
                Salvar alterações
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Save query dialog */}
      {saveDialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-xl border border-border bg-card p-5 shadow-xl">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-foreground">Salvar Consulta</h2>
              <button
                type="button"
                onClick={() => setSaveDialogOpen(false)}
                className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X className="size-4" />
              </button>
            </div>

            <div className="mt-4 space-y-3">
              <div>
                <label className="text-xs font-medium text-foreground">Nome *</label>
                <input
                  type="text"
                  value={saveName}
                  onChange={(e) => setSaveName(e.target.value)}
                  placeholder="Ex: Listar todos os CFOPs"
                  className="mt-1 h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-1 focus:ring-ring/20"
                  autoFocus
                />
              </div>
              <div>
                <label className="text-xs font-medium text-foreground">Descrição</label>
                <input
                  type="text"
                  value={saveDesc}
                  onChange={(e) => setSaveDesc(e.target.value)}
                  placeholder="Descrição opcional..."
                  className="mt-1 h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-1 focus:ring-ring/20"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-foreground">SQL</label>
                <pre className="mt-1 max-h-32 overflow-auto rounded-md bg-muted p-3 font-mono text-[11px] text-foreground">
                  {query}
                </pre>
              </div>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setSaveDialogOpen(false)}
                className="h-8 rounded-md px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => void handleSaveQuery()}
                disabled={!saveName.trim() || saving}
                className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-4 text-xs font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {saving ? <MorphLoader className="size-3.5" /> : <Save className="size-3.5" />}
                Salvar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
