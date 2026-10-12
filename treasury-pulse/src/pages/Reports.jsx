import { useEffect, useState } from 'react'
import { Download, FileText, Mail, Printer, X } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { useData } from '../context/DataContext'
import * as api from '../services/api'
import { fmtDate, money, signedMoney } from '../lib/format'
import { Card, DemoTag, Notice, PageHeader, Select, Tabs, Toggle } from '../components/ui'

const TABS = ['SOD briefing', 'EOD report', 'Custom report']
const SCOPE = { Analyst: 'Personal reports', 'Treasury Manager': 'Regional reports', Admin: 'Full scheduler management' }

export default function Reports() {
  const { role } = useAuth()
  const { entities, alerts, asOf } = useData()
  const isAdmin = role === 'Admin'
  const [tab, setTab] = useState(TABS[0])
  const [recipients, setRecipients] = useState(['treasury@company.com', 'finance@company.com'])
  const [draft, setDraft] = useState('')
  const [enabled, setEnabled] = useState({ sod: true, eod: true })
  const [time, setTime] = useState('08:00')
  const [period, setPeriod] = useState('Daily')
  const [upcoming, setUpcoming] = useState([])

  useEffect(() => { api.getUpcoming(2, 5).then((u) => setUpcoming(u.events)).catch(() => {}) }, [asOf])

  const isSod = tab === TABS[0]
  const isEod = tab === TABS[1]
  const openAlerts = alerts.filter((a) => a.status !== 'RESOLVED')
  const atRisk = entities.filter((e) => ['emergency', 'critical', 'warning'].includes(e.status))
  const addRecipient = () => {
    const v = draft.trim()
    if (/^\S+@\S+\.\S+$/.test(v) && !recipients.includes(v)) { setRecipients([...recipients, v]); setDraft('') }
  }

  const exportCsv = () => {
    const header = ['Entity', 'Region', 'Currency', 'Balance as of', 'Lowest projected (30d)', 'Lowest on', 'Threshold', 'Gap', 'Status']
    const body = entities.map((e) => [e.code, e.region, e.currency, e.balance, e.projected_min, e.projected_min_date, e.threshold, e.gap, e.status])
    const csv = [header, ...body].map((r) => r.join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    const a = Object.assign(document.createElement('a'), { href: url, download: `treasury-pulse-${tab.split(' ')[0].toLowerCase()}-${asOf}.csv` })
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Reports" description={`Schedule start-of-day and end-of-day briefings. Your access: ${SCOPE[role]}.`}><DemoTag /></PageHeader>
      <Tabs tabs={TABS} value={tab} onChange={setTab} />

      <div className="grid gap-4 xl:grid-cols-5">
        <Card title="Report settings" className="xl:col-span-2">
          <div className="space-y-4">
            <div><label className="label" htmlFor="rdate">Report date</label><input id="rdate" className="input" value={fmtDate(asOf)} readOnly /></div>
            <Select label="Report type" value={tab} onChange={setTab} options={TABS} />

            <div>
              <span className="label">Recipients</span>
              <div className="flex flex-wrap gap-2 rounded-lg border border-line p-2">
                {recipients.map((r) => (
                  <span key={r} className="inline-flex items-center gap-1 rounded-md bg-brand-soft px-2 py-1 text-xs font-semibold text-brand-dark">
                    {r}
                    {isAdmin && <button onClick={() => setRecipients(recipients.filter((x) => x !== r))} aria-label={`Remove ${r}`}><X size={12} /></button>}
                  </span>
                ))}
                {isAdmin && (
                  <input className="min-w-[150px] flex-1 border-0 p-1 text-sm focus:outline-none" placeholder="Add email, press Enter" value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addRecipient() } }} aria-label="Add recipient email" />
                )}
              </div>
              {!isAdmin && <p className="mt-1.5 text-xs text-muted">Only Admins can change the distribution list.</p>}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <Select label="Frequency" value={period} onChange={setPeriod} options={['Daily', 'Weekdays only', 'Weekly']} />
              <div><label className="label" htmlFor="rtime">Send at</label><input id="rtime" type="time" className="input" value={time} onChange={(e) => setTime(e.target.value)} /></div>
            </div>

            <div className="space-y-2.5 rounded-lg border border-line p-3.5">
              {[['sod', 'Start-of-day briefing'], ['eod', 'End-of-day report']].map(([k, l]) => (
                <div key={k} className="flex items-center justify-between text-sm">
                  <span className="font-semibold">{l}</span>
                  <Toggle label={`Schedule ${l}`} checked={enabled[k]} onChange={(v) => setEnabled({ ...enabled, [k]: v })} />
                </div>
              ))}
            </div>

            <div className="flex flex-wrap gap-2">
              <button className="btn-primary"><Mail size={15} /> Save schedule</button>
              <button className="btn-outline" onClick={exportCsv}><Download size={15} /> Export CSV</button>
              <button className="btn-outline" onClick={() => window.print()}><Printer size={15} /> Export PDF</button>
            </div>
            <Notice tone="blue" icon={FileText}>Report content is live (forecast, gaps, alerts). Scheduled email delivery is not part of this backend yet, so saving only updates this screen.</Notice>
          </div>
        </Card>

        <Card title="Report preview" className="xl:col-span-3">
          <article className="rounded-lg border border-line bg-white p-5">
            <header className="border-b border-line pb-3">
              <p className="font-heading text-lg font-extrabold">Treasury Pulse · {isSod ? 'Start-of-day briefing' : isEod ? 'End-of-day report' : 'Custom report'}</p>
              <p className="text-xs text-muted">As of {fmtDate(asOf)} · {entities.length} entities</p>
            </header>
            <h4 className="mt-4 text-sm font-bold">{isSod ? 'Opening position (and lowest projected gap)' : 'Position summary (lowest projected in 30 days)'}</h4>
            <table className="mt-2 w-full text-sm">
              <tbody>
                {entities.map((e) => (
                  <tr key={e.id} className="border-t border-line"><td className="py-1.5 font-semibold">{e.code}</td><td className="tabular-nums">{money(isSod ? e.balance : e.projected_min, e.currency)}</td><td className={`text-right tabular-nums ${e.gap < 0 ? 'text-crit' : 'text-ok'}`}>{signedMoney(e.gap, e.currency)}</td></tr>
                ))}
              </tbody>
            </table>
            <h4 className="mt-4 text-sm font-bold">{isSod ? 'Upcoming payments (next 24–48h)' : 'Forecast outlook and liquidity gap status'}</h4>
            {isSod ? (
              <ul className="mt-1 list-disc pl-5 text-sm text-muted">
                {upcoming.map((u) => <li key={u.id}>{u.entity}: {u.description}, {money(u.amount, u.currency)} ({u.direction}) due {fmtDate(u.date)}</li>)}
                {upcoming.length === 0 && <li>No pending payments due in the next 48 hours.</li>}
              </ul>
            ) : (
              <p className="mt-1 text-sm text-muted">
                {atRisk.length ? atRisk.map((e) => `${e.code} ${e.status} (lowest ${money(e.projected_min, e.currency)} on ${fmtDate(e.projected_min_date)})`).join('; ') : 'All entities stay above threshold for the next 30 days.'}
              </p>
            )}
            <h4 className="mt-4 text-sm font-bold">{isSod ? 'Overnight alerts' : 'Alerts open'}</h4>
            <ul className="mt-1 list-disc pl-5 text-sm text-muted">
              {openAlerts.slice(0, 5).map((a) => <li key={a.id}>{a.entity_code}: {a.title} ({String(a.severity).toLowerCase()})</li>)}
              {openAlerts.length === 0 && <li>No open alerts.</li>}
            </ul>
          </article>
        </Card>
      </div>
    </div>
  )
}
