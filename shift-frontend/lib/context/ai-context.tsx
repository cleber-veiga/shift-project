"use client"

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react"
import { usePathname } from "next/navigation"
import type { AIContext, AIContextValue } from "@/lib/types/ai-context"

interface AIContextStore {
  context: AIContextValue
  setContext: (ctx: AIContext) => void
  clearContext: () => void
}

const defaultValue: AIContextStore = {
  context: { section: "unknown", pathname: "" },
  setContext: () => undefined,
  clearContext: () => undefined,
}

const AIContextStoreCtx = createContext<AIContextStore>(defaultValue)

export function AIContextProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const [context, setContextState] = useState<AIContextValue>({
    section: "unknown",
    pathname: pathname ?? "",
  })

  const setContext = useCallback((ctx: AIContext) => {
    setContextState(ctx)
  }, [])

  const clearContext = useCallback(() => {
    setContextState({ section: "unknown", pathname: pathname ?? "" })
  }, [pathname])

  return (
    <AIContextStoreCtx.Provider value={{ context, setContext, clearContext }}>
      {children}
    </AIContextStoreCtx.Provider>
  )
}

// Hook leitor — usado pelo painel AI (Fase 5). Nao expoe setContext.
export function useAIContext(): AIContextValue {
  return useContext(AIContextStoreCtx).context
}

/**
 * Hook contribuidor — usado por paginas para registrar o contexto atual.
 *
 * IMPORTANTE: sempre passe um objeto memoizado via useMemo. Objetos literais
 * mudam a cada render e causam loop infinito de cleanup/setup.
 */
export function useRegisterAIContext(context: AIContext | null): void {
  const { setContext, clearContext } = useContext(AIContextStoreCtx)
  // tokenRef rastreia "quem foi o ultimo a registrar" para evitar que o cleanup
  // de uma pagina anterior sobrescreva o contexto ja definido pela pagina atual
  // em navegacoes rapidas.
  const tokenRef = useRef<object>({})

  useEffect(() => {
    if (context === null) {
      return
    }
    const myToken = {}
    tokenRef.current = myToken
    setContext(context)

    return () => {
      if (tokenRef.current === myToken) {
        clearContext()
      }
    }
  }, [context, setContext, clearContext])
}
