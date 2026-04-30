"use client"

import { useState, useCallback, useRef, useEffect } from "react"
import { ChevronDown, ChevronRight, Eye, EyeOff, Plus, X } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

// ─── Types ────────────────────────────────────────────────────────────────────

type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE" | "HEAD" | "OPTIONS"
type AuthType = "none" | "bearer" | "basic" | "api_key"
type BodyFormat = "json" | "text"

interface AuthConfig {
  type: AuthType
  token?: string
  username?: string
  password?: string
  header?: string
  value?: string
}

export interface HttpRequestConfigProps {
  data: Record<string, unknown>
  onUpdate: (patch: Record<string, unknown>) => void
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function readString(data: Record<string, unknown>, key: string, fallback = ""): string {
  const v = data[key]
  return typeof v === "string" ? v : fallback
}

function readNumber(data: Record<string, unknown>, key: string, fallback: number): number {
  const v = data[key]
  return typeof v === "number" && Number.isFinite(v) ? v : fallback
}

function readBool(data: Record<string, unknown>, key: string, fallback: boolean): boolean {
  const v = data[key]
  return typeof v === "boolean" ? v : fallback
}

function readDict(data: Record<string, unknown>, key: string): Record<string, string> {
  const v = data[key]
  if (v && typeof v === "object" && !Array.isArray(v)) {
    return Object.fromEntries(
      Object.entries(v as Record<string, unknown>).map(([k, val]) => [k, String(val ?? "")]),
    )
  }
  return {}
}

function readAuth(data: Record<string, unknown>): AuthConfig {
  const raw = data.auth
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const obj = raw as Record<string, unknown>
    return {
      type: (typeof obj.type === "string" ? obj.type : "none") as AuthType,
      token: typeof obj.token === "string" ? obj.token : "",
      username: typeof obj.username === "string" ? obj.username : "",
      password: typeof obj.password === "string" ? obj.password : "",
      header: typeof obj.header === "string" ? obj.header : "X-API-Key",
      value: typeof obj.value === "string" ? obj.value : "",
    }
  }
  return { type: "none", token: "", username: "", password: "", header: "X-API-Key", value: "" }
}

function bodyFormatFromData(data: Record<string, unknown>): BodyFormat {
  const fmt = data.body_format
  return fmt === "text" ? "text" : "json"
}

// ─── cURL parser ─────────────────────────────────────────────────────────────

function tokenizeCurl(input: string): string[] {
  const tokens: string[] = []
  let current = ""
  let i = 0
  // Normalize line continuations and Windows line endings
  const src = input.replace(/\\\r?\n/g, " ").replace(/\r\n/g, "\n")

  while (i < src.length) {
    const ch = src[i]
    if (ch === " " || ch === "\t" || ch === "\n") {
      if (current) { tokens.push(current); current = "" }
    } else if (ch === "'" && src[i + 1] !== "'" ) {
      // single-quoted literal
      i++
      while (i < src.length && src[i] !== "'") { current += src[i++] }
    } else if (ch === '"') {
      i++
      while (i < src.length && src[i] !== '"') {
        if (src[i] === "\\" && i + 1 < src.length) { i++; current += src[i] }
        else { current += src[i] }
        i++
      }
    } else if (ch === "$" && src[i + 1] === "'") {
      // ANSI-C quoting $'...'
      i += 2
      while (i < src.length && src[i] !== "'") {
        if (src[i] === "\\" && i + 1 < src.length) {
          i++
          const esc: Record<string, string> = { n: "\n", t: "\t", r: "\r", "\\": "\\", "'": "'" }
          current += esc[src[i]] ?? src[i]
        } else { current += src[i] }
        i++
      }
    } else {
      current += ch
    }
    i++
  }
  if (current) tokens.push(current)
  return tokens
}

interface ParsedCurl {
  method: HttpMethod
  url: string
  headers: Record<string, string>
  query_params: Record<string, string>
  body: unknown
  body_format: BodyFormat
  auth: AuthConfig
}

