import { Loader2, X } from 'lucide-react'
import { Line, LineChart, ResponsiveContainer } from 'recharts'
import { useData } from '../context/DataContext'
import { fmtDate } from '../lib/format'

const TONES = {
  green: 'bg-ok-soft text-ok',
  amber: 'bg-warn-soft text-warn',
  red: 'bg-crit-soft text-crit',
  blue: 'bg-brand-soft text-brand-dark',
  violet: 'bg-violet-soft text-violet',
  grey: 'bg-slate-100 text-slate-600',
}

export function Badge({ tone = 'grey', children, className = '' }) {
  return (
    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold ${TONES[tone]} ${className}`}>
      {children}
    </span>
  )
}

const STATUS_TONE = {
  surplus: ['green', 'Surplus'],
  ok: ['green', 'Healthy'],
  acknowledged: ['amber', 'Acknowledged'],
  warning: ['amber', 'Warning'],
  critical: ['red', 'Critical'],
  emergency: ['red', 'Emergency'],
  info: ['blue', 'Info'],
  settled: ['green', 'Settled'],
  pending: ['amber', 'Pending'],
  overdue: ['red', 'Overdue'],
  failed: ['red', 'Failed'],
  open: ['blue', 'Open'],
  resolved: ['green', 'Resolved'],
  active: ['green', 'Active'],
  suspended: ['red', 'Suspended'],
  inflow: ['green', 'Inflow'],
  outflow: ['red', 'Outflow'],
}

export function StatusBadge({ status }) {
  const [tone, label] = STATUS_TONE[String(status).toLowerCase()] || ['grey', status]
  return <Badge tone={tone}>{label}</Badge>
}

const RATING_TONE = { A: 'green', B: 'blue', C: 'amber', D: 'red' }
export function RatingBadge({ rating }) {
  return (
    <span
      className={`inline-flex h-6 w-6 items-center justify-center rounded-md text-xs font-bold ${TONES[RATING_TONE[rating]]}`}
      title={`Rating ${rating}`}
    >
      {rating}
    </span>
  )
}

export function Card({ title, subtitle, action, children, className = '', pad = true }) {
  return (
    <section className={`card ${className}`}>
      {(title || action) && (
        <div className="flex flex-wrap items-start justify-between gap-2 px-5 pt-4">
          <div>
            {title && <h3 className="text-[15px] font-bold text-ink">{title}</h3>}
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {action}
        </div>
      )}
      <div className={pad ? 'p-5' : ''}>{children}</div>
    </section>
  )
}

export function PageHeader({ title, description, children }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-muted">{description}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  )
}

const KPI_ACCENT = { blue: 'bg-brand-soft text-brand', green: 'bg-ok-soft text-ok', red: 'bg-crit-soft text-crit', amber: 'bg-warn-soft text-warn', violet: 'bg-violet-soft text-violet' }
export function KpiCard({ label, value, note, noteTone = 'muted', icon: Icon, accent = 'blue' }) {
  const noteColor = { muted: 'text-muted', green: 'text-ok', red: 'text-crit', amber: 'text-warn' }[noteTone]
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-semibold text-muted">{label}</p>
        {Icon && (
          <span className={`flex h-8 w-8 items-center justify-center rounded-lg ${KPI_ACCENT[accent]}`}>
            <Icon size={16} />
          </span>
        )}
      </div>
      <p className="mt-2 font-heading text-2xl font-extrabold tracking-tight text-ink">{value}</p>
      {note && <p className={`mt-1 text-xs font-medium ${noteColor}`}>{note}</p>}
    </div>
  )
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="mb-4 flex gap-1 overflow-x-auto border-b border-line" role="tablist">
      {tabs.map((t) => (
        <button
          key={t}
          role="tab"
          aria-selected={value === t}
          onClick={() => onChange(t)}
          className={`whitespace-nowrap border-b-2 px-3.5 py-2.5 text-sm font-semibold transition-colors ${
            value === t ? 'border-brand text-brand' : 'border-transparent text-muted hover:text-ink'
          }`}
        >
          {t}
        </button>
      ))}
    </div>
  )
}

export function Select({ value, onChange, options, label, className = '' }) {
  return (
    <label className={className}>
      {label && <span className="label">{label}</span>}
      <select className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => {
          const v = typeof o === 'string' ? o : o.value
          const l = typeof o === 'string' ? o : o.label
          return <option key={v} value={v}>{l}</option>
        })}
      </select>
    </label>
  )
}

export function Toggle({ checked, onChange, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${checked ? 'bg-brand' : 'bg-slate-300'}`}
    >
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${checked ? 'left-[22px]' : 'left-0.5'}`} />
    </button>
  )
}

export function Modal({ open, title, onClose, children, footer }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy/50 p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="card w-full max-w-md shadow-pop">
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <h3 className="text-base font-bold">{title}</h3>
          <button onClick={onClose} className="rounded p-1 text-muted hover:bg-surface" aria-label="Close dialog">
            <X size={18} />
          </button>
        </div>
        <div className="space-y-4 p-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3.5">{footer}</div>}
      </div>
    </div>
  )
}

export function Sparkline({ data = [], color = '#DC2626' }) {
  const rows = data.map((v, i) => ({ i, v }))
  return (
    <div className="h-6 w-20">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows}>
          <Line type="monotone" dataKey="v" stroke={color} strokeWidth={1.75} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export function Notice({ tone = 'blue', icon: Icon, children }) {
  return (
    <div className={`flex items-start gap-2.5 rounded-lg px-3.5 py-2.5 text-sm ${TONES[tone]}`}>
      {Icon && <Icon size={16} className="mt-0.5 shrink-0" />}
      <div>{children}</div>
    </div>
  )
}

// Shows the forecast "as of" date (the dataset is historical, so "today" is configurable on the server).
export function DemoTag() {
  const { asOf, refreshing } = useData() || {}
  if (refreshing) return <Badge tone="violet"><Loader2 size={12} className="mr-1 animate-spin" /> Updating forecast…</Badge>
  return <Badge tone="violet">Live data · as of {fmtDate(asOf)}</Badge>
}

export function Loading({ label = 'Loading…' }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted">
      <Loader2 size={18} className="animate-spin" /> {label}
    </div>
  )
}

export function ErrorNotice({ error }) {
  if (!error) return null
  return <Notice tone="red">{String(error)}</Notice>
}

export const chartTooltipStyle = {
  contentStyle: { borderRadius: 10, border: '1px solid #E3E9F2', boxShadow: '0 8px 24px rgba(16,28,45,0.12)', fontSize: 12 },
  labelStyle: { fontWeight: 700, color: '#0F1B2D' },
}
