"use client"

import { useState } from "react"
import { AlertTriangle, Check, Copy, KeyRound } from "lucide-react"

interface ApiKeyCreatedDialogProps {
  open: boolean
  plaintextKey: string
  keyName: string
  onClose: () => void
}

export function ApiKeyCreatedDialog({
  open,
  plaintextKey,
  keyName,
  onClose,
}: ApiKeyCreatedDialogProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(plaintextKey)
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    } catch {
      // clipboard may fail in insecure contexts
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      {/* Backdrop — not clickable: user must confirm they copied */}
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" />

      <div
        role="dialog"
        aria-modal="true"
        aria-label="Chave criada — copie agora"
        className="relative z-10 w-full max-w-lg rounded-2xl border border-border bg-card p-6 shadow-2xl"
      >
        <div className="mb-5 flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-lg bg-emerald-500/10">
            <KeyRound className="size-5 text-emerald-600 dark:text-emerald-400" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-foreground">Chave criada com sucesso</h2>
            <p className="text-xs text-muted-foreground">{keyName}</p>
          </div>
        </div>

        <div className="mb-5 flex items-start gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3">
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-amber-600 dark:text-amber-400" />
          <div>
            <p className="text-sm font-semibold text-amber-900 dark:text-amber-200">
              Esta é a ÚNICA vez que você verá a chave completa.
            </p>
            <p className="mt-0.5 text-xs text-amber-800 dark:text-amber-300">
              Após fechar este diálogo, não será possível recuperar o valor. Copie e guarde em um gerenciador de segredos agora.
            </p>
          </div>
        </div>

        <div className="mb-5">
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
            Chave de API (plaintext)
          </label>
          <div className="flex items-stretch gap-2">
            <code className="flex-1 overflow-x-auto rounded-lg border border-input bg-background px-3 py-2.5 font-mono text-xs text-foreground select-all">
              {plaintextKey}
            </code>
            <button
              type="button"
              onClick={handleCopy}
              className="inline-flex items-center gap-1.5 rounded-lg border border-input bg-background px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-accent"
            >
              {copied ? (
                <>
                  <Check className="size-3.5 text-emerald-500" />
                  Copiado!
                </>
              ) : (
                <>
                  <Copy className="size-3.5" />
                  Copiar
                </>
              )}
            </button>
          </div>
        </div>

        <div className="flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center gap-2 rounded-lg bg-foreground px-4 py-2.5 text-sm font-semibold text-background transition-opacity hover:opacity-90"
          >
            <Check className="size-4" />
            Eu copiei e guardei a chave
          </button>
        </div>
      </div>
    </div>
  )
}
