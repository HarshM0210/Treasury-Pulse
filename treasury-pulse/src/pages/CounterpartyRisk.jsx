import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from 'lucide-react'
import * as api from '../services/api'
import { Card, DemoTag, ErrorNotice, KpiCard, Loading, Notice, PageHeader, RatingBadge, Select, Sparkline } from '../components/ui'

const TREND_COLOR = { A: '#16A34A', B: '#3478F6', C: '#D97706', D: '#DC2626' }
const RATING_LABEL = { A: 'Low risk', B: 'Medium risk', C: 'High risk', D: 'High risk' }
const pc = (x) => `${(x * 100).toFixed(2)}%`

// Risk score per transaction: R(t) = 1 − (1 − p_fail)(1 − p_late), 0–1.
// p_fail: entity–counterparty failure rate shrunk to its entity's rate (empirical Bayes);
// p_late: share of late payments for the transaction's payment frequency.
export default function CounterpartyRisk() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [q, setQ] = useState('')
  const [rating, setRating] = useState('All Ratings')
  const [selectedName, setSelectedName] = useState(null)

  useEffect(() => { api.getCounterparties().then(setData).catch((e) => setError(e.message)) }, [])

  if (!data) return <div className="space-y-4"><PageHeader title="Counterparty risk" /><ErrorNotice error={error} />{!error && <Loading />}</div>

  const all = data.counterparties
  const rows = all.filter((c) => c.name.toLowerCase().includes(q.toLowerCase()) && (rating === 'All Ratings' || c.rating === rating))
  const selected = all.find((c) => c.name === selectedName) || rows[0] || all[0]
  const n = (list) => all.filter((c) => list.includes(c.rating)).length
  const m = data.model || {}

  return (
    <div className="space-y-4">
      <PageHeader title="Counterparty risk" description="Payment reliability by counterparty. Risk score R (0–1) = probability a payment does not arrive in full and on time; it weights expected inflows in the forecast."><DemoTag /></PageHeader>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard label="Total counterparties" value={all.length} />
        <KpiCard label="High risk (C, D)" value={n(['C', 'D'])} accent="red" />
        <KpiCard label="Medium risk (B)" value={n(['B'])} accent="amber" />
        <KpiCard label="Low risk (A)" value={n(['A'])} accent="green" />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Counterparty risk ratings" className="xl:col-span-2" pad={false}>
          <div className="flex flex-wrap gap-3 px-5 pb-3 pt-4">
            <label className="relative w-60"><span className="sr-only">Search counterparty</span><Search size={15} className="absolute left-3 top-3 text-muted" /><input className="input pl-9" placeholder="Search counterparty" value={q} onChange={(e) => setQ(e.target.value)} /></label>
            <Select className="w-40" value={rating} onChange={setRating} options={['All Ratings', 'A', 'B', 'C', 'D']} />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead><tr>{['Counterparty', 'Rating', 'Risk score R', 'Transactions', 'Failure rate', 'Avg. delay (days)', 'Trend'].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.name} onClick={() => setSelectedName(c.name)} className={`cursor-pointer hover:bg-surface ${selected?.name === c.name ? 'bg-brand-soft/50' : ''}`}>
                    <td className="td font-semibold">{c.name}</td><td className="td"><RatingBadge rating={c.rating} /></td>
                    <td className="td tabular-nums">{c.risk_score.toFixed(3)}</td>
                    <td className="td tabular-nums">{c.transactions.toLocaleString()}</td><td className="td tabular-nums">{c.failure_rate}%</td><td className="td tabular-nums">{c.avg_delay}</td>
                    <td className="td"><Sparkline data={c.trend} color={TREND_COLOR[c.rating]} /></td>
                  </tr>
                ))}
                {rows.length === 0 && <tr><td colSpan={7} className="td py-10 text-center text-muted">No counterparties match. Clear the search or rating filter.</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>

        {selected && (
          <Card title="Risk details">
            <div className="mb-4 flex items-center gap-3"><RatingBadge rating={selected.rating} /><div><p className="font-heading text-lg font-extrabold leading-tight">{selected.name}</p><p className="text-xs text-muted">{RATING_LABEL[selected.rating]} · R = {selected.risk_score.toFixed(3)}</p></div></div>
            <dl className="space-y-2 text-sm">
              {[['Expected failure probability', pc(selected.p_fail)], ['Lateness probability', pc(selected.p_late)], ['Observed failure rate', `${selected.failure_rate}%`], ['Paid late', `${selected.late_share}%`], ['Avg. days late', `${selected.avg_delay} days`], ['Avg. timing vs due date', `${selected.avg_timing} days`], ['Total transactions', selected.transactions.toLocaleString()]].map(([k, v]) => (
                <div key={k} className="flex justify-between border-b border-line pb-2"><dt className="text-muted">{k}</dt><dd className="font-semibold tabular-nums">{v}</dd></div>
              ))}
            </dl>
            <p className="label mt-4">Last 6 months: average days late</p>
            <div className="h-16 w-full"><Sparkline data={selected.trend} color={TREND_COLOR[selected.rating]} /></div>
            <p className="label mt-3">By entity (R)</p>
            <div className="flex flex-wrap gap-1.5">
              {selected.entities.map((x) => <span key={x.entity_id} className="rounded-md bg-surface px-2 py-1 text-xs"><b>{x.entity}</b> {x.risk_score.toFixed(3)}</span>)}
            </div>
            <div className="mt-4 flex flex-col gap-2">
              <button className="btn-primary" onClick={() => navigate('/transactions')}>View transaction history</button>
              <button className="btn-outline" onClick={() => navigate('/what-if')}>Simulate a rating downgrade</button>
            </div>
          </Card>
        )}
      </div>
      <Notice tone="blue">
        Estimated as of {data.as_of} from {m.global_failure_rate !== undefined ? pc(m.global_failure_rate) : '—'} global failure rate.
        Shrinkage strength (estimated from the data): entity k = {Math.round(m.k_entity || 0)}, pair k = {Math.round(m.k_pair || 0)}. A large pair k means counterparties barely differ beyond their entity, so most of the risk signal is entity-level.
        Rating bands on R: A &lt; 0.01, B 0.01–0.05, C 0.05–0.18, D ≥ 0.18.
      </Notice>
    </div>
  )
}
