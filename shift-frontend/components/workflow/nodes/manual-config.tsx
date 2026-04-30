"use client"

import { useEffect, useState } from "react"
import { AlertTriangle } from "lucide-react"
import { HelpTip } from "@/components/ui/help-tip"

interface ManualConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

/**
 * ManualConfig — config do gatilho Manual.
 *
 * Mostra o banner explicativo de gatilho + um editor JSON pra payload de
 * teste. Esse payload e' usado como fallback pelo processor quando a
 * execucao roda sem ``input_data`` externo (ex.: testar o fluxo no editor
 * sem chamar a API ou declarar Variaveis).
 */
export function ManualConfig({ data, onUpdate }: ManualConfigProps) {
  const payload = data.payload

  // Estado local do textarea: a string que o usuario digita. Soh commitamos
  // pro ``data.payload`` quando o JSON parseia OK — assim o usuario pode
  // digitar livremente sem perder caracteres parciais (e.g., aspa aberta
  // no meio do digito).
  const [text, setText] = useState<string>(() => {
    if (payload === null || payload === undefined) return ""
    try {
      return JSON.stringify(payload, null, 2)
    } catch {
      return ""
    }
  })
  const [error, setError] = useState<string | null>(null)

  // Sincroniza quando o ``data`` muda externamente (ex.: outro lugar setou
  // o payload, ou o nó foi recarregado de versão salva). Compara via
  // re-stringify para nao causar loop com nossa propria edição.
  useEffect(() => {
    if (payload === null || payload === undefined) {
      if (text !== "") {
        try {
          // Se o texto local ainda parseia, deixa quieto — o usuario pode
          // estar editando em modo "vazio". Soh limpamos quando o data
          // realmente foi resetado por fora E o texto nao bate.
          JSON.parse(text)
        } catch {
          setText("")
          setError(null)
        }
      }
      return
    }
    try {
      const incoming = JSON.stringify(payload, null, 2)
      // Compara com o que o usuario tem digitado: se nao bate, sincroniza.
      // Trim pra ignorar diferencas so de espacos no fim.
      if (incoming.trim() !== text.trim()) {
        setText(incoming)
        setError(null)
      }
    } catch {
      // payload nao serializavel — ignora
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payload])

  function handleChange(value: string) {
    setText(value)
    if (!value.trim()) {
      onUpdate({ ...data, payload: null })
      setError(null)
      return
    }
    try {
      const parsed = JSON.parse(value)
      onUpdate({ ...data, payload: parsed })
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : "JSON inválido")
    }
  }

  const lineCount = text ? text.split("\n").length : 0

  return (
    <div className="space-y-4">
      {/* Banner: e' um gatilho */}
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
        <p className="text-xs font-medium text-amber-600 dark:text-amber-400">
          Gatilho Manual
        </p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          Este nó marca o ponto de entrada do fluxo. A execução será disparada
          manualmente pelo botão &quot;Executar&quot; na toolbar.
        </p>
      </div>

      {/* Payload de teste */}
      <div className="space-y-1.5">
        <label className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Payload de teste (opcional)
          <HelpTip>
            JSON usado como entrada do fluxo quando o trigger dispara sem
            <code> input_data</code> externo (caso típico ao testar pelo
            editor sem declarar Variáveis ou chamar a API).
            <br />
            <br />
            <strong>Aceita:</strong>
            <br />
            • <em>Objeto</em>: <code>{`{ "campo": valor }`}</code> — vira um
            dict disponível para os nós seguintes consumirem campos via
            template.
            <br />
            • <em>Lista de objetos</em>: <code>{`[{ "..." }, { "..." }]`}</code>{" "}
            — vira um dataset com N linhas, consumível por nós de transformação
            (Mapper, Filter, etc.).
            <br />
            <br />
            Quando o workflow é disparado via API ou pelo modal Executar com
            Variáveis preenchidas, esses dados externos têm prioridade — o
            payload aqui só é usado como fallback de teste.
          </HelpTip>
        </label>
        <p className="text-[10px] leading-relaxed text-muted-foreground/70">
          Ideal para testar o fluxo direto no editor sem precisar declarar
          Variáveis ou subir um arquivo.
        </p>
        <div className="relative">
          <textarea
            value={text}
            onChange={(e) => handleChange(e.target.value)}
            placeholder={`{\n  "exemplo": "valor"\n}\n\nou:\n\n[\n  { "id": 1, "nome": "Linha 1" },\n  { "id": 2, "nome": "Linha 2" }\n]`}
            rows={Math.max(10, Math.min(20, lineCount + 2))}
            spellCheck={false}
            className="w-full resize-y rounded-md border border-input bg-background px-2.5 py-2 font-mono text-[11px] leading-relaxed text-foreground outline-none placeholder:text-muted-foreground/40 focus:ring-1 focus:ring-primary"
          />
        </div>
        {error && (
          <div className="flex items-start gap-1.5 rounded-md border border-destructive/30 bg-destructive/5 p-2 text-[10px] text-destructive">
            <AlertTriangle className="size-3 shrink-0 translate-y-px" />
            <span>
              <strong>JSON inválido:</strong> {error}
            </span>
          </div>
        )}
        {!error && text.trim() && (
          <p className="text-[10px] text-emerald-600 dark:text-emerald-400">
            ✓ JSON válido —{" "}
            {Array.isArray(payload)
              ? `lista de ${payload.length} ${payload.length === 1 ? "linha" : "linhas"} (vira dataset)`
              : "objeto (vira dict de entrada)"}
          </p>
        )}
      </div>
    </div>
  )
}
