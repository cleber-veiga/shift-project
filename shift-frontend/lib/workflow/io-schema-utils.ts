import type { WorkflowIOSchema } from "@/lib/api/workflow-versions"

const IDENTIFIER_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/

export function isIoSchemaValid(schema: WorkflowIOSchema): boolean {
  for (const list of [schema.inputs, schema.outputs]) {
    const names = new Set<string>()
    for (const p of list) {
      const n = p.name.trim()
      if (!n) return false
      if (!IDENTIFIER_PATTERN.test(n)) return false
      if (names.has(n)) return false
      names.add(n)
    }
  }
  return true
}
