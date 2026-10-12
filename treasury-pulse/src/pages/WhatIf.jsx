import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Info, Loader2 } from 'lucide-react'
import { useData } from '../context/DataContext'
import * as api from '../services/api'
import { compact, fmtDay, money, signedMoney } from '../lib/format'
import { Card, chartTooltipStyle, DemoTag, ErrorNotice, KpiCard, Loading, Notice, PageHeader, Select } from '../components/ui'

const RATINGS = ['A', 'B', 'C', 'D']

function Slider({ label, min, max, step = 1, value, onChange, format = (v) => v, marks }) {
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs"><span className="font-semibold text-muted">{label}</span><span className="rounded bg-brand-soft px-2 py-0.5 font-bold text-brand-dark">{format(value)}</span></div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-full accent-brand" aria-label={label} />
      {marks && <div className="mt-1 flex justify-between text-[11px] text-muted">{marks.map((m) => <span key={m}>{m}</span>)}</div>}
    </div>
  )
}

function parametersFor({ delay, postpone, fx, bps, cp, newRating, currentRating }) {
  return {
    payment_delay_days: delay,
    capex_postpone_days: postpone,
    fx_shock_pct: fx,
    rate_shock_bps: bps,
    rating_shift: cp && newRating !== currentRating ? { counterparty: cp, new_rating: newRating } : null,
  }
}

