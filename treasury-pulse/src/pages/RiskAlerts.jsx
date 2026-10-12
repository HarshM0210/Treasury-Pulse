import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertOctagon } from 'lucide-react'
import { useData } from '../context/DataContext'
import * as api from '../services/api'
import { fmtDate, fmtDateTime, money, signedMoney } from '../lib/format'
import { Card, DemoTag, ErrorNotice, KpiCard, Notice, PageHeader, Select, StatusBadge, Tabs } from '../components/ui'

const STATUS_LABEL = { OPEN: 'Open', ACKNOWLEDGED: 'Acknowledged', RESOLVED: 'Resolved' }

// API alert → row used by this page
const toRow = (a) => ({
  id: a.id,
  ref: `AL-${String(a.id).padStart(4, '0')}`,
  time: fmtDateTime(a.created_at),
  entity: a.entity_code,
  entityId: a.entity,
  currency: a.currency,
  projected: a.projected_balance !== null ? Number(a.projected_balance) : null,
  threshold: a.threshold !== null ? Number(a.threshold) : null,
  gap: Number(a.liquidity_gap),
  severity: String(a.severity).toLowerCase(),
  status: STATUS_LABEL[a.status] || a.status,
  title: a.title || 'Liquidity alert',
  expected: a.metric_date ? fmtDate(a.metric_date) : 'Today',
  breach: a.breach_probability,
  source: a.source,
  resolvedBy: a.resolved_by,
  resolvedAt: a.resolved_at,
})

