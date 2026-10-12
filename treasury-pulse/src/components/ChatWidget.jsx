import { useEffect, useMemo, useRef, useState } from 'react'
import { Bot, Minus, RotateCcw, Send, Sparkles, X } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useChat } from '../hooks/useChat'
import { useAuth } from '../context/AuthContext'
import { useLocation } from 'react-router-dom'
import { compact } from '../lib/format'

export const SUGGESTIONS = [
  'Which entities face a shortfall?',
  'Summarise the 30-day forecast',
  'What if we delay payments by 3 days in New York?',
  'Any counterparty concerns?',
  'Where is idle cash we could deploy?',
]

const SERIES_COLORS = ['#3478F6', '#7C6BD6', '#94A3B8']
const BAND_KEYS = new Set(['lower', 'upper'])
const tick = { fontSize: 10, fill: '#64748B' }
const yTick = (v) => (Math.abs(v) < 10 && v !== 0 ? Number(v).toFixed(2) : compact(v))
const fmtTick = (v) => (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v.slice(5) : v)

/** Small chart for an assistant answer. Spec from server/copilot: {type, title, xKey, series, data, threshold?, signed?} */
export function ChatChart({ spec }) {
  const data = spec?.data || []
  const longLabels = useMemo(() => data.some((d) => String(d[spec.xKey] ?? '').length > 8 && !/^\d{4}-/.test(String(d[spec.xKey]))), [data, spec])
  if (!data.length || !spec.series?.length) return null
  const common = (
    <>
      <CartesianGrid stroke="#E3E9F2" strokeDasharray="3 3" vertical={false} />
      <XAxis dataKey={spec.xKey} tick={tick} tickFormatter={fmtTick} tickLine={false} interval="preserveStartEnd"
        angle={longLabels ? -35 : 0} textAnchor={longLabels ? 'end' : 'middle'} height={longLabels ? 46 : 22} />
      <YAxis tick={tick} tickFormatter={yTick} width={46} tickLine={false} axisLine={false} domain={['auto', 'auto']} />
      <Tooltip formatter={(v, n) => [typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: 3 }) : v, n]}
        contentStyle={{ fontSize: 11, borderRadius: 8, border: '1px solid #E3E9F2' }} />
      {spec.threshold != null && <ReferenceLine y={spec.threshold} stroke="#DC2626" strokeDasharray="4 4" />}
      {spec.signed && <ReferenceLine y={0} stroke="#94A3B8" />}
    </>
  )
  return (
    <figure className="mt-2 w-full rounded-xl border border-line bg-white p-2.5">
      <figcaption className="mb-1 text-[11px] font-semibold text-muted">{spec.title}</figcaption>
      <div className="h-40">
        <ResponsiveContainer width="100%" height="100%">
          {spec.type === 'line' ? (
            <LineChart data={data} margin={{ top: 4, right: 6, left: 0, bottom: 0 }}>
              {common}
              {spec.series.length > 1 && <Legend iconType="plainline" wrapperStyle={{ fontSize: 10 }} />}
              {spec.series.map((s, i) => (
                <Line key={s.key} dataKey={s.key} name={s.label} dot={false} isAnimationActive={false}
                  stroke={BAND_KEYS.has(s.key) ? '#94A3B8' : SERIES_COLORS[i] || '#3478F6'}
                  strokeWidth={BAND_KEYS.has(s.key) ? 1 : 2}
                  strokeDasharray={BAND_KEYS.has(s.key) ? '3 3' : s.key === 'scenario' ? '6 4' : undefined} />
              ))}
            </LineChart>
          ) : (
            <BarChart data={data} margin={{ top: 4, right: 6, left: 0, bottom: 0 }}>
              {common}
              <Bar dataKey={spec.series[0].key} name={spec.series[0].label} isAnimationActive={false}>
                {data.map((d, i) => (
                  <Cell key={i} fill={spec.signed ? (d[spec.series[0].key] >= 0 ? '#16A34A' : '#DC2626') : '#3478F6'} />
                ))}
              </Bar>
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </figure>
  )
}

/** Message list + input, shared by the floating widget and the AI Assistant page. */
export function ChatBody({ chat, className = '', suggestions = SUGGESTIONS }) {
  const [draft, setDraft] = useState('')
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [chat.messages, chat.loading])

  const submit = (e) => {
    e.preventDefault()
    if (!draft.trim()) return
    chat.send(draft)
    setDraft('')
  }

  return (
    <div className={`flex min-h-0 flex-1 flex-col ${className}`}>
      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4" aria-live="polite">
        {chat.messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`flex max-w-[92%] flex-col ${m.role === 'user' ? 'items-end' : 'items-start'}`}>
              <div
                className={`whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
                  m.role === 'user' ? 'rounded-br-md bg-brand text-white' : 'rounded-bl-md bg-slate-100 text-ink'
                }`}
              >
                {m.content}
              </div>
              {m.visualization && <ChatChart spec={m.visualization} />}
              {m.role === 'assistant' && i > 0 && (
                <span className="mt-1 text-[10px] text-muted">{m.llmUsed ? `Live data · phrased by ${m.model}` : 'Live data'}</span>
              )}
            </div>
          </div>
        ))}
        {chat.loading && (
          <div className="flex justify-start" aria-label="Assistant is typing">
            <div className="flex gap-1 rounded-2xl rounded-bl-md bg-slate-100 px-3.5 py-3">
              {[0, 1, 2].map((d) => (
                <span key={d} className="typing-dot h-1.5 w-1.5 rounded-full bg-slate2" style={{ animationDelay: `${d * 0.15}s` }} />
              ))}
            </div>
          </div>
        )}
        {chat.error && <p className="rounded-lg bg-crit-soft px-3 py-2 text-xs font-medium text-crit">{chat.error}</p>}
        {chat.messages.length === 1 && !chat.loading && (
          <div className="flex flex-wrap gap-2 pt-1">
            {suggestions.map((s) => (
              <button
                key={s}
                onClick={() => chat.send(s)}
                className="rounded-full border border-line bg-white px-3 py-1.5 text-xs font-semibold text-slate2 hover:border-brand hover:text-brand"
              >
                {s}
              </button>
            ))}
          </div>
        )}
        <div ref={endRef} />
      </div>
      <form onSubmit={submit} className="flex items-center gap-2 border-t border-line p-3">
        <input
          className="input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask about liquidity, alerts, forecasts…"
          aria-label="Message to Pulse Assistant"
        />
        <button type="submit" className="btn-primary h-9 w-9 shrink-0 !p-0" disabled={!draft.trim() || chat.loading} aria-label="Send message">
          <Send size={16} />
        </button>
      </form>
    </div>
  )
}