export default function WhatIf() {
  const { entities } = useData()
  const [params] = useSearchParams()
  const [id, setId] = useState(params.get('entity') || '')
  const [delay, setDelay] = useState(0)
  const [postpone, setPostpone] = useState(0)
  const [fx, setFx] = useState(0)
  const [bps, setBps] = useState(0)
  const [cps, setCps] = useState([])
  const [cp, setCp] = useState('')
  const [newRating, setNewRating] = useState('B')
  const [runToken, setRunToken] = useState(0)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const seq = useRef(0)
  const currentRating = cps.find((c) => c.name === cp)?.rating || '—'

  useEffect(() => {
    if (!id && entities.length) setId(String([...entities].sort((a, b) => a.gap - b.gap)[0].id))
  }, [entities, id])

  useEffect(() => {
    api.getCounterparties().then((c) => {
      setCps(c.counterparties || [])
      if (c.counterparties?.length) {
        setCp(c.counterparties[0].name)
        setNewRating(c.counterparties[0].rating || 'B')
      }
    }).catch(() => {})
  }, [])

  // Call Script 3 with every assumption whenever an input changes (debounced).
  useEffect(() => {
    if (!id) return
    const mine = ++seq.current
    const parameters = parametersFor({ delay, postpone, fx, bps, cp, newRating, currentRating })
    const t = setTimeout(async () => {
      setBusy(true)
      setError(null)
      try {
        const r = await api.runWhatIf({ entityId: Number(id), horizon: 30, parameters })
        if (mine === seq.current) setResult(r)
      } catch (e) {
        if (mine === seq.current) setError(e.message)
      } finally {
        if (mine === seq.current) setBusy(false)
      }
    }, 350)
    return () => clearTimeout(t)
  }, [id, delay, postpone, fx, bps, cp, newRating, currentRating, runToken])

  const e = result?.entity
  const ccyOut = e?.currency
  const unit = 1

  const rows = useMemo(() => (result?.series || []).map((d) => ({
    date: fmtDay(d.date),
    baseline: Math.round(d.baseline),
    scenario: Math.round(d.scenario),
    diff: Math.round(d.scenario - d.baseline),
  })), [result])

  if (!result || !e) {
    return (
      <div className="space-y-4">
        <PageHeader title="What-if analysis" description="Combine assumptions and compare the baseline forecast with the scenario side by side."><DemoTag /></PageHeader>
        <ErrorNotice error={error} />
        <Loading label="Running scenario…" />
      </div>
    )
  }

  const threshold = e.threshold * unit
  const minBase = Math.min(...rows.map((r) => r.baseline))
  const minScen = Math.min(...rows.map((r) => r.scenario))
  const gapBase = minBase - threshold
  const gapScen = minScen - threshold
  const daysBelow = (k) => rows.filter((r) => r[k] < threshold).length
  const surplus = Math.max(minScen - threshold * 1.2, 0)
  const imp = result.impact

  return (
    <div className="space-y-4">
      <PageHeader title="What-if analysis" description="Combine assumptions and compare the baseline forecast with the scenario side by side."><DemoTag /></PageHeader>
      <ErrorNotice error={error} />

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Scenario parameters">
          <div className="space-y-5">
            <Select label="Entity" value={id} onChange={setId} options={entities.map((x) => ({ value: String(x.id), label: `${x.code} · ${x.currency}` }))} />
            <Slider label="Delay pending outgoing payments (days)" min={0} max={5} value={delay} onChange={setDelay} format={(v) => v ? `+${v} day${v > 1 ? 's' : ''}` : 'No delay'} marks={['0', '+1', '+2', '+3', '+4', '+5']} />
            <Slider label="Postpone capital spend (days)" min={0} max={30} value={postpone} onChange={setPostpone} format={(v) => `${v} days`} marks={['0', '10', '20', '30']} />
            <Slider label={e.currency === 'USD' ? 'USD vs other currencies rate change' : `${e.currency}/USD rate change`} min={-15} max={15} step={5} value={fx} onChange={setFx} format={(v) => `${v > 0 ? '+' : ''}${v}%`} marks={['-15%', '-10%', '-5%', '0', '+5%', '+10%', '+15%']} />
            <Slider label="Rate change" min={-200} max={200} step={50} value={bps} onChange={setBps} format={(v) => `${v > 0 ? '+' : ''}${v} bps`} marks={['-200', '-100', '0', '+100', '+200']} />
            <Select label="Counterparty" value={cp} onChange={(name) => {
              setCp(name)
              setNewRating(cps.find((counterparty) => counterparty.name === name)?.rating || 'B')
            }} options={cps.map((c) => c.name)} />
            <Slider label={`Counterparty rating shift (current: ${currentRating})`} min={0} max={3} value={RATINGS.indexOf(newRating)} onChange={(index) => setNewRating(RATINGS[index])} format={(index) => RATINGS[index]} marks={RATINGS} />
            <button className="btn-primary w-full" onClick={() => setRunToken((token) => token + 1)} disabled={busy}>{busy ? <><Loader2 size={15} className="animate-spin" /> Running…</> : 'Run scenario'}</button>
            <button className="btn-outline w-full" onClick={() => {
              setDelay(0)
              setPostpone(0)
              setFx(0)
              setBps(0)
              setNewRating(currentRating === '—' ? 'B' : currentRating)
              setRunToken((token) => token + 1)
            }}>Reset to baseline</button>
            <ul className="space-y-1 text-xs text-muted">{result.notes.map((n) => <li key={n}>• {n}</li>)}</ul>
          </div>
        </Card>

        <Card title={`Scenario result · ${e.code} (${ccyOut})`} subtitle={`Amounts in ${e.currency} · baseline = stored Prophet forecast`} className="xl:col-span-2">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="#E3E9F2" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#64748B' }} interval={5} tickLine={false} />
                <YAxis tickFormatter={(v) => compact(v)} tick={{ fontSize: 11, fill: '#64748B' }} width={56} tickLine={false} axisLine={false} domain={['auto', 'auto']} />
                <Tooltip {...chartTooltipStyle} formatter={(v, n) => [money(v, ccyOut), n]} />
                <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
                <Line dataKey="baseline" name="Baseline" stroke="#3478F6" strokeWidth={2.25} dot={false} />
                <Line dataKey="scenario" name="Scenario" stroke="#7C6BD6" strokeWidth={2.25} strokeDasharray="6 4" dot={false} />
                <ReferenceLine y={threshold} stroke="#DC2626" strokeDasharray="4 4" label={{ value: 'Threshold', fontSize: 11, fill: '#DC2626', position: 'insideTopRight' }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-4 flex items-baseline justify-between">
            <p className="text-xs font-semibold text-muted">Scenario − baseline (cumulative change in balance)</p>
            {rows.every((r) => r.diff === 0) && <p className="text-xs text-muted">No change: scenario equals the baseline</p>}
          </div>
          <div className="h-36">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="#E3E9F2" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#64748B' }} interval={5} tickLine={false} />
                <YAxis tickFormatter={(v) => compact(v)} tick={{ fontSize: 11, fill: '#64748B' }} width={56} tickLine={false} axisLine={false} />
                <Tooltip {...chartTooltipStyle} formatter={(v) => [signedMoney(v, ccyOut), 'Scenario − baseline']} />
                <ReferenceLine y={0} stroke="#94A3B8" />
                <Bar dataKey="diff" name="Scenario − baseline" isAnimationActive={false}>
                  {rows.map((r) => <Cell key={r.date} fill={r.diff >= 0 ? '#16A34A' : '#DC2626'} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <Card title="Impact summary" subtitle={`Baseline compared with scenario over the next ${result.horizon} days (as of ${result.as_of})`}>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard label="Liquidity gap (lowest point)" value={signedMoney(gapScen, ccyOut)} note={`Baseline ${signedMoney(gapBase, ccyOut)}`} noteTone={gapScen >= gapBase ? 'green' : 'red'} />
          <KpiCard label="Days below threshold" value={daysBelow('scenario')} note={`Baseline ${daysBelow('baseline')}`} noteTone={daysBelow('scenario') <= daysBelow('baseline') ? 'green' : 'red'} accent="red" />
          <KpiCard label="Surplus deployment opportunity" value={money(Math.round(surplus), ccyOut)} note="Above threshold + 20%" accent="green" />
          <KpiCard label={`Change at day ${result.horizon}`} value={signedMoney(rows.at(-1).scenario - rows.at(-1).baseline, ccyOut)} accent="violet" />
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard label="Overdraft / funding cost (8% p.a.)" value={money(result.scenario.funding_cost, e.currency)} note={`Baseline ${money(result.baseline.funding_cost, e.currency)}`} />
          <KpiCard label="FX translation gain/loss" value={signedMoney(imp.fx_translation_usd, 'USD')} note={`Payments revalued: ${signedMoney(imp.fx_transaction_impact, e.currency)}`} />
          <KpiCard label="Interest income/expense change" value={signedMoney(imp.interest_delta, e.currency)} />
          <KpiCard label="Transactions affected" value={imp.affected_transactions} />
        </div>
        <div className="mt-3"><Notice tone="blue" icon={Info}>Scenario = stored baseline + the exact change in expected cash flows of pending transactions (risk-weighted by R(t)). The model is not refitted. Scenario #{result.scenario_id} saved.</Notice></div>
      </Card>
    </div>
  )
}