export default function RiskAlerts() {
  const navigate = useNavigate()
  const { alerts: apiAlerts, entities, currencies, reloadAlerts, reload } = useData()
  const [tab, setTab] = useState('Alerts')
  const [sev, setSev] = useState('All Severities')
  const [ccy, setCcy] = useState('All Currencies')
  const [selectedId, setSelectedId] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const alerts = useMemo(() => apiAlerts.map(toRow), [apiAlerts])
  const active = alerts.filter((a) => a.status !== 'Resolved')
  const filtered = active.filter((a) => (sev === 'All Severities' || a.severity === sev.toLowerCase()) && (ccy === 'All Currencies' || a.currency === ccy))
  const selected = alerts.find((a) => a.id === selectedId) || filtered[0] || alerts[0]
  const count = (s) => active.filter((a) => a.severity === s).length
  const topAlert = active.find((a) => a.severity === 'emergency')

  const act = async (fn) => {
    setBusy(true)
    setError(null)
    try { await fn(selected.id); await reloadAlerts(); await reload() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Risk & alerts" description="Gap checks of every forecast day against each entity's minimum cash threshold. Re-evaluated whenever the forecast or a threshold changes.">
        <DemoTag />
        <Select className="w-40" value={sev} onChange={setSev} options={['All Severities', 'Warning', 'Critical', 'Emergency']} />
        <Select className="w-40" value={ccy} onChange={setCcy} options={['All Currencies', ...currencies]} />
      </PageHeader>
      <ErrorNotice error={error} />

      {topAlert && (
        <Notice tone="red" icon={AlertOctagon}>
          <span className="font-bold">Emergency:</span> {topAlert.entity} is projected at {money(topAlert.projected, topAlert.currency)} on {topAlert.expected}, below its {money(topAlert.threshold, topAlert.currency)} threshold.
        </Notice>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard label="Open alerts" value={active.length} />
        <KpiCard label="Emergency" value={count('emergency')} accent="red" noteTone="red" />
        <KpiCard label="Critical" value={count('critical')} accent="red" />
        <KpiCard label="Warning" value={count('warning')} accent="amber" />
      </div>

      <Tabs tabs={['Alerts', 'Alert matrix', 'History']} value={tab} onChange={setTab} />

      {tab === 'Alerts' && (
        <div className="grid gap-4 xl:grid-cols-3">
          <Card title="Alert list" className="xl:col-span-2" pad={false}>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full">
                <thead><tr>{['Time', 'Entity', 'Currency', 'Projected', 'Threshold', 'Gap', 'Severity', 'Status'].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
                <tbody>
                  {filtered.map((a) => (
                    <tr key={a.id} onClick={() => setSelectedId(a.id)} className={`cursor-pointer hover:bg-surface ${a.id === selected?.id ? 'bg-brand-soft/50' : ''}`}>
                      <td className="td">{a.time}</td><td className="td font-semibold">{a.entity}</td><td className="td">{a.currency}</td>
                      <td className="td tabular-nums">{money(a.projected, a.currency)}</td><td className="td tabular-nums text-muted">{money(a.threshold, a.currency)}</td>
                      <td className={`td font-semibold tabular-nums ${a.gap < 0 ? 'text-crit' : 'text-ok'}`}>{signedMoney(a.gap, a.currency)}</td>
                      <td className="td"><StatusBadge status={a.severity} /></td><td className="td"><StatusBadge status={a.status} /></td>
                    </tr>
                  ))}
                  {filtered.length === 0 && <tr><td colSpan={8} className="td py-10 text-center text-muted">No open alerts match these filters.</td></tr>}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="Alert details">
            {!selected ? <p className="text-sm text-muted">No alerts.</p> : (
              <>
                <div className="mb-3 flex items-center justify-between"><p className="text-sm font-bold">{selected.title}</p><StatusBadge status={selected.severity} /></div>
                <dl className="space-y-2 text-sm">
                  {[['Alert', selected.ref], ['Entity', selected.entity], ['Currency', selected.currency], ['Projected position', money(selected.projected, selected.currency)], ['Threshold', money(selected.threshold, selected.currency)], ['Liquidity gap', signedMoney(selected.gap, selected.currency)], ['Expected date', selected.expected], ['Breach probability', selected.breach !== null && selected.breach !== undefined ? `${Math.round(selected.breach * 100)}%` : '—'], ['Source', selected.source === 'ACTUAL' ? 'Current balance' : '30-day forecast'], ['Status', selected.status]].map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-3 border-b border-line pb-2"><dt className="text-muted">{k}</dt><dd className="font-semibold tabular-nums">{v}</dd></div>
                  ))}
                </dl>
                <div className="mt-4 flex flex-col gap-2">
                  <button className="btn-primary" onClick={() => navigate('/transactions')}>View supporting transactions</button>
                  <button className="btn-outline" onClick={() => navigate(`/what-if?entity=${selected.entityId}`)}>Test a scenario</button>
                  {selected.status === 'Open' && <button className="btn-outline" disabled={busy} onClick={() => act(api.acknowledgeAlert)}>Acknowledge</button>}
                  {selected.status !== 'Resolved' && <button className="btn-outline" disabled={busy} onClick={() => act(api.resolveAlert)}>Mark as resolved</button>}
                </div>
              </>
            )}
          </Card>
        </div>
      )}

      {tab === 'Alert matrix' && (
        <Card title="Alert matrix" subtitle="Per-entity, per-currency evaluation of the lowest forecast point against the configured threshold" pad={false}>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full">
              <thead><tr>{['Entity', 'Region', 'Currency', 'Threshold', 'Lowest projected', 'Gap', 'First breach', 'Alert level'].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
              <tbody>
                {entities.map((e) => (
                  <tr key={e.id}>
                    <td className="td font-semibold">{e.code}</td><td className="td">{e.region}</td><td className="td">{e.currency}</td>
                    <td className="td tabular-nums">{money(e.threshold, e.currency)}</td><td className="td tabular-nums">{money(e.projected_min, e.currency)}</td>
                    <td className={`td font-semibold tabular-nums ${e.gap < 0 ? 'text-crit' : 'text-ok'}`}>{signedMoney(e.gap, e.currency)}</td>
                    <td className="td">{e.first_breach_date ? fmtDate(e.first_breach_date) : '—'}</td>
                    <td className="td"><StatusBadge status={e.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid gap-2 px-5 py-4 text-xs text-muted sm:grid-cols-3">
            <p><b className="text-warn">Warning:</b> within 5–10% of threshold</p>
            <p><b className="text-crit">Critical:</b> within 0–5% of threshold</p>
            <p><b className="text-crit">Emergency:</b> below threshold or negative</p>
          </div>
        </Card>
      )}

      {tab === 'History' && (
        <Card title="Alert history" subtitle="Timestamp, severity and resolution status" pad={false}>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full">
              <thead><tr>{['ID', 'Raised', 'Entity', 'Description', 'Severity', 'Resolution', 'Resolved'].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
              <tbody>
                {alerts.map((a) => (
                  <tr key={a.id}><td className="td font-semibold">{a.ref}</td><td className="td">{a.time}</td><td className="td">{a.entity}</td><td className="td">{a.title}</td><td className="td"><StatusBadge status={a.severity} /></td><td className="td"><StatusBadge status={a.status} /></td><td className="td text-xs text-muted">{a.resolvedAt ? `${fmtDateTime(a.resolvedAt)} by ${a.resolvedBy}` : '—'}</td></tr>
                ))}
                {alerts.length === 0 && <tr><td colSpan={7} className="td py-10 text-center text-muted">No alerts raised yet.</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
