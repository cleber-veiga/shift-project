/**
 * Round-trip entre o canvas (flat com parentId) e a definicao salva
 * (nos filhos embutidos em data.body do loop).
 *
 * Quando o backend tem um nó loop em ``body_mode='inline'``, ele guarda
 * o corpo do loop em ``data.body = { nodes, edges }`` dentro do proprio
 * node. Para o usuario editar visualmente esse corpo no React Flow,
 * "explodimos" esses nos para o canvas principal usando
 * ``parentId: <loopId>`` + ``extent: 'parent'`` — assim eles ficam
 * contidos no container do loop e seguem-no quando arrastado.
 *
 * Antes de salvar, fazemos o caminho inverso: agrupamos por ``parentId``,
 * empacotamos em ``data.body`` e removemos os filhos do array flat.
 */
import type { Edge, Node } from "@xyflow/react"

const LOOP_TYPE = "loop"
const INLINE_MODE = "inline"

function isInlineLoop(node: Node): boolean {
  if (node.type !== LOOP_TYPE) {
    const dataType = (node.data as Record<string, unknown> | undefined)?.type
    if (dataType !== LOOP_TYPE) return false
  }
  const data = (node.data ?? {}) as Record<string, unknown>
  return (data.body_mode ?? "external") === INLINE_MODE
}

/**
 * Expande os corpos inline da definicao salva para o estado plano que
 * o React Flow entende (filhos com ``parentId``). Nao muta os arrays
 * de entrada — devolve copias.
 */
export function expandInlineLoopBodies(
  nodes: Node[],
  edges: Edge[],
): { nodes: Node[]; edges: Edge[] } {
  const outNodes: Node[] = []
  const outEdges: Edge[] = [...edges]

  for (const node of nodes) {
    if (!isInlineLoop(node)) {
      outNodes.push(node)
      continue
    }
    const data = (node.data ?? {}) as Record<string, unknown>
    const body = data.body as { nodes?: Node[]; edges?: Edge[] } | undefined

    // Preserva o node loop, mas remove ``body`` do data flat — ele sera
    // recomposto a partir dos filhos no momento de salvar. Manter o
    // ``body`` aqui levaria a duplicacao (corpo no data + filhos no canvas).
    const { body: _omit, ...rest } = data
    void _omit
    outNodes.push({ ...node, data: rest })

    if (!body) continue
    const childNodes = Array.isArray(body.nodes) ? body.nodes : []
    const childEdges = Array.isArray(body.edges) ? body.edges : []

    for (const child of childNodes) {
      outNodes.push({
        ...child,
        parentId: node.id,
        extent: "parent",
      })
    }
    for (const edge of childEdges) {
      outEdges.push(edge)
    }
  }

  return { nodes: outNodes, edges: outEdges }
}

/**
 * Inverso: pega o canvas plano (com filhos por parentId) e empacota
 * cada corpo de loop inline de volta no ``data.body`` do respectivo
 * node loop. Filhos sao removidos do array de saida.
 *
 * Edges com ambos endpoints como filhos do mesmo loop entram no
 * ``body.edges``; o resto fica no array plano. Edges que cruzam a
 * fronteira sao mantidas no array plano (a validacao backend bloqueia
 * publicacao se isso ocorrer — frontend nao tenta consertar).
 */
export function collapseInlineLoopBodies(
  nodes: Node[],
  edges: Edge[],
): { nodes: Node[]; edges: Edge[] } {
  const loopIds = new Set<string>()
  const loopNodes = new Map<string, Node>()
  for (const node of nodes) {
    if (isInlineLoop(node)) {
      loopIds.add(node.id)
      loopNodes.set(node.id, node)
    }
  }

  if (loopIds.size === 0) {
    return { nodes, edges }
  }

  const childrenByLoop = new Map<string, Node[]>()
  const topLevelNodes: Node[] = []
  for (const node of nodes) {
    const parentId = (node as Node & { parentId?: string }).parentId
    if (parentId && loopIds.has(parentId)) {
      const list = childrenByLoop.get(parentId) ?? []
      // Nao serializa parentId/extent — o backend nao usa, e ao recarregar
      // serao re-injetados por expandInlineLoopBodies.
      const { parentId: _p, extent: _e, ...clean } = node as Node & {
        parentId?: string
        extent?: unknown
      }
      void _p
      void _e
      list.push(clean)
      childrenByLoop.set(parentId, list)
    } else {
      topLevelNodes.push(node)
    }
  }

  // Particiona edges: as que ligam dois filhos do mesmo loop entram em
  // body.edges; o restante segue no array plano.
  const childIdToLoopId = new Map<string, string>()
  for (const [loopId, children] of childrenByLoop) {
    for (const child of children) {
      childIdToLoopId.set(child.id, loopId)
    }
  }
  const edgesByLoop = new Map<string, Edge[]>()
  const topLevelEdges: Edge[] = []
  for (const edge of edges) {
    const srcLoop = childIdToLoopId.get(edge.source)
    const tgtLoop = childIdToLoopId.get(edge.target)
    if (srcLoop && srcLoop === tgtLoop) {
      const list = edgesByLoop.get(srcLoop) ?? []
      list.push(edge)
      edgesByLoop.set(srcLoop, list)
    } else {
      topLevelEdges.push(edge)
    }
  }

  // Reescreve cada node loop com ``data.body`` restaurado.
  const finalNodes: Node[] = topLevelNodes.map((node) => {
    if (!loopIds.has(node.id)) return node
    const children = childrenByLoop.get(node.id) ?? []
    const bodyEdges = edgesByLoop.get(node.id) ?? []
    const data = (node.data ?? {}) as Record<string, unknown>
    return {
      ...node,
      data: {
        ...data,
        body: { nodes: children, edges: bodyEdges },
      },
    }
  })

  return { nodes: finalNodes, edges: topLevelEdges }
}
