import type { AgentApiKey } from "@/lib/auth"

export type { AgentApiKey }

export type ProjectApiKeyCreated = {
  plaintextKey: string
  id: string
  name: string
  prefix: string
}

export type CreateApiKeyInput = {
  name: string
  expiresInDays: number | null
  allowedTools: string[]
}