function parseCurl(raw: string): ParsedCurl | null {
  const tokens = tokenizeCurl(raw.trim())
  if (!tokens.length) return null

  // Strip leading 'curl'
  if (tokens[0].toLowerCase() === "curl") tokens.shift()

  const result: ParsedCurl = {
    method: "GET",
    url: "",
    headers: {},
    query_params: {},
    body: null,
    body_format: "json",
    auth: { type: "none" },
  }

  const singleValueFlags = new Set(["-o", "--output", "-m", "--max-time", "--connect-timeout",
    "--retry", "-b", "--cookie", "-c", "--cookie-jar", "-A", "--user-agent",
    "-e", "--referer", "--cert", "--key", "--cacert", "--capath",
    "--proxy", "-x", "--dns-servers", "--resolve", "--interface",
    "--max-filesize", "--limit-rate", "--retry-delay", "--retry-max-time",
    "--connect-timeout", "--keepalive-time", "--speed-limit", "--speed-time",
    "--local-port", "--range", "--time-cond", "--write-out", "-w"])

  let i = 0
  while (i < tokens.length) {
    const t = tokens[i]

    if (t === "-X" || t === "--request") {
      result.method = ((tokens[++i] ?? "GET").toUpperCase()) as HttpMethod
    } else if (t === "-H" || t === "--header") {
      const hdr = tokens[++i] ?? ""
      const idx = hdr.indexOf(":")
      if (idx > 0) {
        result.headers[hdr.slice(0, idx).trim()] = hdr.slice(idx + 1).trim()
      }
    } else if (["-d", "--data", "--data-raw", "--data-binary", "--data-urlencode"].includes(t)) {
      const raw = tokens[++i] ?? ""
      if (result.method === "GET") result.method = "POST"
      result.body = raw
    } else if (t === "-u" || t === "--user") {
      const up = tokens[++i] ?? ""
      const ci = up.indexOf(":")
      result.auth = { type: "basic", username: up.slice(0, ci < 0 ? undefined : ci), password: ci < 0 ? "" : up.slice(ci + 1) }
    } else if (t === "--url") {
      result.url = tokens[++i] ?? ""
    } else if (!t.startsWith("-")) {
      if (!result.url) result.url = t
    } else if (singleValueFlags.has(t)) {
      i++ // skip the value
    }
    // boolean flags (-v, -s, -k, -L, --compressed, etc.) are simply skipped
    i++
  }

  // Extract query params from URL
  try {
    const u = new URL(result.url)
    u.searchParams.forEach((v, k) => { result.query_params[k] = v })
    result.url = u.origin + u.pathname
  } catch { /* not a valid URL yet, leave as-is */ }

  // Detect auth from Authorization header
  const authHdr = result.headers["Authorization"] ?? result.headers["authorization"]
  if (authHdr && result.auth.type === "none") {
    if (authHdr.startsWith("Bearer ")) {
      result.auth = { type: "bearer", token: authHdr.slice(7) }
      delete result.headers["Authorization"]; delete result.headers["authorization"]
    } else if (authHdr.startsWith("Basic ")) {
      try {
        const dec = atob(authHdr.slice(6))
        const ci = dec.indexOf(":")
        result.auth = { type: "basic", username: dec.slice(0, ci), password: dec.slice(ci + 1) }
        delete result.headers["Authorization"]; delete result.headers["authorization"]
      } catch { /* keep header as-is */ }
    }
  }

  // Determine body format from Content-Type
  const ct = result.headers["Content-Type"] ?? result.headers["content-type"] ?? ""
  if (ct.includes("application/json") || (!ct && typeof result.body === "string")) {
    result.body_format = "json"
    if (typeof result.body === "string") {
      try { result.body = JSON.parse(result.body) } catch { /* leave as string */ }
    }
  } else if (result.body !== null) {
    result.body_format = "text"
  }

  // Infer POST when body is present and method is still GET
  if (result.body !== null && result.method === "GET") result.method = "POST"

  return result
}

// ─── Local UI primitives ──────────────────────────────────────────────────────

function Label({ children }: { children: React.ReactNode }) {
  return (
    <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
      {children}
    </label>
  )
}

function TextField({
  value,
  onChange,
  placeholder,
  type = "text",
  className,
  onPaste,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
  className?: string
  onPaste?: (e: React.ClipboardEvent<HTMLInputElement>) => void
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onPaste={onPaste}
      placeholder={placeholder}
      className={cn(
        "h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary",
        className,
      )}
    />
  )
}

