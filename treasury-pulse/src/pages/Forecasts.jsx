import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useData } from '../context/DataContext'
import * as api from '../services/api'
import { compact, fmtDate, fmtDay, money, signedMoney } from '../lib/format'
import { Card, chartTooltipStyle, DemoTag, ErrorNotice, KpiCard, Loading, Notice, PageHeader, Select, StatusBadge } from '../components/ui'
import { Info } from 'lucide-react'
import { joinSeries } from './Overview'

const HORIZONS = { 'Next 7 days': 7, 'Next 14 days': 14, 'Next 30 days': 30 }

// Reads the forecast stored by ML Script 2 (GET /analytics/forecast/<id>/).
export default function Forecasts() {
  const { entities, summary } = useData()
  const [params] = useSearchParams()
  const [id, setId] = useState(params.get('entity') || '')
  const [horizon, setHorizon] = useState('Next 30 days')
  const [fc, setFc] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!id && entities.length) {
      const worst = [...entities].sort((a, b) => a.gap - b.gap)[0]
      setId(String(worst.id))
    }
  }, [entities, id])

  useEffect(() => {
    if (!id) return
    setError(null)
    api.getForecast(id, HORIZONS[horizon]).then(setFc).catch((e) => setError(e.message))
  }, [id, horizon, summary?.forecast_run_id])

  const data = useMemo(() => (fc ? joinSeries(fc.history, fc.forecast, fc.as_of) : []), [fc])
  const e = fc?.entity

  return (
    <div className="space-y-4">
      <PageHeader title="Forecasts" description="Prophet cash-balance forecast per entity, with an 80% confidence range and the minimum cash threshold.">
        <DemoTag />
        <Select className="w-52" value={id} onChange={setId} options={entities.map((x) => ({ value: String(x.id), label: `${x.code} · ${x.currency}` }))} />
        <Select className="w-40" value={horizon} onChange={setHorizon} options={Object.keys(HORIZONS)} />
      </PageHeader>
      <ErrorNotice error={error} />

      {!fc || !e ? <Loading label="Loading forecast…" /> : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard label={`Balance as of ${fmtDate(fc.as_of)}`} value={money(fc.balance, e.currency)} />
            <KpiCard label={`Projected in ${fc.horizon} days`} value={money(fc.projected, e.currency)} note={`Lowest ${money(fc.projected_min, e.currency)} on ${fmtDate(fc.projected_min_date)}`} />
            <KpiCard label="Minimum threshold" value={money(e.threshold, e.currency)} accent="amber" />
            <KpiCard label="Expected gap (lowest point)" value={signedMoney(fc.projected_min - e.threshold, e.currency)} noteTone={fc.projected_min < e.threshold ? 'red' : 'green'} note={<><span className="mr-1">Worst level:</span><StatusBadge status={fc.worst_level?.toLowerCase()} /></>} />
          </div>

          <Card title={`${fc.horizon}-day balance forecast · ${e.code} (${e.currency})`} subtitle={`${e.name} · ${e.region} · amounts in ${e.currency}`}>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={data} margin={{ top: 18, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke="#E3E9F2" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#64748B' }} interval={Math.max(1, Math.floor(data.length / 8))} tickLine={false} />
                  <YAxis tickFormatter={(v) => compact(v)} tick={{ fontSize: 11, fill: '#64748B' }} width={56} tickLine={false} axisLine={false} domain={['auto', 'auto']} />
                  <Tooltip {...chartTooltipStyle} formatter={(v, n) => (Array.isArray(v) ? [`${money(v[0], e.currency)} – ${money(v[1], e.currency)}`, n] : [money(v, e.currency), n])} />
                  <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
                  <Area dataKey="band" name="Confidence range (80%)" stroke="none" fill="#3478F6" fillOpacity={0.14} />
                  <Line dataKey="actual" name="Historical" stroke="#3478F6" strokeWidth={2.25} dot={false} />
                  <Line dataKey="forecast" name="Forecast" stroke="#7C6BD6" strokeWidth={2.25} strokeDasharray="6 4" dot={false} />
                  <ReferenceLine y={e.threshold} stroke="#DC2626" strokeDasharray="4 4" label={{ value: 'Threshold', fontSize: 11, fill: '#DC2626', position: 'insideTopRight' }} />
                  <ReferenceLine x={fmtDay(fc.as_of)} stroke="#94A3B8" label={{ value: 'As of', fontSize: 11, fill: '#64748B', position: 'top' }} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            {fc.lowest_lower_bound < e.threshold && (
              <div className="mt-3"><Notice tone="red" icon={Info}>The lower end of the confidence range falls below the {e.currency} threshold. Consider running a what-if scenario.</Notice></div>
            )}
            <p className="mt-3 text-xs text-muted">Model run {fc.forecast_run_id}. Scheduled flows are pending transactions weighted by counterparty risk R(t); the rest is Prophet's weekly, monthly and quarterly pattern.</p>
          </Card>
        </>
      )}
    </div>
  )
}
