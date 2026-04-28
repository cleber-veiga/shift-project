"use client"

import { useCallback, useEffect, useMemo, useState } from "react"

// ─── Tipos ────────────────────────────────────────────────────────────────────

type ScheduleKind =
  | "every_5_min"
  | "every_10_min"
  | "every_15_min"
  | "every_30_min"
  | "every_hour"
  | "every_2_hours"
  | "every_3_hours"
  | "every_6_hours"
  | "specific_time"

type Weekday = "SUN" | "MON" | "TUE" | "WED" | "THU" | "FRI" | "SAT"

type CronFormState = {
  schedule_kind: ScheduleKind
  specific_hour: number
  specific_minute: number
  all_weekdays: boolean
  weekdays: Weekday[]
  all_months: boolean
  months: number[]
  all_month_days: boolean
  month_days: number[]
  timezone: string
}

// ─── Constantes ───────────────────────────────────────────────────────────────

const WEEKDAYS: Array<{ value: Weekday; label: string; cronIdx: number }> = [
  { value: "SUN", label: "DOM", cronIdx: 0 },
  { value: "MON", label: "SEG", cronIdx: 1 },
  { value: "TUE", label: "TER", cronIdx: 2 },
  { value: "WED", label: "QUA", cronIdx: 3 },
  { value: "THU", label: "QUI", cronIdx: 4 },
  { value: "FRI", label: "SEX", cronIdx: 5 },
  { value: "SAT", label: "SAB", cronIdx: 6 },
]

const MONTHS: Array<{ value: number; label: string }> = [
  { value: 1, label: "Janeiro" },
  { value: 2, label: "Fevereiro" },
  { value: 3, label: "Março" },
  { value: 4, label: "Abril" },
  { value: 5, label: "Maio" },
  { value: 6, label: "Junho" },
  { value: 7, label: "Julho" },
  { value: 8, label: "Agosto" },
  { value: 9, label: "Setembro" },
  { value: 10, label: "Outubro" },
  { value: 11, label: "Novembro" },
  { value: 12, label: "Dezembro" },
]

const MONTH_DAYS = Array.from({ length: 31 }, (_, i) => i + 1)

const SCHEDULE_OPTIONS: Array<{ value: ScheduleKind; label: string }> = [
  { value: "every_5_min", label: "A cada 5 minutos" },
  { value: "every_10_min", label: "A cada 10 minutos" },
  { value: "every_15_min", label: "A cada 15 minutos" },
  { value: "every_30_min", label: "A cada 30 minutos" },
  { value: "every_hour", label: "A cada hora" },
  { value: "every_2_hours", label: "A cada 2 horas" },
  { value: "every_3_hours", label: "A cada 3 horas" },
  { value: "every_6_hours", label: "A cada 6 horas" },
  { value: "specific_time", label: "Horário específico" },
]

const TIMEZONE_OPTIONS = [
  "America/Sao_Paulo",
  "America/New_York",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Lisbon",
  "UTC",
]

const DEFAULT_FORM: CronFormState = {
  schedule_kind: "every_5_min",
  specific_hour: 9,
  specific_minute: 0,
  all_weekdays: true,
  weekdays: ["MON", "TUE", "WED", "THU", "FRI"],
  all_months: true,
  months: [],
  all_month_days: true,
  month_days: [],
  timezone: "America/Sao_Paulo",
}

// ─── Geração / parsing ────────────────────────────────────────────────────────

function buildCronExpression(form: CronFormState): string {
  let minute = "*"
  let hour = "*"

  switch (form.schedule_kind) {
    case "every_5_min": minute = "*/5"; break
    case "every_10_min": minute = "*/10"; break
    case "every_15_min": minute = "*/15"; break
    case "every_30_min": minute = "*/30"; break
    case "every_hour": minute = "0"; break
    case "every_2_hours": minute = "0"; hour = "*/2"; break
    case "every_3_hours": minute = "0"; hour = "*/3"; break
    case "every_6_hours": minute = "0"; hour = "*/6"; break
    case "specific_time":
      minute = String(form.specific_minute)
      hour = String(form.specific_hour)
      break
  }

  const dayOfMonth = form.all_month_days
    ? "*"
    : form.month_days.slice().sort((a, b) => a - b).join(",") || "*"
  const month = form.all_months
    ? "*"
    : form.months.slice().sort((a, b) => a - b).join(",") || "*"
  const dayOfWeek = form.all_weekdays
    ? "*"
    : form.weekdays
        .map((w) => WEEKDAYS.find((x) => x.value === w)?.cronIdx ?? 0)
        .sort((a, b) => a - b)
        .join(",") || "*"

  return `${minute} ${hour} ${dayOfMonth} ${month} ${dayOfWeek}`
}

