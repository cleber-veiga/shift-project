"use client"

/**
 * ExcelNodeConfig — wrapper que conecta os 3 inputs do no excel_input
 * (FilePicker, InputModelPicker, ExcelSheetPicker) com state local pro
 * modelo selecionado.
 *
 * Por que existe: quando o user vincula um modelo de entrada, o dropdown
 * de "Nome da Aba" deve listar as sheets DEFINIDAS NO MODELO (em vez do
 * auto-detect do arquivo), e auto-selecionar a primeira sheet do modelo
 * se sheet_name estiver vazio. Esse comportamento exige acesso ao modelo
 * completo, nao so ao id — daí o wrapper segura `selectedModel` em state.
 */

import { useEffect, useMemo, useState } from "react"
import type { InputModel } from "@/lib/auth"
import { FilePickerInput } from "@/components/workflow/file-picker-input"
import { InputModelPicker } from "@/components/workflow/input-model-picker"
import { ExcelSheetPicker } from "@/components/workflow/excel-sheet-picker"
import { HelpTip } from "@/components/ui/help-tip"

type Data = Record<string, unknown>

export type ExcelNodeConfigProps = {
  workflowId: string
  data: Data
  update: (key: string, value: unknown) => void
}

export function ExcelNodeConfig({ workflowId, data, update }: ExcelNodeConfigProps) {
  const [selectedModel, setSelectedModel] = useState<InputModel | null>(null)

  const modelSheets = useMemo<string[] | null>(() => {
    if (!selectedModel) return null
    const sheets = (selectedModel.schema_def?.sheets ?? []) as Array<{ name?: string }>
    return sheets.map((s) => String(s.name ?? "")).filter(Boolean)
  }, [selectedModel])

  // Quando o user troca de modelo (incluindo de null para algum) e o
  // sheet_name nao bate com nenhuma sheet do novo modelo, alinha com a
  // primeira sheet do modelo. Se sheet_name ja bate com alguma sheet do
  // modelo, mantem (user pode estar pulando entre nodes do mesmo arquivo).
  useEffect(() => {
    if (!modelSheets || modelSheets.length === 0) return
    const current = String(data.sheet_name ?? "")
    if (current && modelSheets.includes(current)) return
    update("sheet_name", modelSheets[0])
  }, [modelSheets])  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <ConfigField
        label="Arquivo Excel"
        help="4 modos: URL/Path direto, Do projeto (uploads salvos), Enviar (upload novo) ou Variável (arquivo solicitado em runtime)."
        helpArticle="variaveis-arquivos"
      >
        <FilePickerInput
          value={(data.url as string) ?? ""}
          onChange={(next) => update("url", next)}
          workflowId={workflowId}
          accept=".xlsx,.xls"
          placeholder="https://... ou /path/to/file.xlsx"
        />
      </ConfigField>
      <ConfigField
        label="Modelo de entrada (opcional)"
        help="Define o cabeçalho esperado da planilha. Vinculado, valida na execução e o Nome da Aba passa a vir do modelo."
        helpArticle="modelos-entrada"
      >
        <InputModelPicker
          workflowId={workflowId}
          value={(data.input_model_id as string | null | undefined) ?? null}
          onChange={(next) => update("input_model_id", next)}
          fileType="excel"
          onModelChange={setSelectedModel}
        />
      </ConfigField>
      <ConfigField
        label="Nome da Aba"
        help="Auto-detectado do arquivo (sem modelo) ou derivado das sheets do modelo (com modelo). Pra ler múltiplas abas, crie um nó Excel pra cada."
      >
        <ExcelSheetPicker
          workflowId={workflowId}
          fileRef={(data.url as string) ?? ""}
          value={(data.sheet_name as string) ?? ""}
          onChange={(v) => update("sheet_name", v)}
          modelSheets={modelSheets}
        />
      </ConfigField>
    </>
  )
}

// Local copy of ConfigField — mantem o componente independente do
// node-config-panel (evita dependencia circular se este file for
// importado por outros lugares).
function ConfigField({
  label,
  help,
  helpArticle,
  children,
}: {
  label: string
  help?: React.ReactNode
  helpArticle?: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <label className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        {label}
        {help && <HelpTip article={helpArticle}>{help}</HelpTip>}
      </label>
      {children}
    </div>
  )
}
