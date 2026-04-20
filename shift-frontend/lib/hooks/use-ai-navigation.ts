"use client"

import { useCallback } from "react"
import { useRouter } from "next/navigation"

export function useAINavigation() {
  const router = useRouter()

  const navigateTo = useCallback((path: string) => {
    // Navega sem fechar o painel nem resetar a thread ativa
    router.push(path)
  }, [router])

  return { navigateTo }
}