// ─── Próximas execuções (previsão local) ──────────────────────────────────────

type FieldMatcher =
  | { type: "any" }
  | { type: "value"; value: number }
  | { type: "step"; step: number }
  | { type: "list"; values: Set<number> }

function parseField(raw: string): FieldMatcher {
  const s = raw.trim()
  if (!s || s === "*") return { type: "any" }
  if (s.startsWith("*/")) {
    const step = Number(s.slice(2))
    return Number.isFinite(step) && step > 0 ? { type: "step", step } : { type: "any" }
  }
  if (s.includes(",")) {
    const values = new Set<number>()
    for (const tok of s.split(",")) {
      const n = Number(tok.trim())
      if (Number.isFinite(n)) values.add(n)
    }
    return values.size ? { type: "list", values } : { type: "any" }
  }
  const n = Number(s)
  return Number.isFinite(n) ? { type: "value", value: n } : { type: "any" }
}

function matches(m: FieldMatcher, v: number) {
  if (m.type === "any") return true
  if (m.type === "value") return m.value === v
  if (m.type === "step") return v % m.step === 0
  return m.values.has(v)
}

function nextExecutions(expression: string, count: number): Date[] {
  const parts = expression.trim().split(/\s+/)
  if (parts.length !== 5) return []

  const [minF, hourF, domF, monF, dowF] = parts.map(parseField)
  const out: Date[] = []
  const cursor = new Date()
  cursor.setSeconds(0, 0)
  cursor.setMinutes(cursor.getMinutes() + 1)

  const limit = 100_000
  for (let i = 0; i < limit && out.length < count; i += 1) {
    const ok =
      matches(minF, cursor.getMinutes()) &&
      matches(hourF, cursor.getHours()) &&
      matches(domF, cursor.getDate()) &&
      matches(monF, cursor.getMonth() + 1) &&
      matches(dowF, cursor.getDay())
    if (ok) out.push(new Date(cursor))
    cursor.setMinutes(cursor.getMinutes() + 1)
  }
  return out
}

// ─── Componente ───────────────────────────────────────────────────────────────

interface CronConfigProps {
  data: Record<string, unknown>
  onUpdate: (patch: Record<string, unknown>) => void
}

