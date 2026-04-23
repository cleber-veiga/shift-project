import type { Node, NodePositionChange } from "@xyflow/react"

export interface GuideLine {
  /** Aligned coordinate: X for vertical guides, Y for horizontal guides. */
  pos: number
  /** Extent start along the orthogonal axis. */
  start: number
  /** Extent end along the orthogonal axis. */
  end: number
}

export interface HelperLinesResult {
  horizontal?: GuideLine
  vertical?: GuideLine
  snapPosition: { x: number | null; y: number | null }
}

/**
 * Compute alignment guides and snap position for a dragging node.
 *
 * Compares the dragging node against every other node on 10 axes:
 *   - vertical (align X):   L↔L, R↔R, L↔R, R↔L, centerX↔centerX
 *   - horizontal (align Y): T↔T, B↔B, T↔B, B↔T, centerY↔centerY
 *
 * Returns the closest matching guide (within `distance` px) bounded by the
 * combined extent of the two aligned nodes, plus the snap position to apply.
 */
export function getHelperLines(
  change: NodePositionChange,
  nodes: Node[],
  distance = 6,
): HelperLinesResult {
  const result: HelperLinesResult = {
    horizontal: undefined,
    vertical: undefined,
    snapPosition: { x: null, y: null },
  }

  const nodeA = nodes.find((n) => n.id === change.id)
  if (!nodeA || !change.position) return result

  const aWidth = nodeA.measured?.width ?? (nodeA.width as number | undefined) ?? 0
  const aHeight = nodeA.measured?.height ?? (nodeA.height as number | undefined) ?? 0

  const aBounds = {
    left: change.position.x,
    right: change.position.x + aWidth,
    top: change.position.y,
    bottom: change.position.y + aHeight,
    centerX: change.position.x + aWidth / 2,
    centerY: change.position.y + aHeight / 2,
    width: aWidth,
    height: aHeight,
  }

  let verticalDistance = distance
  let horizontalDistance = distance

  for (const nodeB of nodes) {
    if (nodeB.id === change.id) continue

    const bWidth = nodeB.measured?.width ?? (nodeB.width as number | undefined) ?? 0
    const bHeight = nodeB.measured?.height ?? (nodeB.height as number | undefined) ?? 0

    const bBounds = {
      left: nodeB.position.x,
      right: nodeB.position.x + bWidth,
      top: nodeB.position.y,
      bottom: nodeB.position.y + bHeight,
      centerX: nodeB.position.x + bWidth / 2,
      centerY: nodeB.position.y + bHeight / 2,
    }

    // Vertical guides extend along Y between both nodes' top/bottom extent
    const vStart = Math.min(aBounds.top, bBounds.top)
    const vEnd = Math.max(aBounds.bottom, bBounds.bottom)
    // Horizontal guides extend along X between both nodes' left/right extent
    const hStart = Math.min(aBounds.left, bBounds.left)
    const hEnd = Math.max(aBounds.right, bBounds.right)

    // ── Vertical (align X) ──
    const dLL = Math.abs(aBounds.left - bBounds.left)
    if (dLL < verticalDistance) {
      result.snapPosition.x = bBounds.left
      result.vertical = { pos: bBounds.left, start: vStart, end: vEnd }
      verticalDistance = dLL
    }
    const dRR = Math.abs(aBounds.right - bBounds.right)
    if (dRR < verticalDistance) {
      result.snapPosition.x = bBounds.right - aBounds.width
      result.vertical = { pos: bBounds.right, start: vStart, end: vEnd }
      verticalDistance = dRR
    }
    const dLR = Math.abs(aBounds.left - bBounds.right)
    if (dLR < verticalDistance) {
      result.snapPosition.x = bBounds.right
      result.vertical = { pos: bBounds.right, start: vStart, end: vEnd }
      verticalDistance = dLR
    }
    const dRL = Math.abs(aBounds.right - bBounds.left)
    if (dRL < verticalDistance) {
      result.snapPosition.x = bBounds.left - aBounds.width
      result.vertical = { pos: bBounds.left, start: vStart, end: vEnd }
      verticalDistance = dRL
    }
    const dCX = Math.abs(aBounds.centerX - bBounds.centerX)
    if (dCX < verticalDistance) {
      result.snapPosition.x = bBounds.centerX - aBounds.width / 2
      result.vertical = { pos: bBounds.centerX, start: vStart, end: vEnd }
      verticalDistance = dCX
    }

    // ── Horizontal (align Y) ──
    const dTT = Math.abs(aBounds.top - bBounds.top)
    if (dTT < horizontalDistance) {
      result.snapPosition.y = bBounds.top
      result.horizontal = { pos: bBounds.top, start: hStart, end: hEnd }
      horizontalDistance = dTT
    }
    const dBB = Math.abs(aBounds.bottom - bBounds.bottom)
    if (dBB < horizontalDistance) {
      result.snapPosition.y = bBounds.bottom - aBounds.height
      result.horizontal = { pos: bBounds.bottom, start: hStart, end: hEnd }
      horizontalDistance = dBB
    }
    const dTB = Math.abs(aBounds.top - bBounds.bottom)
    if (dTB < horizontalDistance) {
      result.snapPosition.y = bBounds.bottom
      result.horizontal = { pos: bBounds.bottom, start: hStart, end: hEnd }
      horizontalDistance = dTB
    }
    const dBT = Math.abs(aBounds.bottom - bBounds.top)
    if (dBT < horizontalDistance) {
      result.snapPosition.y = bBounds.top - aBounds.height
      result.horizontal = { pos: bBounds.top, start: hStart, end: hEnd }
      horizontalDistance = dBT
    }
    const dCY = Math.abs(aBounds.centerY - bBounds.centerY)
    if (dCY < horizontalDistance) {
      result.snapPosition.y = bBounds.centerY - aBounds.height / 2
      result.horizontal = { pos: bBounds.centerY, start: hStart, end: hEnd }
      horizontalDistance = dCY
    }
  }

  return result
}
