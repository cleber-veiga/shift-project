"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  ChevronDown,
  ChevronRight,
  Copy,
  Eye,
  EyeOff,
  Radio,
} from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import {
  clearWebhookCaptures,
  getWebhookUrls,
  listenForTestEvent,
  type WebhookCapture,
  type WebhookUrls,
} from "@/lib/api/webhooks"
import { cn } from "@/lib/utils"

// ─── Types ────────────────────────────────────────────────────────────────────

type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE" | "HEAD"
type AuthType = "none" | "header" | "basic" | "jwt"
type RespondMode = "immediately" | "on_finish" | "using_respond_node"
type ResponseData = "first_entry_json" | "all_entries" | "no_body"

interface AuthConfig {
  type: AuthType
  header_name?: string | null
  header_value?: string | null
  username?: string | null
  password?: string | null
  jwt_secret?: string | null
  jwt_algorithm?: string | null
}

interface WebhookConfigProps {
  workflowId: string
  nodeId: string
  data: Record<string, unknown>
  onUpdate: (patch: Record<string, unknown>) => void
  onTestEvent?: (capture: WebhookCapture) => void
}

const METHOD_OPTIONS: HttpMethod[] = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]

const AUTH_OPTIONS: Array<{ value: AuthType; label: string }> = [
  { value: "none", label: "Nenhuma" },
  { value: "header", label: "Header Auth" },
  { value: "basic", label: "Basic Auth" },
  { value: "jwt", label: "JWT" },
]

const RESPOND_OPTIONS: Array<{ value: RespondMode; label: string }> = [
  { value: "immediately", label: "Imediatamente" },
  { value: "on_finish", label: "Ao terminar o workflow" },
  { value: "using_respond_node", label: "Via nó 'Respond to Webhook'" },
]

const RESPONSE_DATA_OPTIONS: Array<{ value: ResponseData; label: string }> = [
  { value: "first_entry_json", label: "Primeiro registro (JSON)" },
  { value: "all_entries", label: "Todos os registros" },
  { value: "no_body", label: "Sem corpo" },
]

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

function readAuth(data: Record<string, unknown>): AuthConfig {
  const raw = data.authentication
  if (raw && typeof raw === "object") {
    const obj = raw as Record<string, unknown>
    return {
      type: (typeof obj.type === "string" ? obj.type : "none") as AuthType,
      header_name: (obj.header_name as string) ?? null,
      header_value: (obj.header_value as string) ?? null,
      username: (obj.username as string) ?? null,
      password: (obj.password as string) ?? null,
      jwt_secret: (obj.jwt_secret as string) ?? null,
      jwt_algorithm: (obj.jwt_algorithm as string) ?? "HS256",
    }
  }
  return { type: "none", jwt_algorithm: "HS256" }
}

// ─── Reusable inputs ──────────────────────────────────────────────────────────

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
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
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
        placeholder={placeholder}
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

function Select<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T
  onChange: (v: T) => void
  options: Array<{ value: T; label: string }>
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as T)}
      className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  )
}

function Field({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  )
}

function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
  disabled?: boolean
}) {
  return (
    <label
      className={cn(
        "flex items-center gap-2",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      <input
        type="checkbox"
        disabled={disabled}
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="size-3.5 rounded border-input accent-primary"
      />
      <span className="text-xs text-foreground">{label}</span>
    </label>
  )
}

// ─── URL card ─────────────────────────────────────────────────────────────────

function UrlCard({
  method,
  url,
  kind,
  loading,
}: {
  method: string
  url: string
  kind: "test" | "prod"
  loading: boolean
}) {
  const [copied, setCopied] = useState(false)
  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // ignore
    }
  }, [url])

  return (
    <div className="flex items-center gap-2 rounded-md border border-border bg-background px-2 py-1.5">
      <span
        className={cn(
          "rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
          kind === "test"
            ? "bg-zinc-500/10 text-zinc-600 dark:text-zinc-300"
            : "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
        )}
      >
        {method}
      </span>
      <code className="flex-1 truncate font-mono text-[11px] text-foreground">
        {loading ? "Carregando..." : url || "—"}
      </code>
      <button
        type="button"
        onClick={handleCopy}
        disabled={loading || !url}
        className="flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
        aria-label="Copiar URL"
      >
        <Copy className="size-3" />
      </button>
      {copied ? (
        <span className="text-[10px] font-medium text-emerald-600">ok</span>
      ) : null}
    </div>
  )
}

