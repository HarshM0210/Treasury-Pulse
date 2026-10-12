import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Area, CartesianGrid, Cell, ComposedChart, Legend, Line, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Banknote, CalendarClock, FlaskConical, ShieldAlert, Users } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { useData } from '../context/DataContext'
import * as api from '../services/api'
import { CCY_COLORS, compact, fmtDate, fmtDay, isAtRisk, money, signedMoney } from '../lib/format'
import { Badge, Card, chartTooltipStyle, DemoTag, ErrorNotice, KpiCard, Loading, PageHeader, Select, StatusBadge } from '../components/ui'

// Joins history (≤ as_of) and forecast (> as_of) into one chart series.
export function joinSeries(history = [], forecast = [], asOf) {
  const rows = history.map((h) => ({ date: fmtDay(h.date), iso: h.date, actual: h.actual, forecast: null, band: null }))
  const last = rows.find((r) => r.iso === asOf) || rows[rows.length - 1]
  if (last) { last.forecast = last.actual; last.band = [last.actual, last.actual] }
  forecast.forEach((f) => rows.push({ date: fmtDay(f.date), iso: f.date, actual: null, forecast: f.forecast, band: [f.lower ?? f.forecast, f.upper ?? f.forecast] }))
  return rows
}

function CashTrend({ thresholdUsd, asOf }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const { summary } = useData()
  useEffect(() => {
    api.getTotalForecast().then((t) => setData(joinSeries(t.history, t.forecast, t.as_of))).catch((e) => setError(e.message))
  }, [summary?.forecast_run_id])
  return (
    <Card title="Cash position trend" subtitle="USD equivalent · 30 days actual, 30 days Prophet forecast" className="h-full">
      <ErrorNotice error={error} />
      {!data ? <Loading /> : (
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 18, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#E3E9F2" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#64748B' }} interval={7} tickLine={false} />
              <YAxis tickFormatter={(v) => compact(v, 'USD')} tick={{ fontSize: 11, fill: '#64748B' }} width={60} tickLine={false} axisLine={false} domain={['auto', 'auto']} />
              <Tooltip {...chartTooltipStyle} formatter={(v, n) => (Array.isArray(v) ? [`${money(v[0])} – ${money(v[1])}`, n] : [money(v), n])} />
              <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
              <Area dataKey="band" name="Confidence range (80%)" stroke="none" fill="#3478F6" fillOpacity={0.14} connectNulls={false} />
              <Line dataKey="actual" name="Actual" stroke="#3478F6" strokeWidth={2.25} dot={false} connectNulls={false} />
              <Line dataKey="forecast" name="Forecast" stroke="#7C6BD6" strokeWidth={2.25} strokeDasharray="6 4" dot={false} connectNulls={false} />
              <ReferenceLine y={thresholdUsd} stroke="#DC2626" strokeDasharray="4 4" label={{ value: 'Combined threshold', fontSize: 11, fill: '#DC2626', position: 'insideBottomRight' }} />
              <ReferenceLine x={fmtDay(asOf)} stroke="#94A3B8" label={{ value: 'As of', fontSize: 11, fill: '#64748B', position: 'top' }} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  )
}

function CurrencyDonut({ rows }) {
  const total = rows.reduce((a, r) => a + r.value, 0)
  return (
    <Card title="Currency breakdown" subtitle="Share of cash, USD equivalent" className="h-full">
      <div className="flex flex-col items-center gap-4 sm:flex-row lg:flex-col xl:flex-row">
        <div className="relative h-44 w-44 shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={rows} dataKey="value" nameKey="name" innerRadius={56} outerRadius={80} paddingAngle={2} stroke="none">
                {rows.map((r) => <Cell key={r.name} fill={r.color} />)}
              </Pie>
              <Tooltip {...chartTooltipStyle} formatter={(v, n) => [money(v), n]} />
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span className="font-heading text-lg font-extrabold">{compact(total, 'USD')}</span>
            <span className="text-[11px] text-muted">Total</span>
          </div>
        </div>
        <ul className="w-full space-y-2 text-sm">
          {rows.map((r) => (
            <li key={r.name} className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: r.color }} />
              <span className="font-semibold">{r.name}</span>
              <span className="ml-auto tabular-nums text-muted">{r.pct.toFixed(1)}%</span>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  )
}

function useCurrencyBreakdown(rows, toUsd) {
  return useMemo(() => {
    const by = {}
    rows.forEach((e) => { by[e.currency] = (by[e.currency] || 0) + Math.max(0, toUsd(e.balance, e.currency)) })
    const total = Object.values(by).reduce((a, b) => a + b, 0) || 1
    return Object.entries(by).sort((a, b) => b[1] - a[1]).map(([name, value], i) => ({ name, value: Math.round(value), pct: (value / total) * 100, color: CCY_COLORS[i % CCY_COLORS.length] }))
  }, [rows, toUsd])
}

function LiquidityGapTable({ rows, onRow }) {
  return (
    <Card title="Liquidity gap by entity" subtitle="Lowest projected position in the next 30 days − threshold, in the entity's own currency" pad={false}>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              {['Entity', 'Currency', 'Projected position (lowest)', 'Threshold', 'Liquidity gap', 'Status'].map((h) => <th key={h} className="th">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.id} className="cursor-pointer hover:bg-surface" onClick={() => onRow?.(e)}>
                <td className="td font-semibold">{e.code}</td>
                <td className="td">{e.currency}</td>
                <td className="td tabular-nums">{money(e.projected_min, e.currency)}<span className="ml-1 text-xs text-muted">{fmtDay(e.projected_min_date)}</span></td>
                <td className="td tabular-nums text-muted">{money(e.threshold, e.currency)}</td>
                <td className={`td font-semibold tabular-nums ${e.gap < 0 ? 'text-crit' : 'text-ok'}`}>{signedMoney(e.gap, e.currency)}</td>
                <td className="td"><StatusBadge status={e.status} /></td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={6} className="td py-10 text-center text-muted">No entities in your scope yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function PriorityActions({ rows }) {
  const navigate = useNavigate()
  const [cp, setCp] = useState(null)
  const [next, setNext] = useState(null)
  useEffect(() => {
    api.getCounterparties().then((c) => setCp(c.counterparties?.[0] || null)).catch(() => {})
    api.getUpcoming(7, 1).then((u) => setNext(u.events?.[0] || null)).catch(() => {})
  }, [])
  const worst = [...rows].filter((e) => isAtRisk(e.status)).sort((a, b) => a.gap - b.gap)[0]
  const actions = [
    worst
      ? { icon: ShieldAlert, tone: 'text-crit bg-crit-soft', title: 'Liquidity shortfall detected', body: `${worst.code} is projected at ${money(worst.projected_min, worst.currency)} on ${fmtDate(worst.projected_min_date)}, against a ${money(worst.threshold, worst.currency)} threshold.`, cta: 'Review alert', to: '/alerts' }
      : { icon: ShieldAlert, tone: 'text-ok bg-ok-soft', title: 'No shortfall projected', body: 'All entities stay above their threshold for the next 30 days.', cta: 'View alerts', to: '/alerts' },
    { icon: CalendarClock, tone: 'text-warn bg-warn-soft', title: 'Upcoming high-value payment', body: next ? `${next.entity}: ${next.description}, ${money(next.amount, next.currency)} due ${fmtDate(next.date)}.` : 'No large payments due in the next 7 days.', cta: 'View transactions', to: '/transactions' },
    { icon: Users, tone: 'text-warn bg-warn-soft', title: 'Counterparty reliability', body: cp ? `${cp.name} has the highest risk score (${cp.risk_score.toFixed(3)}, rating ${cp.rating}).` : 'Counterparty scores are loading.', cta: 'Open counterparty risk', to: '/counterparty' },
    { icon: FlaskConical, tone: 'text-brand bg-brand-soft', title: 'Test a payment-delay scenario', body: worst ? `See how a 3-day delay changes the ${worst.code} gap.` : 'Stress-test any entity with what-if analysis.', cta: 'Run scenario', to: '/what-if' },
  ]
  return (
    <Card title="Priority actions">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {actions.map(({ icon: Icon, tone, title, body, cta, to }) => (
          <div key={title} className="flex flex-col rounded-lg border border-line p-3.5">
            <span className={`mb-2 flex h-8 w-8 items-center justify-center rounded-lg ${tone}`}><Icon size={16} /></span>
            <p className="text-sm font-bold">{title}</p>
            <p className="mt-1 flex-1 text-xs text-muted">{body}</p>
            <button className="btn-outline mt-3 !py-1.5 text-xs" onClick={() => navigate(to)}>{cta}</button>
          </div>
        ))}
      </div>
    </Card>
  )
}

function AnalystOverview({ rows, thresholdUsd }) {
  const navigate = useNavigate()
  const { toUsd, asOf } = useData()
  const inflow = rows.reduce((a, e) => a + toUsd(e.inflow_30d, e.currency), 0)
  const outflow = rows.reduce((a, e) => a + toUsd(e.outflow_30d, e.currency), 0)
  const cash = rows.reduce((a, e) => a + toUsd(e.balance, e.currency), 0)
  const atRisk = rows.filter((e) => isAtRisk(e.status))
  const breakdown = useCurrencyBreakdown(rows, toUsd)
  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard label="Total cash position (USD eq.)" value={money(cash)} note={`As of ${fmtDate(asOf)}`} icon={Banknote} />
        <KpiCard label="Known inflows, next 30 days" value={money(inflow)} note="Pending, due within 30 days" noteTone="green" icon={ArrowUpRight} accent="green" />
        <KpiCard label="Known outflows, next 30 days" value={money(outflow)} note="Pending, due within 30 days" noteTone="red" icon={ArrowDownRight} accent="red" />
        <KpiCard label="Entities at risk" value={atRisk.length} note={`${atRisk.filter((e) => e.status !== 'warning').length} critical/emergency, ${atRisk.filter((e) => e.status === 'warning').length} warning`} noteTone="red" icon={AlertTriangle} accent="amber" />
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2"><CashTrend thresholdUsd={thresholdUsd} asOf={asOf} /></div>
        <CurrencyDonut rows={breakdown} />
      </div>
      <LiquidityGapTable rows={rows} onRow={(e) => navigate(`/forecasts?entity=${e.id}`)} />
      <PriorityActions rows={rows} />
    </>
  )
}

function ManagerOverview({ rows, thresholdUsd, admin }) {
  const navigate = useNavigate()
  const { toUsd, regions, currencies, openAlerts, asOf } = useData()
  const [region, setRegion] = useState('All Regions')
  const [ccy, setCcy] = useState('All Currencies')
  const [events, setEvents] = useState(null)
  const [userCount, setUserCount] = useState(null)
  useEffect(() => {
    api.getUpcoming(7, 8).then((u) => setEvents(u.events)).catch(() => setEvents([]))
    if (admin) api.getUsers().then((u) => setUserCount(`${u.filter((x) => x.is_active).length} of ${u.length}`)).catch(() => {})
  }, [admin])
  const filtered = rows.filter((e) => (region === 'All Regions' || e.region === region) && (ccy === 'All Currencies' || e.currency === ccy))
  const cash = filtered.reduce((a, e) => a + toUsd(e.balance, e.currency), 0)
  const inflow = filtered.reduce((a, e) => a + toUsd(e.inflow_30d, e.currency), 0)
  const outflow = filtered.reduce((a, e) => a + toUsd(e.outflow_30d, e.currency), 0)
  const byRegion = regions.map((r) => ({
    region: r,
    value: rows.filter((e) => e.region === r).reduce((a, e) => a + toUsd(e.balance, e.currency), 0),
  }))
  const maxRegion = Math.max(1, ...byRegion.map((r) => r.value))
  const breakdown = useCurrencyBreakdown(filtered, toUsd)
  const shownEvents = (events || []).filter((e) => filtered.some((f) => f.id === e.entity_id))
  return (
    <>
      <div className="flex flex-wrap gap-3">
        <Select className="w-44" value={region} onChange={setRegion} options={['All Regions', ...regions]} />
        <Select className="w-44" value={ccy} onChange={setCcy} options={['All Currencies', ...currencies]} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard label="Global cash position (USD eq.)" value={money(cash)} note={`As of ${fmtDate(asOf)}`} icon={Banknote} />
        <KpiCard label="Known inflows, 30 days (USD eq.)" value={money(inflow)} icon={ArrowUpRight} accent="green" />
        <KpiCard label="Known outflows, 30 days (USD eq.)" value={money(outflow)} icon={ArrowDownRight} accent="red" />
        <KpiCard label="Net known flow (USD eq.)" value={signedMoney(inflow - outflow, 'USD')} note={inflow - outflow < 0 ? 'Net outflow expected' : 'Net inflow expected'} noteTone={inflow - outflow < 0 ? 'red' : 'green'} icon={Banknote} accent="violet" />
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2 space-y-4">
          <Card title="Cash position by region" subtitle="USD equivalent · select a region to filter, an entity row to drill down">
            <div className="space-y-4">
              {byRegion.map((r) => (
                <button key={r.region} onClick={() => setRegion(r.region)} className="block w-full text-left">
                  <div className="mb-1 flex justify-between text-sm"><span className="font-bold">{r.region}</span><span className="tabular-nums">{money(r.value)}</span></div>
                  <div className="h-2.5 rounded-full bg-surface"><div className="h-2.5 rounded-full bg-brand" style={{ width: `${(r.value / maxRegion) * 100}%` }} /></div>
                </button>
              ))}
            </div>
          </Card>
          <LiquidityGapTable rows={filtered} onRow={(e) => navigate(`/forecasts?entity=${e.id}`)} />
        </div>
        <CurrencyDonut rows={breakdown} />
      </div>
      <Card title="Upcoming critical events" subtitle="Largest pending payments due in the next 7 days" pad={false}>
        <div className="mt-3 overflow-x-auto">
          {events === null ? <Loading /> : (
            <table className="w-full">
              <thead><tr>{['Due date', 'Entity', 'Description', 'Amount', 'Type', 'Entity status'].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
              <tbody>
                {shownEvents.map((e) => (
                  <tr key={e.id} className="hover:bg-surface">
                    <td className="td">{fmtDate(e.date)}</td><td className="td font-semibold">{e.entity}</td><td className="td">{e.description}</td>
                    <td className="td tabular-nums">{money(e.amount, e.currency)}</td><td className="td"><StatusBadge status={e.direction} /></td><td className="td"><StatusBadge status={e.status} /></td>
                  </tr>
                ))}
                {shownEvents.length === 0 && <tr><td colSpan={6} className="td py-8 text-center text-muted">No pending payments due in the next 7 days.</td></tr>}
              </tbody>
            </table>
          )}
        </div>
      </Card>
      {admin && (
        <Card title="System summary" subtitle="Admin only">
          <div className="grid gap-3 sm:grid-cols-3">
            {[['Active users', userCount ?? '…'], ['Open alerts', String(openAlerts)], ['Entities monitored', String(rows.length)]].map(([k, v]) => (
              <div key={k} className="rounded-lg border border-line p-3.5"><p className="text-xs font-semibold text-muted">{k}</p><p className="mt-1 font-heading text-xl font-extrabold">{v}</p></div>
            ))}
          </div>
        </Card>
      )}
    </>
  )
}

export default function Overview() {
  const { role } = useAuth()
  const { entities, toUsd, loading, error, asOf } = useData()
  const thresholdUsd = entities.reduce((a, e) => a + toUsd(e.threshold, e.currency), 0)

  const titles = {
    Analyst: ['Overview', 'Entity-level cash, 30-day outlook and liquidity gaps for your assigned entities.'],
    'Treasury Manager': ['Regional overview', 'Cross-entity liquidity by region, with drill-down into individual entities.'],
    Admin: ['Global overview', 'System-wide liquidity, with access to users, thresholds and report scheduling.'],
  }
  return (
    <div className="space-y-4">
      <PageHeader title={titles[role][0]} description={titles[role][1]}>
        <DemoTag />
        <Badge tone="grey">{fmtDate(asOf)}</Badge>
      </PageHeader>
      <ErrorNotice error={error} />
      {loading && !entities.length ? <Loading label="Running forecast and loading positions…" /> : role === 'Analyst' ? (
        <AnalystOverview rows={entities} thresholdUsd={thresholdUsd} />
      ) : (
        <ManagerOverview rows={entities} thresholdUsd={thresholdUsd} admin={role === 'Admin'} />
      )}
    </div>
  )
}
