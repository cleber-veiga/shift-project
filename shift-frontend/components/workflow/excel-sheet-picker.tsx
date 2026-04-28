"use client"

/**
 * ExcelSheetPicker — abre o arquivo Excel referenciado por ``fileRef``,
 * lista as sheets via API e mostra um dropdown. Fallback pra texto livre
 * quando nao tem arquivo, ou quando o fetch falha (URL remota inacessivel,
 * variavel ainda nao definida em runtime, etc).
 *
 * Estados:
 *   - sem fileRef                  -> input texto (placeholder informativo)
 *   - fileRef e ``{{vars.X}}``     -> input texto (resolucao so em runtime)
 *   - fileRef carregando           -> spinner
 *   - sheets carregadas            -> dropdown com sheets + opcao "primeira aba"
 *   - fetch falhou                 -> input texto + mensagem de erro
 */

import { useEffect, useMemo, useState } from "react"
import { MorphLoader } from "@/components/ui/morph-loader"
import { listExcelSheets } from "@/lib/auth"

const VARS_RE = /\{\{\s*vars\./
const UPLOAD_SCHEME = "shift-upload://"

export type ExcelSheetPickerProps = {
  workflowId?: string
  /** Referencia ao arquivo: shift-upload://X, http(s)://, /path, ou {{vars.X}}. */
  fileRef: string
  value: string
  onChange: (next: string) => void
  disabled?: boolean
  /** Sheets esperadas pelo modelo de entrada vinculado, se houver.
      Quando passado, o dropdown vem dessas sheets em vez do auto-detect
      do arquivo — UX mais coerente quando ha modelo (ele e o source-of-truth
      do que vai ser validado). */
  modelSheets?: string[] | null
}

function isResolvableAtDesignTime(ref: string): boolean {
  if (!ref) return false
  if (VARS_RE.test(ref)) return false  // resolve so em runtime
  return ref.startsWith(UPLOAD_SCHEME) || /^https?:\/\//i.test(ref) || /^\//.test(ref) || /^[A-Za-z]:\\/.test(ref)
}

export function ExcelSheetPicker({
  workflowId,
  fileRef,
  value,
  onChange,
  disabled = false,
  modelSheets,
}: ExcelSheetPickerProps) {
  const [sheets, setSheets] = useState<string[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canResolveNow = useMemo(() => isResolvableAtDesignTime(fileRef), [fileRef])
  // Quando modelo dita as sheets, NAO faz fetch do arquivo — modelo e
  // source-of-truth e o user nao deveria conseguir escolher uma aba que
  // nao existe no schema validado.
  const useModelSheets = modelSheets !== null && modelSheets !== undefined
  const effectiveSheets = useModelSheets ? modelSheets : sheets

  useEffect(() => {
    if (useModelSheets) {
      // Skip fetch — modelo controla.
      setSheets(null)
      setError(null)
      setLoading(false)
      return
    }
    if (!workflowId || !canResolveNow) {
      setSheets(null)
      setError(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    setSheets(null)

    listExcelSheets(workflowId, fileRef)
      .then((res) => {
        if (cancelled) return
        setSheets(res.sheets)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : "Falha ao ler abas.")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [workflowId, fileRef, canResolveNow, useModelSheets])

  // Se a aba selecionada nao existe nas sheets carregadas, ainda mostra
  // pra usuario nao perder o valor (sinal pra ele de que algo mudou).
  const valueExistsInList = useMemo(
    () => !value || (effectiveSheets ?? []).includes(value),
    [value, effectiveSheets],
  )

  // Quando modelo controla as sheets, renderiza dropdown direto.
  if (useModelSheets && effectiveSheets) {
    if (effectiveSheets.length === 0) {
      return (
        <p className="text-[11px] text-amber-500">
          Modelo vinculado nao define nenhuma sheet. Configure o modelo antes.
        </p>
      )
    }
    return (
      <div className="space-y-1">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-60"
        >
          {effectiveSheets.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
          {!valueExistsInList && value && (
            <option value={value}>{value} (não definida no modelo)</option>
          )}
        </select>
        <p className="text-[11px] text-muted-foreground">
          {effectiveSheets.length === 1
            ? "Aba derivada do modelo de entrada."
            : `${effectiveSheets.length} abas no modelo. Selecione qual usar neste nó.`}
        </p>
      </div>
    )
  }

  // Caso 1: ainda nao temos arquivo resolvivel — texto livre.
  if (!canResolveNow) {
    return (
      <div className="space-y-1">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          placeholder={
            !fileRef
              ? "Selecione o arquivo acima primeiro"
              : "Sheet1 (vazio = primeira aba)"
          }
          className="flex h-9 w-full items-center rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-60"
        />
        {fileRef && VARS_RE.test(fileRef) && (
          <p className="text-[11px] text-muted-foreground">
            Arquivo via variável — abas só ficam disponíveis em runtime. Digite o nome esperado.
          </p>
        )}
      </div>
    )
  }

  // Caso 2: carregando.
  if (loading) {
    return (
      <div className="flex h-9 items-center gap-2 rounded-md border border-input bg-muted/20 px-3 text-xs text-muted-foreground">
        <MorphLoader className="size-3" />
        Lendo abas do arquivo…
      </div>
    )
  }

  // Caso 3: deu ruim — fallback texto livre + mensagem.
  if (error || sheets === null) {
    return (
      <div className="space-y-1">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          placeholder="Sheet1 (vazio = primeira aba)"
          className="flex h-9 w-full items-center rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-60"
        />
        {error && (
          <p className="text-[11px] text-amber-500">
            Nao foi possivel ler as abas: {error}. Digite o nome manualmente.
          </p>
        )}
      </div>
    )
  }

  // Caso 4: sheets carregadas — dropdown.
  return (
    <div className="space-y-1">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-60"
      >
        <option value="">(primeira aba: {sheets[0] ?? "—"})</option>
        {sheets.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
        {!valueExistsInList && value && (
          <option value={value}>
            {value} (não existe no arquivo atual)
          </option>
        )}
      </select>
      <p className="text-[11px] text-muted-foreground">
        {sheets.length === 1
          ? "1 aba detectada."
          : `${sheets.length} abas detectadas. Pra ler mais de uma, crie um nó Excel pra cada.`}
      </p>
    </div>
  )
}