/**
 * Floating assistant at bottom-right.
 * Backend: askAssistant() in src/services/api.js -> server/copilot.
 */
export default function ChatWidget() {
  const [open, setOpen] = useState(false)
  const { role } = useAuth()
  const { pathname, search } = useLocation()
  const entityId = new URLSearchParams(search).get('entity') || undefined
  const chat = useChat({ role, page: pathname, entity_id: entityId })

  // The full AI Assistant page already has a chat, so hide the floating one there
  if (pathname === '/assistant') return null

  return (
    <div className="no-print fixed bottom-5 right-5 z-40 flex flex-col items-end gap-3">
      {open && (
        <div
          className="chat-pop flex h-[min(520px,calc(100vh-7rem))] w-[calc(100vw-2.5rem)] max-w-[370px] flex-col overflow-hidden rounded-2xl border border-line bg-white shadow-pop"
          role="dialog"
          aria-label="Pulse Assistant"
        >
          <div className="flex items-center justify-between bg-navy px-4 py-3 text-white">
            <div className="flex items-center gap-2.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand">
                <Sparkles size={16} />
              </span>
              <div>
                <p className="font-heading text-sm font-bold leading-tight">Pulse Assistant</p>
                <p className="text-[11px] text-slate-300">Live treasury data · your entity scope</p>
              </div>
            </div>
            <div className="flex items-center gap-0.5">
              <button onClick={chat.reset} className="rounded p-1.5 text-slate-300 hover:bg-white/10" aria-label="Clear conversation">
                <RotateCcw size={15} />
              </button>
              <button onClick={() => setOpen(false)} className="rounded p-1.5 text-slate-300 hover:bg-white/10" aria-label="Minimise chat">
                <Minus size={16} />
              </button>
            </div>
          </div>
          <ChatBody chat={chat} />
        </div>
      )}
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex h-14 w-14 items-center justify-center rounded-full bg-brand text-white shadow-pop transition-colors hover:bg-brand-dark"
        aria-label={open ? 'Close Pulse Assistant' : 'Open Pulse Assistant'}
        aria-expanded={open}
      >
        {open ? <X size={22} /> : <Bot size={24} />}
      </button>
    </div>
  )
}
