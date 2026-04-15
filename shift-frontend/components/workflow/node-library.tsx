"use client"

import { useState } from "react"
import { ChevronDown, ChevronRight, GripVertical, Search, X } from "lucide-react"
import { NODE_CATEGORIES, NODE_REGISTRY, type NodeCategory, type NodeDefinition } from "@/lib/workflow/types"
import { getNodeIcon } from "@/lib/workflow/node-icons"
import { cn } from "@/lib/utils"

interface NodeLibraryProps {
  onClose: () => void
}

const categoryColorMap: Record<string, string> = {
  trigger: "text-amber-500",
  input: "text-blue-500",
  transform: "text-violet-500",
  output: "text-emerald-500",
  ai: "text-pink-500",
}

const categoryBgMap: Record<string, string> = {
  trigger: "bg-amber-500/10",
  input: "bg-blue-500/10",
  transform: "bg-violet-500/10",
  output: "bg-emerald-500/10",
  ai: "bg-pink-500/10",
}

function DraggableNode({ definition }: { definition: NodeDefinition }) {
  const Icon = getNodeIcon(definition.icon)

  function onDragStart(event: React.DragEvent) {
    event.dataTransfer.setData("application/reactflow-type", definition.type)
    event.dataTransfer.effectAllowed = "move"
  }

  return (
    <div
      draggable
      onDragStart={onDragStart}
      className="group flex cursor-grab items-center gap-2.5 rounded-md border border-transparent px-2 py-2 transition-colors hover:border-border hover:bg-muted/50 active:cursor-grabbing"
    >
      <GripVertical className="size-3 shrink-0 text-muted-foreground/40 transition-colors group-hover:text-muted-foreground" />
      <div className={cn("flex size-7 shrink-0 items-center justify-center rounded-md", categoryBgMap[definition.category])}>
        <Icon className={cn("size-3.5", categoryColorMap[definition.category])} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-medium text-foreground">{definition.label}</p>
        <p className="truncate text-[10px] text-muted-foreground">{definition.description}</p>
      </div>
    </div>
  )
}

export function NodeLibrary({ onClose }: NodeLibraryProps) {
  const [search, setSearch] = useState("")
  const [expanded, setExpanded] = useState<Set<NodeCategory>>(new Set(NODE_CATEGORIES.map((c) => c.key)))

  const filteredNodes = search.trim()
    ? NODE_REGISTRY.filter(
        (n) =>
          n.label.toLowerCase().includes(search.toLowerCase()) ||
          n.description.toLowerCase().includes(search.toLowerCase())
      )
    : NODE_REGISTRY

  function toggleCategory(cat: NodeCategory) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(cat)) next.delete(cat)
      else next.add(cat)
      return next
    })
  }

  return (
    <div className="flex h-full w-64 flex-col rounded-lg border border-border bg-card shadow-lg">
      {/* Header */}
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-border px-3">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Nós</span>
        <button
          type="button"
          onClick={onClose}
          className="flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <X className="size-3.5" />
        </button>
      </div>

      {/* Search */}
      <div className="border-b border-border px-3 py-2">
        <label className="flex h-8 items-center gap-2 rounded-md border border-input bg-background px-2.5">
          <Search className="size-3.5 shrink-0 text-muted-foreground" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar nós..."
            className="w-full bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground"
          />
        </label>
      </div>

      {/* Node list */}
      <div className="flex-1 overflow-y-auto px-2 py-2">
        {search.trim() ? (
          // Flat filtered list
          <div className="space-y-0.5">
            {filteredNodes.length === 0 && (
              <p className="px-2 py-4 text-center text-xs text-muted-foreground">Nenhum nó encontrado</p>
            )}
            {filteredNodes.map((node) => (
              <DraggableNode key={node.type} definition={node} />
            ))}
          </div>
        ) : (
          // Categorized list
          <div className="space-y-1">
            {NODE_CATEGORIES.map((cat) => {
              const nodes = filteredNodes.filter((n) => n.category === cat.key)
              if (nodes.length === 0) return null
              const isExpanded = expanded.has(cat.key)

              return (
                <div key={cat.key}>
                  <button
                    type="button"
                    onClick={() => toggleCategory(cat.key)}
                    className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-muted/50"
                  >
                    {isExpanded ? (
                      <ChevronDown className="size-3 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="size-3 text-muted-foreground" />
                    )}
                    <span className={cn("text-[11px] font-semibold uppercase tracking-wider", cat.color)}>
                      {cat.label}
                    </span>
                    <span className="ml-auto text-[10px] text-muted-foreground">{nodes.length}</span>
                  </button>

                  {isExpanded && (
                    <div className="ml-1 space-y-0.5">
                      {nodes.map((node) => (
                        <DraggableNode key={node.type} definition={node} />
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Footer hint */}
      <div className="shrink-0 border-t border-border px-3 py-2">
        <p className="text-[10px] text-muted-foreground">Arraste um nó para o canvas para adicioná-lo ao fluxo</p>
      </div>
    </div>
  )
}
