"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

export function SessionGuard() {
  const router = useRouter()

  useEffect(() => {
    function handleSessionExpired() {
      router.replace("/login")
    }

    window.addEventListener("auth:session-expired", handleSessionExpired)
    return () => window.removeEventListener("auth:session-expired", handleSessionExpired)
  }, [router])

  return null
}
