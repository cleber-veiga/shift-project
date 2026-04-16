"use client"

import { useCallback, useEffect, useState } from "react"
import {
  Building2,
  Edit2,
  Landmark,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react"
import { useDashboard } from "@/lib/context/dashboard-context"
import {
  type EconomicGroup,
  type Establishment,
  type CreateEconomicGroupPayload,
  type CreateEstablishmentPayload,
  type UpdateEstablishmentPayload,
  listOrganizationConglomerates,
  createEconomicGroup,
  updateEconomicGroup,
  deleteEconomicGroup,
  listEstablishments,
  createEstablishment,
  updateEstablishment,
  deleteEstablishment,
  lookupCnpj,
  lookupCep,
} from "@/lib/auth"
import { MorphLoader } from "@/components/ui/morph-loader"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

const UF_OPTIONS = [
  "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG",
  "PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO",
]

function formatCnpj(value: string): string {
  const digits = value.replace(/\D/g, "")
  if (digits.length <= 2) return digits
  if (digits.length <= 5) return `${digits.slice(0, 2)}.${digits.slice(2)}`
  if (digits.length <= 8) return `${digits.slice(0, 2)}.${digits.slice(2, 5)}.${digits.slice(5)}`
  if (digits.length <= 12) return `${digits.slice(0, 2)}.${digits.slice(2, 5)}.${digits.slice(5, 8)}/${digits.slice(8)}`
  return `${digits.slice(0, 2)}.${digits.slice(2, 5)}.${digits.slice(5, 8)}/${digits.slice(8, 12)}-${digits.slice(12, 14)}`
}

function formatCep(value: string): string {
  const digits = value.replace(/\D/g, "")
  if (digits.length <= 5) return digits
  return `${digits.slice(0, 5)}-${digits.slice(5, 8)}`
}

function GroupDetail({
  group,
  onUpdated,
}: {
  group: EconomicGroup
  onUpdated: () => Promise<void>
}) {
  const [name, setName] = useState(group.name)
  const [description, setDescription] = useState(group.description ?? "")
  const [lastSavedName, setLastSavedName] = useState(group.name.trim())
  const [lastSavedDesc, setLastSavedDesc] = useState((group.description ?? "").trim())
  const [autoSaving, setAutoSaving] = useState(false)
  const [saveError, setSaveError] = useState("")

  const [establishments, setEstablishments] = useState<Establishment[]>([])
  const [estLoading, setEstLoading] = useState(true)
  const [estError, setEstError] = useState("")

  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [savingEst, setSavingEst] = useState(false)
  const [formError, setFormError] = useState("")

  // Establishment form fields
  const [estCorporateName, setEstCorporateName] = useState("")
  const [estTradeName, setEstTradeName] = useState("")
  const [estCnpj, setEstCnpj] = useState("")
  const [estErpCode, setEstErpCode] = useState("")
  const [estCnae, setEstCnae] = useState("")
  const [estStateReg, setEstStateReg] = useState("")
  const [estCep, setEstCep] = useState("")
  const [estCity, setEstCity] = useState("")
  const [estState, setEstState] = useState("")
  const [estNotes, setEstNotes] = useState("")

  const [lookingUpCnpj, setLookingUpCnpj] = useState(false)
  const [lookingUpCep, setLookingUpCep] = useState(false)

  const [deleteTarget, setDeleteTarget] = useState<Establishment | null>(null)
  const [deleting, setDeleting] = useState(false)

  const isEditing = !!editingId

  useEffect(() => {
    setName(group.name)
    setDescription(group.description ?? "")
    setLastSavedName(group.name.trim())
    setLastSavedDesc((group.description ?? "").trim())
  }, [group.id, group.name, group.description])

  const loadEstablishments = useCallback(async () => {
    setEstLoading(true)
    setEstError("")
    try {
      const items = await listEstablishments(group.id)
      setEstablishments(items)
    } catch (err) {
      setEstError(err instanceof Error ? err.message : "Falha ao carregar estabelecimentos.")
    } finally {
      setEstLoading(false)
    }
  }, [group.id])

  useEffect(() => { loadEstablishments() }, [loadEstablishments])

  // Auto-save name + description
  useEffect(() => {
    const trimmedName = name.trim()
    const trimmedDesc = description.trim()
    const nameChanged = trimmedName.length >= 2 && trimmedName !== lastSavedName
    const descChanged = trimmedDesc !== lastSavedDesc

    if (!nameChanged && !descChanged) return

    const timer = window.setTimeout(async () => {
      setAutoSaving(true)
      setSaveError("")
      try {
        const payload: Record<string, string> = {}
        if (nameChanged) payload.name = trimmedName
        if (descChanged) payload.description = trimmedDesc
        await updateEconomicGroup(group.id, payload)
        if (nameChanged) setLastSavedName(trimmedName)
        if (descChanged) setLastSavedDesc(trimmedDesc)
        await onUpdated()
      } catch (err) {
        setSaveError(err instanceof Error ? err.message : "Falha ao salvar.")
      } finally {
        setAutoSaving(false)
      }
    }, 700)

    return () => window.clearTimeout(timer)
  }, [name, description, lastSavedName, lastSavedDesc, group.id, onUpdated])

  const resetForm = () => {
    setEstCorporateName("")
    setEstTradeName("")
    setEstCnpj("")
    setEstErpCode("")
    setEstCnae("")
    setEstStateReg("")
    setEstCep("")
    setEstCity("")
    setEstState("")
    setEstNotes("")
    setFormError("")
  }

  const openNewModal = () => {
    setEditingId(null)
    resetForm()
    setIsModalOpen(true)
  }

  const openEditModal = (est: Establishment) => {
    setEditingId(est.id)
    setEstCorporateName(est.corporate_name)
    setEstTradeName(est.trade_name ?? "")
    setEstCnpj(est.cnpj)
    setEstErpCode(est.erp_code != null ? String(est.erp_code) : "")
    setEstCnae(est.cnae)
    setEstStateReg(est.state_registration ?? "")
    setEstCep(est.cep ?? "")
    setEstCity(est.city ?? "")
    setEstState(est.state ?? "")
    setEstNotes(est.notes ?? "")
    setFormError("")
    setIsModalOpen(true)
  }

  const closeModal = () => {
    if (savingEst) return
    setIsModalOpen(false)
    setEditingId(null)
    resetForm()
  }

  const handleLookupCnpj = async () => {
    const digits = estCnpj.replace(/\D/g, "")
    if (digits.length !== 14) {
      setFormError("Informe os 14 digitos do CNPJ para consultar.")
      return
    }
    setLookingUpCnpj(true)
    setFormError("")
    try {
      const data = await lookupCnpj(digits)
      if (data.razao_social) setEstCorporateName(data.razao_social)
      if (data.nome_fantasia) setEstTradeName(data.nome_fantasia)
      if (data.cnae_fiscal) setEstCnae(String(data.cnae_fiscal))
      if (data.inscricao_estadual) setEstStateReg(data.inscricao_estadual)
      if (data.cep) {
        const cepDigits = data.cep.replace(/\D/g, "")
        setEstCep(cepDigits)
      }
      if (data.municipio) setEstCity(data.municipio)
      if (data.uf) setEstState(data.uf)
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Falha ao consultar CNPJ.")
    } finally {
      setLookingUpCnpj(false)
    }
  }

  const handleLookupCep = async () => {
    const digits = estCep.replace(/\D/g, "")
    if (digits.length !== 8) {
      setFormError("Informe os 8 digitos do CEP para consultar.")
      return
    }
    setLookingUpCep(true)
    setFormError("")
    try {
      const data = await lookupCep(digits)
      if (data.localidade) setEstCity(data.localidade)
      if (data.uf) setEstState(data.uf)
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Falha ao consultar CEP.")
    } finally {
      setLookingUpCep(false)
    }
  }

  const handleSaveEst = async (e: React.FormEvent) => {
    e.preventDefault()
    const cnpjDigits = estCnpj.replace(/\D/g, "")
    const cepDigits = estCep.replace(/\D/g, "")

    if (estCorporateName.trim().length < 2) {
      setFormError("Razao social deve ter pelo menos 2 caracteres.")
      return
    }
    if (cnpjDigits.length !== 14) {
      setFormError("CNPJ deve conter exatamente 14 digitos.")
      return
    }
    if (estCnae.trim().length < 1) {
      setFormError("CNAE e obrigatorio.")
      return
    }

    setSavingEst(true)
    setFormError("")

    try {
      const base = {
        corporate_name: estCorporateName.trim(),
        trade_name: estTradeName.trim() || null,
        cnpj: cnpjDigits,
        erp_code: estErpCode.trim() ? Number(estErpCode.trim()) : null,
        cnae: estCnae.trim(),
        state_registration: estStateReg.trim() || null,
        cep: cepDigits || null,
        city: estCity.trim() || null,
        state: estState || null,
        notes: estNotes.trim() || null,
      }

      if (editingId) {
        await updateEstablishment(editingId, base as UpdateEstablishmentPayload)
      } else {
        await createEstablishment(group.id, base as CreateEstablishmentPayload)
      }
      closeModal()
      await loadEstablishments()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Falha ao salvar estabelecimento.")
    } finally {
      setSavingEst(false)
    }
  }

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    setEstError("")
    try {
      await deleteEstablishment(deleteTarget.id)
      setDeleteTarget(null)
      await loadEstablishments()
    } catch (err) {
      setEstError(err instanceof Error ? err.message : "Falha ao remover estabelecimento.")
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="flex flex-col space-y-4">
      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title="Remover estabelecimento"
        description={
          deleteTarget
            ? `Tem certeza que deseja remover "${deleteTarget.corporate_name}"?`
            : "Tem certeza que deseja remover este estabelecimento?"
        }
        confirmText="Remover"
        confirmVariant="destructive"
        loading={deleting}
        onConfirm={handleConfirmDelete}
      />

      {/* Header bar */}
      <div className="flex items-center justify-between rounded-lg border border-border bg-card/50 p-2.5">
        <div className="flex items-center gap-3">
          <div className="flex size-8 items-center justify-center rounded bg-primary/10">
            <Building2 className="size-4.5 text-primary" />
          </div>
          <h1 className="text-[15px] font-bold tracking-tight text-foreground">{group.name}</h1>
        </div>
        <div className="flex items-center gap-2">
          {saveError ? (
            <span className="rounded bg-destructive/10 px-2 py-1 text-[11px] font-semibold text-destructive">
              {saveError}
            </span>
          ) : null}
          <span className="px-2 py-1 text-[11px] font-medium text-muted-foreground">
            {autoSaving ? "Salvando..." : "Salvo automaticamente"}
          </span>
        </div>
      </div>

      <div className="grid gap-4">
        {/* Group info section */}
        <section className="rounded-lg border border-border bg-card p-4.5 shadow-sm">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                Nome do Grupo
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Ex.: Grupo Alfa"
                className="h-9 w-full rounded-md border border-input bg-background/50 px-3 text-[13px] outline-none transition-all focus:ring-1 focus:ring-primary/20"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                Descricao (Opcional)
              </label>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Descricao do grupo economico"
                className="h-9 w-full rounded-md border border-input bg-background/50 px-3 text-[13px] outline-none transition-all focus:ring-1 focus:ring-primary/20"
              />
            </div>
          </div>
        </section>

        {/* Divider */}
        <div className="flex items-center gap-2 px-1">
          <div className="h-px flex-1 bg-border/50" />
          <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/60">
            Estabelecimentos
          </span>
          <div className="h-px flex-1 bg-border/50" />
        </div>

        {/* Establishments section */}
        <section className="flex flex-col space-y-3">
          <div className="flex items-center justify-between px-1">
            <div className="flex items-center gap-2 text-muted-foreground">
              <Landmark className="size-4" />
              <span className="text-[13px] font-medium">{establishments.length} estabelecimentos vinculados</span>
            </div>
            <button
              type="button"
              onClick={openNewModal}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-background px-3 text-[13px] font-bold transition-all hover:bg-accent"
            >
              <Plus className="size-3.5" />
              Novo Estabelecimento
            </button>
          </div>

          {estError ? (
            <div className="rounded-md border border-destructive/20 bg-destructive/10 px-3 py-2 text-[13px] text-destructive">
              {estError}
            </div>
          ) : null}

          {estLoading ? (
            <div className="flex items-center justify-center rounded-lg border border-border bg-card py-10">
              <MorphLoader className="size-5 morph-muted" />
            </div>
          ) : establishments.length > 0 ? (
            <div className="overflow-auto rounded-lg border border-border bg-card shadow-sm">
              <div className="grid min-w-[720px] grid-cols-[1fr_160px_120px_80px_96px] items-center border-b border-border bg-muted/20 px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                <span>Razao Social</span>
                <span>CNPJ</span>
                <span>Cidade</span>
                <span className="text-center">UF</span>
                <span className="text-right">Acoes</span>
              </div>
              <div className="divide-y divide-border">
                {establishments.map((est) => (
                  <div
                    key={est.id}
                    className="grid min-w-[720px] grid-cols-[1fr_160px_120px_80px_96px] items-center px-4 py-2.5 transition-colors hover:bg-muted/10"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-[13px] font-semibold text-foreground">{est.corporate_name}</p>
                      {est.trade_name ? (
                        <p className="truncate text-[11px] text-muted-foreground">{est.trade_name}</p>
                      ) : null}
                    </div>
                    <p className="text-[12px] font-medium tabular-nums text-muted-foreground">
                      {formatCnpj(est.cnpj)}
                    </p>
                    <p className="truncate text-[12px] text-muted-foreground">{est.city ?? "—"}</p>
                    <p className="text-center text-[12px] font-medium text-muted-foreground">{est.state ?? "—"}</p>
                    <div className="flex items-center justify-end gap-0.5">
                      <button
                        type="button"
                        onClick={() => openEditModal(est)}
                        className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                      >
                        <Edit2 className="size-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeleteTarget(est)}
                        className="rounded p-2 text-destructive/60 transition-colors hover:bg-muted hover:text-destructive"
                      >
                        <Trash2 className="size-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-border bg-card/30 py-12">
              <div className="mb-3 flex size-11 items-center justify-center rounded-full bg-muted">
                <Landmark className="size-5.5 text-muted-foreground" />
              </div>
              <p className="text-[13px] font-semibold text-foreground">Nenhum estabelecimento</p>
              <p className="mb-4 text-[11px] text-muted-foreground">
                Este grupo ainda nao possui estabelecimentos.
              </p>
              <button
                type="button"
                onClick={openNewModal}
                className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-4 text-[13px] font-bold text-primary-foreground transition-all hover:opacity-90"
              >
                <Plus className="size-3.5" />
                Adicionar Primeiro
              </button>
            </div>
          )}
        </section>
      </div>

      {/* Establishment modal */}
      {isModalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4 backdrop-blur-[2px]">
          <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-border bg-card p-4.5 shadow-2xl">
            <div className="mb-5 flex items-start justify-between">
              <div className="flex items-center gap-2">
                <div className="flex size-7 items-center justify-center rounded bg-muted">
                  <Landmark className="size-4 text-muted-foreground" />
                </div>
                <h2 className="text-[13px] font-bold uppercase tracking-tight text-foreground">
                  {isEditing ? "Editar Estabelecimento" : "Novo Estabelecimento"}
                </h2>
              </div>
              <button
                type="button"
                onClick={closeModal}
                disabled={savingEst}
                className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
              >
                <X className="size-3.5" />
              </button>
            </div>

            <form onSubmit={handleSaveEst} className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <label className="mb-1 block text-[10px] font-bold uppercase text-muted-foreground">
                    Razao Social *
                  </label>
                  <input
                    type="text"
                    value={estCorporateName}
                    onChange={(e) => setEstCorporateName(e.target.value)}
                    placeholder="Ex.: Empresa Ltda"
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-[13px] outline-none focus:ring-1 focus:ring-primary/20"
                    required
                  />
                </div>

                <div>
                  <label className="mb-1 block text-[10px] font-bold uppercase text-muted-foreground">
                    Nome Fantasia
                  </label>
                  <input
                    type="text"
                    value={estTradeName}
                    onChange={(e) => setEstTradeName(e.target.value)}
                    placeholder="Nome fantasia"
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-[13px] outline-none focus:ring-1 focus:ring-primary/20"
                  />
                </div>

                <div>
                  <label className="mb-1 block text-[10px] font-bold uppercase text-muted-foreground">
                    CNPJ *
                  </label>
                  <div className="relative">
                    <input
                      type="text"
                      value={formatCnpj(estCnpj)}
                      onChange={(e) => setEstCnpj(e.target.value.replace(/\D/g, "").slice(0, 14))}
                      placeholder="00.000.000/0000-00"
                      className="h-9 w-full rounded-md border border-input bg-background px-3 pr-9 text-[13px] tabular-nums outline-none focus:ring-1 focus:ring-primary/20"
                      required
                    />
                    <button
                      type="button"
                      onClick={handleLookupCnpj}
                      disabled={lookingUpCnpj || estCnpj.replace(/\D/g, "").length !== 14}
                      title="Consultar CNPJ"
                      className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-30"
                    >
                      {lookingUpCnpj ? <MorphLoader className="size-3.5" /> : <Search className="size-3.5" />}
                    </button>
                  </div>
                </div>

                <div>
                  <label className="mb-1 block text-[10px] font-bold uppercase text-muted-foreground">
                    CNAE *
                  </label>
                  <input
                    type="text"
                    value={estCnae}
                    onChange={(e) => setEstCnae(e.target.value)}
                    placeholder="Ex.: 4751-2/01"
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-[13px] outline-none focus:ring-1 focus:ring-primary/20"
                    required
                  />
                </div>

                <div>
                  <label className="mb-1 block text-[10px] font-bold uppercase text-muted-foreground">
                    Codigo ERP
                  </label>
                  <input
                    type="text"
                    inputMode="numeric"
                    value={estErpCode}
                    onChange={(e) => setEstErpCode(e.target.value.replace(/\D/g, ""))}
                    placeholder="Ex.: 1001"
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-[13px] tabular-nums outline-none focus:ring-1 focus:ring-primary/20"
                  />
                </div>

                <div>
                  <label className="mb-1 block text-[10px] font-bold uppercase text-muted-foreground">
                    Inscricao Estadual
                  </label>
                  <input
                    type="text"
                    value={estStateReg}
                    onChange={(e) => setEstStateReg(e.target.value)}
                    placeholder="Inscricao estadual"
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-[13px] outline-none focus:ring-1 focus:ring-primary/20"
                  />
                </div>

                <div>
                  <label className="mb-1 block text-[10px] font-bold uppercase text-muted-foreground">
                    CEP
                  </label>
                  <div className="relative">
                    <input
                      type="text"
                      value={formatCep(estCep)}
                      onChange={(e) => setEstCep(e.target.value.replace(/\D/g, "").slice(0, 8))}
                      placeholder="00000-000"
                      className="h-9 w-full rounded-md border border-input bg-background px-3 pr-9 text-[13px] tabular-nums outline-none focus:ring-1 focus:ring-primary/20"
                    />
                    <button
                      type="button"
                      onClick={handleLookupCep}
                      disabled={lookingUpCep || estCep.replace(/\D/g, "").length !== 8}
                      title="Consultar CEP"
                      className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-30"
                    >
                      {lookingUpCep ? <MorphLoader className="size-3.5" /> : <Search className="size-3.5" />}
                    </button>
                  </div>
                </div>

                <div>
                  <label className="mb-1 block text-[10px] font-bold uppercase text-muted-foreground">
                    Cidade
                  </label>
                  <input
                    type="text"
                    value={estCity}
                    onChange={(e) => setEstCity(e.target.value)}
                    placeholder="Ex.: Maringa"
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-[13px] outline-none focus:ring-1 focus:ring-primary/20"
                  />
                </div>

                <div>
                  <label className="mb-1 block text-[10px] font-bold uppercase text-muted-foreground">
                    UF
                  </label>
                  <Select value={estState} onValueChange={setEstState}>
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="Selecione" />
                    </SelectTrigger>
                    <SelectContent>
                      {UF_OPTIONS.map((uf) => (
                        <SelectItem key={uf} value={uf}>{uf}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div>
                <label className="mb-1 block text-[10px] font-bold uppercase text-muted-foreground">
                  Observacoes
                </label>
                <textarea
                  value={estNotes}
                  onChange={(e) => setEstNotes(e.target.value)}
                  placeholder="Observacoes adicionais..."
                  rows={2}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-[13px] outline-none focus:ring-1 focus:ring-primary/20"
                />
              </div>

              {formError ? (
                <p className="rounded-md border border-destructive/20 bg-destructive/10 px-2.5 py-2 text-[11px] text-destructive">
                  {formError}
                </p>
              ) : null}

              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={closeModal}
                  disabled={savingEst}
                  className="inline-flex h-8 items-center justify-center rounded-md border border-border bg-card px-4 text-[13px] font-semibold text-foreground transition-colors hover:bg-accent disabled:opacity-50"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={savingEst}
                  className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md bg-primary px-4 text-[13px] font-bold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  {savingEst ? <MorphLoader className="size-3" /> : <Plus className="size-3" />}
                  {isEditing ? "Salvar" : "Cadastrar"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  )
}

// ─── Main section (list of groups + detail view) ─────────────────────────────

export function EconomicGroupSection() {
  const { selectedOrganization } = useDashboard()
  const orgId = selectedOrganization?.id

  const [groups, setGroups] = useState<EconomicGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null)

  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [newGroupName, setNewGroupName] = useState("")
  const [newGroupDesc, setNewGroupDesc] = useState("")
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState("")

  const [deleteTarget, setDeleteTarget] = useState<EconomicGroup | null>(null)
  const [deleting, setDeleting] = useState(false)

  const selectedGroup = groups.find((g) => g.id === selectedGroupId) ?? null

  const loadGroups = useCallback(async () => {
    if (!orgId) return
    setLoading(true)
    setError("")
    try {
      const items = await listOrganizationConglomerates(orgId)
      setGroups(items)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar grupos economicos.")
    } finally {
      setLoading(false)
    }
  }, [orgId])

  useEffect(() => { loadGroups() }, [loadGroups])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!orgId) return
    const trimmed = newGroupName.trim()
    if (trimmed.length < 2) {
      setCreateError("Nome deve ter pelo menos 2 caracteres.")
      return
    }
    setCreating(true)
    setCreateError("")
    try {
      const payload: CreateEconomicGroupPayload = {
        name: trimmed,
        description: newGroupDesc.trim() || undefined,
      }
      const created = await createEconomicGroup(orgId, payload)
      setIsCreateOpen(false)
      setNewGroupName("")
      setNewGroupDesc("")
      await loadGroups()
      setSelectedGroupId(created.id)
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Falha ao criar grupo.")
    } finally {
      setCreating(false)
    }
  }

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteEconomicGroup(deleteTarget.id)
      if (selectedGroupId === deleteTarget.id) setSelectedGroupId(null)
      setDeleteTarget(null)
      await loadGroups()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao remover grupo.")
    } finally {
      setDeleting(false)
    }
  }

  // If a group is selected, show detail view
  if (selectedGroup) {
    return (
      <div className="space-y-3">
        <button
          type="button"
          onClick={() => setSelectedGroupId(null)}
          className="inline-flex items-center gap-1.5 text-[13px] font-medium text-muted-foreground transition-colors hover:text-foreground"
        >
          <span>&larr;</span> Voltar para lista
        </button>
        <GroupDetail
          key={selectedGroup.id}
          group={selectedGroup}
          onUpdated={loadGroups}
        />
      </div>
    )
  }

  // List view
  return (
    <section className="space-y-3">
      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title="Remover grupo economico"
        description={
          deleteTarget
            ? `Tem certeza que deseja remover "${deleteTarget.name}" e todos os seus estabelecimentos?`
            : "Tem certeza que deseja remover este grupo?"
        }
        confirmText="Remover"
        confirmVariant="destructive"
        loading={deleting}
        onConfirm={handleConfirmDelete}
      />

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Building2 className="size-4" />
          <span className="text-[13px] font-medium">{groups.length} grupos economicos</span>
        </div>
        <button
          type="button"
          onClick={() => { setIsCreateOpen(true); setCreateError(""); setNewGroupName(""); setNewGroupDesc("") }}
          className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md bg-foreground px-3.5 text-sm font-semibold text-background transition-opacity hover:opacity-90"
        >
          <Plus className="size-4" />
          Novo Grupo
        </button>
      </div>

      {error ? (
        <div className="rounded-md border border-destructive/20 bg-destructive/10 px-3 py-2 text-[13px] text-destructive">
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="flex h-32 items-center justify-center gap-2 text-sm text-muted-foreground">
          <MorphLoader className="size-4 morph-muted" /> Carregando grupos...
        </div>
      ) : groups.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-border bg-card/30 py-12">
          <div className="mb-3 flex size-11 items-center justify-center rounded-full bg-muted">
            <Building2 className="size-5.5 text-muted-foreground" />
          </div>
          <p className="text-[13px] font-semibold text-foreground">Nenhum grupo economico</p>
          <p className="mb-4 text-[11px] text-muted-foreground">
            Crie um grupo para vincular estabelecimentos.
          </p>
          <button
            type="button"
            onClick={() => { setIsCreateOpen(true); setCreateError(""); setNewGroupName(""); setNewGroupDesc("") }}
            className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-4 text-[13px] font-bold text-primary-foreground transition-all hover:opacity-90"
          >
            <Plus className="size-3.5" />
            Criar Primeiro Grupo
          </button>
        </div>
      ) : (
        <div className="overflow-auto rounded-lg border border-border bg-card shadow-sm">
          <div className="grid min-w-[600px] grid-cols-[1fr_1fr_120px_96px] items-center border-b border-border bg-muted/20 px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            <span>Nome do Grupo</span>
            <span>Descricao</span>
            <span className="text-center">Status</span>
            <span className="text-right">Acoes</span>
          </div>
          <div className="divide-y divide-border">
            {groups.map((group) => (
              <div
                key={group.id}
                className="grid min-w-[600px] grid-cols-[1fr_1fr_120px_96px] items-center px-4 py-2.5 transition-colors hover:bg-muted/10"
              >
                <button
                  type="button"
                  onClick={() => setSelectedGroupId(group.id)}
                  className="truncate text-left text-[13px] font-semibold text-foreground hover:underline"
                >
                  {group.name}
                </button>
                <p className="truncate text-[12px] text-muted-foreground">
                  {group.description || "—"}
                </p>
                <div className="flex justify-center">
                  <span className={`inline-flex rounded px-2 py-0.5 text-[10px] font-medium uppercase ${
                    group.is_active ? "bg-emerald-500/10 text-emerald-600" : "bg-muted text-muted-foreground"
                  }`}>
                    {group.is_active ? "Ativo" : "Inativo"}
                  </span>
                </div>
                <div className="flex items-center justify-end gap-0.5">
                  <button
                    type="button"
                    onClick={() => setSelectedGroupId(group.id)}
                    className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    <Edit2 className="size-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => setDeleteTarget(group)}
                    className="rounded p-2 text-destructive/60 transition-colors hover:bg-muted hover:text-destructive"
                  >
                    <Trash2 className="size-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Create group modal */}
      {isCreateOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4 backdrop-blur-[2px]">
          <div className="w-full max-w-lg rounded-xl border border-border bg-card p-4.5 shadow-2xl">
            <div className="mb-5 flex items-start justify-between">
              <div className="flex items-center gap-2">
                <div className="flex size-7 items-center justify-center rounded bg-muted">
                  <Building2 className="size-4 text-muted-foreground" />
                </div>
                <h2 className="text-[13px] font-bold uppercase tracking-tight text-foreground">
                  Novo Grupo Economico
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setIsCreateOpen(false)}
                disabled={creating}
                className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
              >
                <X className="size-3.5" />
              </button>
            </div>

            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="mb-1 block text-[10px] font-bold uppercase text-muted-foreground">
                  Nome do Grupo *
                </label>
                <input
                  type="text"
                  value={newGroupName}
                  onChange={(e) => setNewGroupName(e.target.value)}
                  placeholder="Ex.: Grupo Alfa"
                  className="h-9 w-full rounded-md border border-input bg-background px-3 text-[13px] outline-none focus:ring-1 focus:ring-primary/20"
                  required
                />
              </div>

              <div>
                <label className="mb-1 block text-[10px] font-bold uppercase text-muted-foreground">
                  Descricao
                </label>
                <input
                  type="text"
                  value={newGroupDesc}
                  onChange={(e) => setNewGroupDesc(e.target.value)}
                  placeholder="Descricao opcional"
                  className="h-9 w-full rounded-md border border-input bg-background px-3 text-[13px] outline-none focus:ring-1 focus:ring-primary/20"
                />
              </div>

              {createError ? (
                <p className="rounded-md border border-destructive/20 bg-destructive/10 px-2.5 py-2 text-[11px] text-destructive">
                  {createError}
                </p>
              ) : null}

              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(false)}
                  disabled={creating}
                  className="inline-flex h-8 items-center justify-center rounded-md border border-border bg-card px-4 text-[13px] font-semibold text-foreground transition-colors hover:bg-accent disabled:opacity-50"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md bg-primary px-4 text-[13px] font-bold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  {creating ? <MorphLoader className="size-3" /> : <Plus className="size-3" />}
                  Cadastrar
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </section>
  )
}