// ─── Main component ──────────────────────────────────────────────────────────

export function WebhookConfig({
  workflowId,
  nodeId,
  data,
  onUpdate,
  onTestEvent,
}: WebhookConfigProps) {
  const [tab, setTab] = useState<"params" | "settings">("params")

  const httpMethod = (readString(data, "http_method", "POST") as HttpMethod)
  const path = readString(data, "path", "")
  const auth = useMemo<AuthConfig>(() => readAuth(data), [data])
  const respondMode = (readString(data, "respond_mode", "immediately") as RespondMode)
  const responseCode = readNumber(data, "response_code", 200)
  const responseData = (readString(data, "response_data", "first_entry_json") as ResponseData)
  const rawBody = readBool(data, "raw_body", false)
  const allowedOrigins = readString(data, "allowed_origins", "")

  const updateField = useCallback(
    (field: string, value: unknown) => {
      onUpdate({ [field]: value })
    },
    [onUpdate],
  )

  const updateAuth = useCallback(
    (patch: Partial<AuthConfig>) => {
      onUpdate({ authentication: { ...auth, ...patch } })
    },
    [auth, onUpdate],
  )

  // ── Auto-preenche path na primeira vez ─────────────────────────────────
  // n8n usa um id curto e pseudo-aleatorio como default para que a URL de
  // producao nao seja advinhavel. Rodamos so uma vez por montagem do no.
  const didInitPathRef = useRef(false)
  useEffect(() => {
    if (didInitPathRef.current) return
    didInitPathRef.current = true
    if (!path || path.trim() === "") {
      const generated =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `webhook-${Math.random().toString(36).slice(2, 10)}`
      onUpdate({ path: generated })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── URLs ────────────────────────────────────────────────────────────────
  // Buscamos do backend uma vez por montagem apenas para:
  //   (a) conhecer a base publica (EXTERNAL_BASE_URL ou request.base_url)
  //   (b) saber se o workflow esta publicado (production_ready)
  // A URL exibida e recomposta no cliente a partir do ``path`` em memoria,
  // de modo que o card reage imediatamente ao que o usuario digita — sem
  // depender de o workflow ter sido salvo no banco.
  const [urls, setUrls] = useState<WebhookUrls | null>(null)
  const [urlsLoading, setUrlsLoading] = useState(false)
  const [urlsTab, setUrlsTab] = useState<"test" | "prod">("test")
  const [showUrlsSection, setShowUrlsSection] = useState(true)

  useEffect(() => {
    if (!workflowId || workflowId === "new") return
    let cancelled = false
    setUrlsLoading(true)
    getWebhookUrls(workflowId)
      .then((data) => {
        if (!cancelled) setUrls(data)
      })
      .catch(() => {
        /* silencioso */
      })
      .finally(() => {
        if (!cancelled) setUrlsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [workflowId])

  const baseUrl = useMemo(() => {
    if (urls?.test_url) {
      return urls.test_url.replace(/\/api\/v1\/webhook-test\/.*$/, "")
    }
    if (typeof window !== "undefined") {
      return window.location.origin
    }
    return ""
  }, [urls])

  const effectivePath = (path && path.trim()) || workflowId
  const composedTestUrl = baseUrl
    ? `${baseUrl}/api/v1/webhook-test/${effectivePath}`
    : ""
  const composedProdUrl = baseUrl
    ? `${baseUrl}/api/v1/webhook/${effectivePath}`
    : ""

  // ── Listen for test event ───────────────────────────────────────────────
  const [listening, setListening] = useState(false)
  const [listenError, setListenError] = useState<string | null>(null)
  const listenAbortRef = useRef<AbortController | null>(null)

  const stopListening = useCallback(async () => {
    listenAbortRef.current?.abort()
    listenAbortRef.current = null
    setListening(false)
    try {
      await clearWebhookCaptures(workflowId, nodeId)
    } catch {
      /* silencioso */
    }
  }, [workflowId, nodeId])

  const handleListen = useCallback(async () => {
    if (listening) {
      await stopListening()
      return
    }
    setListenError(null)
    setListening(true)
    const controller = new AbortController()
    listenAbortRef.current = controller
    try {
      const capture = await listenForTestEvent(workflowId, nodeId, 120, {
        signal: controller.signal,
      })
      onTestEvent?.(capture)
    } catch (err) {
      if (!controller.signal.aborted) {
        setListenError(err instanceof Error ? err.message : "Falha ao escutar evento.")
      }
    } finally {
      setListening(false)
      listenAbortRef.current = null
    }
  }, [listening, stopListening, workflowId, nodeId, onTestEvent])

  useEffect(() => {
    return () => {
      listenAbortRef.current?.abort()
    }
  }, [])

  // ── Options section ────────────────────────────────────────────────────
  const [showOptions, setShowOptions] = useState(false)

  const displayedUrl = urlsTab === "test" ? composedTestUrl : composedProdUrl
  const displayedMethod = httpMethod

  return (
    <div className="space-y-4">
      {/* Tabs */}
      <div className="flex items-center justify-between border-b border-border">
        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={() => setTab("params")}
            className={cn(
              "-mb-px px-1 pb-2 text-xs font-semibold transition-colors",
              tab === "params"
                ? "border-b-2 border-primary text-foreground"
                : "border-b-2 border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            Parameters
          </button>
          <button
            type="button"
            onClick={() => setTab("settings")}
            className={cn(
              "-mb-px px-1 pb-2 text-xs font-semibold transition-colors",
              tab === "settings"
                ? "border-b-2 border-primary text-foreground"
                : "border-b-2 border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            Settings
          </button>
        </div>
        {tab === "params" ? (
          <button
            type="button"
            onClick={handleListen}
            className={cn(
              "mb-1 flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11px] font-semibold transition-colors",
              listening
                ? "bg-orange-600 text-white hover:bg-orange-700"
                : "bg-orange-500 text-white hover:bg-orange-600",
            )}
          >
            {listening ? (
              <>
                <MorphLoader className="size-3" />
                Listening... (cancelar)
              </>
            ) : (
              <>
                <Radio className="size-3" />
                Listen for test event
              </>
            )}
          </button>
        ) : null}
      </div>

      {tab === "params" ? (
        <div className="space-y-4">
          {/* Webhook URLs section */}
          <div className="space-y-2">
            <button
              type="button"
              onClick={() => setShowUrlsSection((v) => !v)}
              className="flex w-full items-center justify-between text-xs font-semibold text-foreground"
            >
              <span className="flex items-center gap-1.5">
                {showUrlsSection ? (
                  <ChevronDown className="size-3.5" />
                ) : (
                  <ChevronRight className="size-3.5" />
                )}
                Webhook URLs
              </span>
            </button>

            {showUrlsSection ? (
              <div className="space-y-2 pl-4">
                <div className="inline-flex rounded-md border border-border bg-muted/30 p-0.5">
                  <button
                    type="button"
                    onClick={() => setUrlsTab("test")}
                    className={cn(
                      "rounded px-2.5 py-0.5 text-[11px] font-semibold transition-colors",
                      urlsTab === "test"
                        ? "bg-background text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    Test URL
                  </button>
                  <button
                    type="button"
                    onClick={() => setUrlsTab("prod")}
                    className={cn(
                      "rounded px-2.5 py-0.5 text-[11px] font-semibold transition-colors",
                      urlsTab === "prod"
                        ? "bg-background text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    Production URL
                  </button>
                </div>
                <UrlCard
                  method={displayedMethod}
                  url={displayedUrl}
                  kind={urlsTab}
                  loading={urlsLoading && !urls}
                />
                {urlsTab === "prod" && urls && !urls.production_ready ? (
                  <p className="text-[11px] leading-relaxed text-muted-foreground">
                    Disponível quando o workflow estiver em <strong>Produção</strong> e{" "}
                    <strong>Publicado</strong>.
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>

          {listenError ? (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 p-2 text-[11px] text-destructive">
              {listenError}
            </div>
          ) : null}

          {/* HTTP Method */}
          <Field label="HTTP Method">
            <Select<HttpMethod>
              value={httpMethod}
              onChange={(v) => updateField("http_method", v)}
              options={METHOD_OPTIONS.map((m) => ({ value: m, label: m }))}
            />
          </Field>

          {/* Path */}
          <Field label="Path">
            <TextField
              value={path}
              onChange={(v) => updateField("path", v.trim() === "" ? null : v.trim())}
              placeholder={workflowId}
            />
          </Field>

          {/* Authentication */}
          <Field label="Autenticação">
            <Select<AuthType>
              value={auth.type}
              onChange={(v) => updateAuth({ type: v })}
              options={AUTH_OPTIONS}
            />
          </Field>

          {auth.type === "header" ? (
            <>
              <Field label="Nome do header">
                <TextField
                  value={auth.header_name ?? ""}
                  onChange={(v) => updateAuth({ header_name: v })}
                  placeholder="X-Webhook-Secret"
                />
              </Field>
              <Field label="Valor do header">
                <PasswordField
                  value={auth.header_value ?? ""}
                  onChange={(v) => updateAuth({ header_value: v })}
                  placeholder="********"
                />
              </Field>
            </>
          ) : null}

          {auth.type === "basic" ? (
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
                  placeholder="********"
                />
              </Field>
            </>
          ) : null}

          {auth.type === "jwt" ? (
            <>
              <Field label="Segredo JWT">
                <PasswordField
                  value={auth.jwt_secret ?? ""}
                  onChange={(v) => updateAuth({ jwt_secret: v })}
                  placeholder="segredo"
                />
              </Field>
              <Field label="Algoritmo">
                <Select<string>
                  value={auth.jwt_algorithm ?? "HS256"}
                  onChange={(v) => updateAuth({ jwt_algorithm: v })}
                  options={[
                    { value: "HS256", label: "HS256" },
                    { value: "HS384", label: "HS384" },
                    { value: "HS512", label: "HS512" },
                    { value: "RS256", label: "RS256" },
                  ]}
                />
              </Field>
            </>
          ) : null}

          {/* Respond */}
          <Field label="Respond">
            <Select<RespondMode>
              value={respondMode}
              onChange={(v) => updateField("respond_mode", v)}
              options={RESPOND_OPTIONS}
            />
          </Field>

          {/* Options (collapsible) */}
          <div className="space-y-2 border-t border-border pt-3">
            <button
              type="button"
              onClick={() => setShowOptions((v) => !v)}
              className="flex w-full items-center gap-1.5 text-xs font-semibold text-foreground"
            >
              {showOptions ? (
                <ChevronDown className="size-3.5" />
              ) : (
                <ChevronRight className="size-3.5" />
              )}
              Options
            </button>
            {showOptions ? (
              <div className="space-y-3 pl-4">
                <Field label="Response Code">
                  <TextField
                    type="number"
                    value={String(responseCode)}
                    onChange={(v) => {
                      const n = Number(v)
                      if (Number.isFinite(n)) updateField("response_code", n)
                    }}
                  />
                </Field>
                <Field label="Response Data">
                  <Select<ResponseData>
                    value={responseData}
                    onChange={(v) => updateField("response_data", v)}
                    options={RESPONSE_DATA_OPTIONS}
                  />
                </Field>
                <Switch
                  checked={rawBody}
                  onChange={(v) => updateField("raw_body", v)}
                  label="Raw body (sem parse JSON)"
                  disabled={httpMethod === "GET" || httpMethod === "HEAD"}
                />
                <Field label="Allowed Origins (CORS)">
                  <TextField
                    value={allowedOrigins}
                    onChange={(v) => updateField("allowed_origins", v || null)}
                    placeholder="* ou https://app.exemplo.com"
                  />
                </Field>
              </div>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-xs leading-relaxed text-muted-foreground">
            As configurações de agendamento, política de retentativa e workspace por
            nó virão em uma próxima fase. Use a aba <strong>Parameters</strong> para
            configurar o webhook.
          </p>
        </div>
      )}
    </div>
  )
}
