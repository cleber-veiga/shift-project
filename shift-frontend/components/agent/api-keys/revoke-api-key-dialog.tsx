"use client"

import { ConfirmDialog } from "@/components/ui/confirm-dialog"

interface RevokeApiKeyDialogProps {
  keyName: string | null
  open: boolean
  loading: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
}

export function RevokeApiKeyDialog({
  keyName,
  open,
  loading,
  onOpenChange,
  onConfirm,
}: RevokeApiKeyDialogProps) {
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Revogar chave de API"
      description={`A chave "${keyName ?? ""}" será revogada imediatamente. Qualquer agente ou integração usando esta chave receberá erro 401 e perderá acesso ao projeto. Esta ação não pode ser desfeita.`}
      confirmText="Revogar"
      confirmVariant="destructive"
      loading={loading}
      onConfirm={onConfirm}
    />
  )
}