export function CronConfig({ data, onUpdate }: CronConfigProps) {
  const [tab, setTab] = useState<"params" | "next">("params")

  // Carrega estado do data (com defaults). Campos extras sao persistidos junto
  // com cron_expression e timezone no data do no, permitindo reabrir o editor.
  const [form, setForm] = useState<CronFormState>(() => ({
    schedule_kind: (data.schedule_kind as ScheduleKind) ?? DEFAULT_FORM.schedule_kind,
    specific_hour:
      typeof data.specific_hour === "number" ? data.specific_hour : DEFAULT_FORM.specific_hour,
    specific_minute:
      typeof data.specific_minute === "number"
        ? data.specific_minute
        : DEFAULT_FORM.specific_minute,
    all_weekdays:
      typeof data.all_weekdays === "boolean" ? data.all_weekdays : DEFAULT_FORM.all_weekdays,
    weekdays: Array.isArray(data.weekdays)
      ? (data.weekdays as Weekday[])
      : DEFAULT_FORM.weekdays,
    all_months:
      typeof data.all_months === "boolean" ? data.all_months : DEFAULT_FORM.all_months,
    months: Array.isArray(data.months) ? (data.months as number[]) : DEFAULT_FORM.months,
    all_month_days:
      typeof data.all_month_days === "boolean"
        ? data.all_month_days
        : DEFAULT_FORM.all_month_days,
    month_days: Array.isArray(data.month_days)
      ? (data.month_days as number[])
      : DEFAULT_FORM.month_days,
    timezone: (data.timezone as string) ?? DEFAULT_FORM.timezone,
  }))

  const expression = useMemo(() => buildCronExpression(form), [form])
  const previews = useMemo(() => nextExecutions(expression, 5), [expression])

  const errors = useMemo(() => {
    const out: string[] = []
    if (!form.all_weekdays && form.weekdays.length === 0)
      out.push("Selecione ao menos um dia da semana.")
    if (!form.all_months && form.months.length === 0)
      out.push("Selecione ao menos um mês.")
    if (!form.all_month_days && form.month_days.length === 0)
      out.push("Selecione ao menos um dia do mês.")
    if (form.schedule_kind === "specific_time") {
      if (form.specific_hour < 0 || form.specific_hour > 23)
        out.push("Hora deve estar entre 0 e 23.")
      if (form.specific_minute < 0 || form.specific_minute > 59)
        out.push("Minuto deve estar entre 0 e 59.")
    }
    return out
  }, [form])

  // Sincroniza o form para o data do no (mantem a expressao cron + todos os campos)
  useEffect(() => {
    if (errors.length > 0) return
    onUpdate({
      cron_expression: expression,
      timezone: form.timezone,
      schedule_kind: form.schedule_kind,
      specific_hour: form.specific_hour,
      specific_minute: form.specific_minute,
      all_weekdays: form.all_weekdays,
      weekdays: form.weekdays,
      all_months: form.all_months,
      months: form.months,
      all_month_days: form.all_month_days,
      month_days: form.month_days,
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expression, form])

  const timeValue = useMemo(() => {
    const hh = String(form.specific_hour).padStart(2, "0")
    const mm = String(form.specific_minute).padStart(2, "0")
    return `${hh}:${mm}`
  }, [form.specific_hour, form.specific_minute])

  const toggleWeekday = useCallback((w: Weekday) => {
    setForm((prev) => ({
      ...prev,
      weekdays: prev.weekdays.includes(w)
        ? prev.weekdays.filter((x) => x !== w)
        : [...prev.weekdays, w],
    }))
  }, [])

  const toggleMonth = useCallback((m: number) => {
    setForm((prev) => ({
      ...prev,
      months: prev.months.includes(m)
        ? prev.months.filter((x) => x !== m)
        : [...prev.months, m],
    }))
  }, [])

  const toggleDay = useCallback((d: number) => {
    setForm((prev) => ({
      ...prev,
      month_days: prev.month_days.includes(d)
        ? prev.month_days.filter((x) => x !== d)
        : [...prev.month_days, d],
    }))
  }, [])

  return (
    <div className="space-y-4">
      {/* Abas */}
      <div className="flex items-center gap-4 border-b border-border">
        <button
          type="button"
          onClick={() => setTab("params")}
          className={`-mb-px px-1 pb-2 text-xs font-semibold transition-colors ${
            tab === "params"
              ? "border-b-2 border-primary text-foreground"
              : "border-b-2 border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          Parâmetros
        </button>
        <button
          type="button"
          onClick={() => setTab("next")}
          className={`-mb-px px-1 pb-2 text-xs font-semibold transition-colors ${
            tab === "next"
              ? "border-b-2 border-primary text-foreground"
              : "border-b-2 border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          Próximas execuções
        </button>
      </div>

      {tab === "params" ? (
        <div className="space-y-4">
          {/* Frequência */}
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Frequência
            </label>
            <select
              value={form.schedule_kind}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, schedule_kind: e.target.value as ScheduleKind }))
              }
              className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
            >
              {SCHEDULE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Horário específico */}
          {form.schedule_kind === "specific_time" ? (
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Horário
              </label>
              <input
                type="time"
                value={timeValue}
                onChange={(e) => {
                  const [hh, mm] = e.target.value.split(":").map(Number)
                  setForm((prev) => ({
                    ...prev,
                    specific_hour: Number.isFinite(hh) ? hh : prev.specific_hour,
                    specific_minute: Number.isFinite(mm) ? mm : prev.specific_minute,
                  }))
                }}
                className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
          ) : null}

          {/* Timezone */}
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Fuso horário
            </label>
            <select
              value={form.timezone}
              onChange={(e) => setForm((prev) => ({ ...prev, timezone: e.target.value }))}
              className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
            >
              {TIMEZONE_OPTIONS.map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
          </div>

          {/* Dias da semana */}
          <div className="space-y-2 border-t border-border pt-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-foreground">Dias da semana</span>
              <label className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={form.all_weekdays}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, all_weekdays: e.target.checked }))
                  }
                  className="size-3.5 rounded border-input accent-primary"
                />
                Toda a semana
              </label>
            </div>
            <div className="grid grid-cols-7 gap-1">
              {WEEKDAYS.map((d) => {
                const selected = form.weekdays.includes(d.value)
                const disabled = form.all_weekdays
                return (
                  <button
                    key={d.value}
                    type="button"
                    disabled={disabled}
                    onClick={() => toggleWeekday(d.value)}
                    className={`h-8 rounded-md border text-[10px] font-semibold transition-colors ${
                      disabled
                        ? "cursor-not-allowed border-border bg-background/40 text-muted-foreground/60"
                        : selected
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-border bg-background text-foreground hover:bg-accent/40"
                    }`}
                  >
                    {d.label}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Meses */}
          <div className="space-y-2 border-t border-border pt-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-foreground">Meses</span>
              <label className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={form.all_months}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, all_months: e.target.checked }))
                  }
                  className="size-3.5 rounded border-input accent-primary"
                />
                Todos os meses
              </label>
            </div>
            <div className="grid grid-cols-2 gap-1">
              {MONTHS.map((m) => {
                const selected = form.months.includes(m.value)
                const disabled = form.all_months
                return (
                  <button
                    key={m.value}
                    type="button"
                    disabled={disabled}
                    onClick={() => toggleMonth(m.value)}
                    className={`h-8 rounded-md border px-2 text-left text-[11px] font-semibold transition-colors ${
                      disabled
                        ? "cursor-not-allowed border-border bg-background/40 text-muted-foreground/60"
                        : selected
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-border bg-background text-foreground hover:bg-accent/40"
                    }`}
                  >
                    {m.label}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Dias do mês */}
          <div className="space-y-2 border-t border-border pt-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-foreground">Dias do mês</span>
              <label className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={form.all_month_days}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, all_month_days: e.target.checked }))
                  }
                  className="size-3.5 rounded border-input accent-primary"
                />
                Todos os dias
              </label>
            </div>
            <div className="grid grid-cols-7 gap-1">
              {MONTH_DAYS.map((d) => {
                const selected = form.month_days.includes(d)
                const disabled = form.all_month_days
                return (
                  <button
                    key={d}
                    type="button"
                    disabled={disabled}
                    onClick={() => toggleDay(d)}
                    className={`h-8 rounded-md border text-[10px] font-semibold transition-colors ${
                      disabled
                        ? "cursor-not-allowed border-border bg-background/40 text-muted-foreground/60"
                        : selected
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-border bg-background text-foreground hover:bg-accent/40"
                    }`}
                  >
                    {d}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Expressão gerada (info) */}
          <div className="rounded-lg border border-dashed border-sky-500/30 bg-sky-500/5 p-3">
            <p className="text-[11px] font-medium text-sky-600 dark:text-sky-400">
              Expressão gerada
            </p>
            <code className="mt-1 block font-mono text-[11px] text-foreground">
              {expression}
            </code>
            <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
              Agendamento fica <strong>ativo</strong> somente quando o workflow
              está em <strong>Produção</strong>.
            </p>
          </div>

          {errors.length > 0 ? (
            <div className="space-y-1 rounded-lg border border-destructive/30 bg-destructive/5 p-2">
              {errors.map((err) => (
                <p key={err} className="text-[11px] text-destructive">
                  {err}
                </p>
              ))}
            </div>
          ) : null}
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-[11px] text-muted-foreground">
            Próximas 5 execuções (hora local do seu navegador):
          </p>
          <div className="rounded-lg border border-border bg-background p-2">
            {previews.length ? (
              <ol className="space-y-1">
                {previews.map((date, idx) => (
                  <li
                    key={date.toISOString()}
                    className="flex items-center gap-2 font-mono text-[11px] text-foreground"
                  >
                    <span className="w-5 text-muted-foreground">
                      {String(idx + 1).padStart(2, "0")}
                    </span>
                    <span>
                      {new Intl.DateTimeFormat("pt-BR", {
                        dateStyle: "full",
                        timeStyle: "short",
                      }).format(date)}
                    </span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-xs text-muted-foreground">
                Sem previsões com os parâmetros atuais.
              </p>
            )}
          </div>
          <p className="text-[11px] text-muted-foreground">
            O agendador dispara no fuso{" "}
            <code className="font-mono text-foreground">{form.timezone}</code>.
            A lista acima converte para a sua hora local.
          </p>
        </div>
      )}
    </div>
  )
}
