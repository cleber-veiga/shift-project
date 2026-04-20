"use client"

import { useAIContext } from "./ai-context"

function Overlay() {
  const ctx = useAIContext()
  return (
    <div className="fixed bottom-2 right-2 z-50 max-w-xs rounded border bg-background/90 p-2 text-xs backdrop-blur">
      <div className="font-mono">AI Context</div>
      <pre className="text-[10px]">{JSON.stringify(ctx, null, 2)}</pre>
    </div>
  )
}

export function AIContextDebugOverlay() {
  if (process.env.NODE_ENV !== "development") return null
  return <Overlay />
}