function PasswordField({
  value,
  onChange,
  placeholder,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <input
        type={show ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder ?? "••••••••"}
        className="h-8 w-full rounded-md border border-input bg-background px-2.5 pr-8 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
      />
      <button
        type="button"
        onClick={() => setShow((v) => !v)}
        className="absolute inset-y-0 right-1.5 flex items-center text-muted-foreground hover:text-foreground"
        aria-label={show ? "Ocultar" : "Mostrar"}
      >
        {show ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
      </button>
    </div>
  )
}

function SelectInput<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T
  onChange: (v: T) => void
  options: Array<{ value: T; label: string }>
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as T)}>
      <SelectTrigger className="h-8 text-xs">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((opt) => (
          <SelectItem key={opt.value} value={opt.value} className="text-xs">
            {opt.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  )
}

function Checkbox({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="size-3.5 rounded border-input accent-primary"
      />
      <span className="text-xs text-foreground">{label}</span>
    </label>
  )
}

// ─── Section (collapsible) ────────────────────────────────────────────────────

function Section({
  title,
  badge,
  defaultOpen = false,
  children,
}: {
  title: string
  badge?: number
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="space-y-2 border-t border-border pt-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 text-xs font-semibold text-foreground"
      >
        {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        {title}
        {badge != null && badge > 0 && (
          <span className="ml-1 rounded-full bg-primary/15 px-1.5 py-0.5 text-[10px] font-bold text-primary tabular-nums">
            {badge}
          </span>
        )}
      </button>
      {open && <div className="space-y-3 pl-4">{children}</div>}
    </div>
  )
}

// ─── Key-Value editor ─────────────────────────────────────────────────────────

type KVRow = { id: string; key: string; val: string }

function dictToRows(dict: Record<string, string>): KVRow[] {
  return Object.entries(dict).map(([key, val]) => ({
    id: `${key}_${Math.random().toString(36).slice(2)}`,
    key,
    val,
  }))
}

function rowsToDict(rows: KVRow[]): Record<string, string> {
  const dict: Record<string, string> = {}
  for (const r of rows) {
    if (r.key.trim()) dict[r.key.trim()] = r.val
  }
  return dict
}

function KVEditor({
  value,
  onChange,
  addLabel = "Adicionar",
}: {
  value: Record<string, string>
  onChange: (v: Record<string, string>) => void
  addLabel?: string
}) {
  const [rows, setRows] = useState<KVRow[]>(() => dictToRows(value))

  // Sync when the prop changes from outside (e.g. node switch)
  const propRef = useRef(JSON.stringify(value))
  useEffect(() => {
    const next = JSON.stringify(value)
    if (propRef.current !== next) {
      propRef.current = next
      setRows(dictToRows(value))
    }
  }, [value])

  const commit = useCallback(
    (next: KVRow[]) => {
      setRows(next)
      onChange(rowsToDict(next))
    },
    [onChange],
  )

  return (
    <div className="space-y-1.5">
      {rows.map((row) => (
        <div key={row.id} className="flex items-center gap-1.5">
          <input
            type="text"
            value={row.key}
            onChange={(e) =>
              commit(rows.map((r) => (r.id === row.id ? { ...r, key: e.target.value } : r)))
            }
            placeholder="chave"
            className="h-7 min-w-0 flex-1 rounded border border-input bg-background px-2 text-[11px] text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
          />
          <span className="shrink-0 text-[10px] text-muted-foreground">:</span>
          <input
            type="text"
            value={row.val}
            onChange={(e) =>
              commit(rows.map((r) => (r.id === row.id ? { ...r, val: e.target.value } : r)))
            }
            placeholder="valor"
            className="h-7 min-w-0 flex-1 rounded border border-input bg-background px-2 text-[11px] text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
          />
          <button
            type="button"
            onClick={() => commit(rows.filter((r) => r.id !== row.id))}
            className="shrink-0 text-muted-foreground hover:text-destructive"
            aria-label="Remover"
          >
            <X className="size-3.5" />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() =>
          commit([...rows, { id: `new_${Math.random().toString(36).slice(2)}`, key: "", val: "" }])
        }
        className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-primary"
      >
        <Plus className="size-3" />
        {addLabel}
      </button>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

const METHOD_OPTIONS: Array<{ value: HttpMethod; label: string }> = [
  { value: "GET", label: "GET" },
  { value: "POST", label: "POST" },
  { value: "PUT", label: "PUT" },
  { value: "PATCH", label: "PATCH" },
  { value: "DELETE", label: "DELETE" },
  { value: "HEAD", label: "HEAD" },
  { value: "OPTIONS", label: "OPTIONS" },
]

const METHOD_COLORS: Record<HttpMethod, string> = {
  GET: "text-emerald-500",
  POST: "text-amber-500",
  PUT: "text-blue-500",
  PATCH: "text-violet-500",
  DELETE: "text-red-500",
  HEAD: "text-teal-500",
  OPTIONS: "text-pink-500",
}

const CURL_PASTE_RE = /^\s*curl(\.exe)?(\s|$)/i

const AUTH_OPTIONS: Array<{ value: AuthType; label: string }> = [
  { value: "none", label: "Nenhuma" },
  { value: "bearer", label: "Bearer Token" },
  { value: "basic", label: "Basic Auth" },
  { value: "api_key", label: "API Key (Header)" },
]

const BODY_HAS_PAYLOAD: HttpMethod[] = ["POST", "PUT", "PATCH", "DELETE"]

export function HttpRequestConfig({ data, onUpdate }: HttpRequestConfigProps) {
  const [tab, setTab] = useState<"params" | "settings">("params")

  const method = readString(data, "method", "GET") as HttpMethod
  const url = readString(data, "url", "")
  const auth = readAuth(data)
  const headers = readDict(data, "headers")
  const queryParams = readDict(data, "query_params")
  const body = data.body
  const bodyFormat = bodyFormatFromData(data)
  const timeout = readNumber(data, "timeout_seconds", 30)
  const failOnError = readBool(data, "fail_on_error", true)
  const outputField = readString(data, "output_field", "data")

  const headerCount = Object.keys(headers).length
  const queryCount = Object.keys(queryParams).length
  const hasBody = BODY_HAS_PAYLOAD.includes(method) && body != null && body !== ""
  const bodyText =
    typeof body === "string"
      ? body
      : body != null
        ? JSON.stringify(body, null, 2)
        : ""

  const update = useCallback(
    (field: string, value: unknown) => onUpdate({ [field]: value }),
    [onUpdate],
  )

  const updateAuth = useCallback(
    (patch: Partial<AuthConfig>) => onUpdate({ auth: { ...auth, ...patch } }),
    [auth, onUpdate],
  )

  const handleBodyChange = useCallback(
    (text: string) => {
      if (bodyFormat === "json") {
        try {
          onUpdate({ body: JSON.parse(text) })
        } catch {
          // Keep raw text while the user is typing invalid JSON
          onUpdate({ body: text })
        }
      } else {
        onUpdate({ body: text })
      }
    },
    [bodyFormat, onUpdate],
  )

  const handleCurlImport = useCallback(
    (parsed: ParsedCurl) => {
      onUpdate({
        method: parsed.method,
        url: parsed.url,
        headers: parsed.headers,
        query_params: parsed.query_params,
        body: parsed.body,
        body_format: parsed.body_format,
        auth: parsed.auth,
      })
    },
    [onUpdate],
  )

  const handleUrlPaste = useCallback(
    (e: React.ClipboardEvent<HTMLInputElement>) => {
      const pasted = e.clipboardData.getData("text")
      if (!CURL_PASTE_RE.test(pasted)) return
      const parsed = parseCurl(pasted)
      if (!parsed || !parsed.url) return
      e.preventDefault()
      handleCurlImport(parsed)
    },
    [handleCurlImport],
  )

  return (
    <div className="space-y-4">
      {/* ── Tabs ── */}
      <div className="flex items-center border-b border-border">
        {(["params", "settings"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={cn(
              "-mb-px px-1 pb-2 pr-3 text-xs font-semibold transition-colors",
              tab === t
                ? "border-b-2 border-primary text-foreground"
                : "border-b-2 border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t === "params" ? "Parameters" : "Settings"}
          </button>
        ))}
      </div>

      {tab === "params" ? (
        <div className="space-y-4">
          {/* ── Method + URL ── */}
          <div className="flex items-end gap-1.5">
            <div className="w-[96px] shrink-0 space-y-1.5">
              <Label>Método</Label>
              <Select value={method} onValueChange={(v) => update("method", v)}>
                <SelectTrigger
                  className={cn(
                    "h-8 px-2 text-xs font-bold tracking-wide",
                    METHOD_COLORS[method],
                  )}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {METHOD_OPTIONS.map((opt) => (
                    <SelectItem
                      key={opt.value}
                      value={opt.value}
                      className={cn(
                        "text-xs font-bold tracking-wide",
                        METHOD_COLORS[opt.value],
                      )}
                    >
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="min-w-0 flex-1 space-y-1.5">
              <Label>URL</Label>
              <TextField
                value={url}
                onChange={(v) => update("url", v)}
                onPaste={handleUrlPaste}
                placeholder="https://api.exemplo.com/endpoint   (ou cole um cURL)"
              />
            </div>
          </div>

          {/* ── Authentication ── */}
          <Section title="Autenticação" defaultOpen={auth.type !== "none"}>
            <Field label="Tipo">
              <SelectInput<AuthType>
                value={auth.type}
                onChange={(v) => updateAuth({ type: v })}
                options={AUTH_OPTIONS}
              />
            </Field>

            {auth.type === "bearer" && (
              <Field label="Token">
                <PasswordField
                  value={auth.token ?? ""}
                  onChange={(v) => updateAuth({ token: v })}
                  placeholder="eyJhbGciOiJIUzI1NiJ9…"
                />
              </Field>
            )}

            {auth.type === "basic" && (
              <>
                <Field label="Usuário">
                  <TextField
                    value={auth.username ?? ""}
                    onChange={(v) => updateAuth({ username: v })}
                    placeholder="user"
                  />
                </Field>
                <Field label="Senha">
                  <PasswordField
                    value={auth.password ?? ""}
                    onChange={(v) => updateAuth({ password: v })}
                  />
                </Field>
              </>
            )}

            {auth.type === "api_key" && (
              <>
                <Field label="Nome do header">
                  <TextField
                    value={auth.header ?? "X-API-Key"}
                    onChange={(v) => updateAuth({ header: v })}
                    placeholder="X-API-Key"
                  />
                </Field>
                <Field label="Valor">
                  <PasswordField
                    value={auth.value ?? ""}
                    onChange={(v) => updateAuth({ value: v })}
                  />
                </Field>
              </>
            )}
          </Section>

          {/* ── Query Parameters ── */}
          <Section title="Query Parameters" badge={queryCount}>
            <KVEditor
              value={queryParams}
              onChange={(v) => update("query_params", v)}
              addLabel="Adicionar parâmetro"
            />
          </Section>

          {/* ── Headers ── */}
          <Section title="Headers" badge={headerCount}>
            <KVEditor
              value={headers}
              onChange={(v) => update("headers", v)}
              addLabel="Adicionar header"
            />
          </Section>

          {/* ── Body (only for methods that carry a payload) ── */}
          {BODY_HAS_PAYLOAD.includes(method) && (
            <Section title="Body" defaultOpen={hasBody}>
              <div className="flex items-center gap-3">
                <Label>Formato</Label>
                <div className="flex items-center gap-2">
                  {(["json", "text"] as BodyFormat[]).map((fmt) => (
                    <label key={fmt} className="flex cursor-pointer items-center gap-1.5">
                      <input
                        type="radio"
                        name="body_format"
                        value={fmt}
                        checked={bodyFormat === fmt}
                        onChange={() => onUpdate({ body_format: fmt, body: "" })}
                        className="size-3 accent-primary"
                      />
                      <span className="text-[11px] text-foreground">
                        {fmt === "json" ? "JSON" : "Raw Text"}
                      </span>
                    </label>
                  ))}
                </div>
              </div>
              <textarea
                value={bodyText}
                onChange={(e) => handleBodyChange(e.target.value)}
                placeholder={
                  bodyFormat === "json"
                    ? '{\n  "chave": "valor"\n}'
                    : "Conteúdo em texto puro"
                }
                rows={6}
                className="w-full resize-y rounded-md border border-input bg-background px-2.5 py-2 font-mono text-[11px] text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
              />
              {bodyFormat === "json" && (() => {
                try {
                  JSON.parse(bodyText)
                  return null
                } catch {
                  return bodyText ? (
                    <p className="text-[10px] text-destructive">JSON inválido</p>
                  ) : null
                }
              })()}
            </Section>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          <Field label="Timeout (s)">
            <TextField
              type="number"
              value={String(timeout)}
              onChange={(v) => {
                const n = Number(v)
                if (Number.isFinite(n) && n > 0) update("timeout_seconds", n)
              }}
            />
          </Field>
          <Field label="Campo de saída">
            <TextField
              value={outputField}
              onChange={(v) => update("output_field", v || "data")}
              placeholder="data"
            />
          </Field>
          <Checkbox
            checked={failOnError}
            onChange={(v) => update("fail_on_error", v)}
            label="Falhar se o status HTTP indicar erro (4xx / 5xx)"
          />
        </div>
      )}
    </div>
  )
}
