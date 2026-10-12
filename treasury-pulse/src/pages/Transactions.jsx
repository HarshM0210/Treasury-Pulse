import { useEffect, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, ChevronLeft, ChevronRight, FileSpreadsheet, Loader2, Search, UploadCloud } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { useData } from '../context/DataContext'
import * as api from '../services/api'
import { money } from '../lib/format'
import { Card, DemoTag, ErrorNotice, Loading, Notice, PageHeader, Select, StatusBadge } from '../components/ui'

const PAGE_SIZE = 10

function CsvUpload() {
  const { role } = useAuth()
  const { reload } = useData()
  const inputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [state, setState] = useState('idle') // idle | uploading | done | error
  const [result, setResult] = useState(null)
  const [message, setMessage] = useState(null)
  const [drag, setDrag] = useState(false)
  const isAdmin = role === 'Admin'

  const pick = async (f) => {
    if (!f) return
    if (!f.name.toLowerCase().endsWith('.csv')) {
      setFile(null)
      setState('error')
      setMessage('That file is not a CSV. Choose a file ending in .csv.')
      return
    }
    setFile(f)
    setState('uploading')
    setMessage(null)
    try {
      const r = await api.uploadTransactionsCsv(f)
      setResult(r)
      setState('done')
      await reload()
    } catch (e) {
      setState('error')
      setMessage(e.message)
    }
  }

  const s = result?.stats
  return (
    <Card title="Upload transactions (CSV)" subtitle="Validated row by row, imported, then cash positions and the 30-day forecast are rebuilt">
      <div className="grid gap-4 lg:grid-cols-2">
        <div
          onDragOver={(e) => { e.preventDefault(); if (isAdmin) setDrag(true) }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); if (isAdmin) pick(e.dataTransfer.files?.[0]) }}
          className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-8 text-center ${drag ? 'border-brand bg-brand-soft' : 'border-line bg-surface/60'}`}
        >
          <UploadCloud size={32} className="text-brand" />
          <p className="mt-2 text-sm font-bold">Drag and drop your CSV file here</p>
          <p className="my-1 text-xs text-muted">or</p>
          <button className="btn-primary" disabled={!isAdmin || state === 'uploading'} onClick={() => inputRef.current?.click()}>Browse files</button>
          <input ref={inputRef} type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => { pick(e.target.files?.[0]); e.target.value = '' }} />
          <p className="mt-3 text-xs text-muted">{isAdmin ? 'Supported format: CSV (same columns as the UC5 dataset)' : 'Only Admins can upload transaction data.'}</p>
        </div>

        <div>
          <p className="label">Upload status</p>
          {state === 'idle' && <Notice tone="blue" icon={FileSpreadsheet}>No file selected yet.</Notice>}
          {state === 'uploading' && <Notice tone="blue" icon={Loader2}><span className="font-semibold">{file?.name}</span>: validating, importing and re-running the forecast…</Notice>}
          {state === 'done' && <Notice tone="green" icon={CheckCircle2}><span className="font-semibold">{result.filename}</span> imported. Forecast {result.forecast.status === 'up_to_date' ? 'already up to date' : `run ${result.forecast.forecast_run_id}`}.</Notice>}
          {state === 'error' && <Notice tone="red" icon={AlertCircle}>{message}</Notice>}
          <div className="mt-3 rounded-lg border border-line p-3.5">
            <p className="text-xs font-bold">Validation summary</p>
            {s ? (
              <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                {[['Rows read', s.rows_read], ['Valid rows', s.valid_rows], ['New transactions', s.new_transactions], ['Duplicates skipped', s.duplicate_transactions], ['Entities created', s.entities_created], ['Accounts created', s.accounts_created], ['Cash positions rebuilt', s.positions_created]].map(([k, v]) => (
                  <div key={k} className="flex justify-between"><dt className="text-muted">{k}</dt><dd className="font-semibold tabular-nums">{Number(v).toLocaleString()}</dd></div>
                ))}
              </dl>
            ) : <p className="mt-1 text-xs text-muted">Valid, skipped and failed record counts are shown here after server-side validation. Any invalid row rejects the whole file with its line number.</p>}
          </div>
        </div>
      </div>
    </Card>
  )
}

export default function Transactions() {
  const { entities, currencies, summary } = useData()
  const [q, setQ] = useState('')
  const [entity, setEntity] = useState('All Entities')
  const [ccy, setCcy] = useState('All Currencies')
  const [status, setStatus] = useState('All Statuses')
  const [sort, setSort] = useState('-transaction_date')
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const t = setTimeout(() => {
      api.getTransactions({
        page, page_size: PAGE_SIZE, q: q.trim(),
        entity: entity === 'All Entities' ? '' : entity,
        currency: ccy === 'All Currencies' ? '' : ccy,
        status: status === 'All Statuses' ? '' : status.toLowerCase(),
        ordering: sort,
      }).then((d) => { setData(d); setError(null) }).catch((e) => setError(e.message))
    }, 250)
    return () => clearTimeout(t)
  }, [q, entity, ccy, status, sort, page, summary?.forecast_run_id])

  const count = data?.count ?? 0
  const pages = Math.max(1, Math.ceil(count / PAGE_SIZE))
  const reset = (setter) => (v) => { setter(v); setPage(1) }

  return (
    <div className="space-y-4">
      <PageHeader title="Transactions" description="Upload transaction data and review settlement status across entities."><DemoTag /></PageHeader>
      <CsvUpload />
      <Card title="Transaction list" pad={false}>
        <div className="grid gap-3 px-5 pb-3 pt-4 sm:grid-cols-2 lg:grid-cols-5">
          <label className="relative sm:col-span-2">
            <span className="sr-only">Search</span>
            <Search size={15} className="absolute left-3 top-3 text-muted" />
            <input className="input pl-9" placeholder="Search ID, entity or counterparty" value={q} onChange={(e) => reset(setQ)(e.target.value)} />
          </label>
          <Select value={entity} onChange={reset(setEntity)} options={[{ value: 'All Entities', label: 'All Entities' }, ...entities.map((e) => ({ value: String(e.id), label: e.code }))]} />
          <Select value={ccy} onChange={reset(setCcy)} options={['All Currencies', ...currencies]} />
          <Select value={status} onChange={reset(setStatus)} options={['All Statuses', 'Settled', 'Failed']} />
          <Select
            label="Sort by"
            value={sort}
            onChange={reset(setSort)}
            options={[
              { value: '-transaction_date', label: 'Date: newest first' },
              { value: 'transaction_date', label: 'Date: oldest first' },
            ]}
          />
        </div>
        <ErrorNotice error={error} />
        <div className="overflow-x-auto">
          {!data ? <Loading /> : (
            <table className="w-full">
              <thead><tr>{['Transaction ID', 'Date (actual)', 'Due date (expected)', 'Entity', 'Counterparty', 'Amount', 'Currency', 'Direction', 'Status'].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
              <tbody>
                {data.results.map((t) => (
                  <tr key={t.id} className="hover:bg-surface">
                    <td className="td font-semibold">{t.transaction_id}</td><td className="td">{t.transaction_date}</td><td className="td">{t.due_date || '—'}</td>
                    <td className="td">{t.entity_code}</td><td className="td">{t.counterparty || '—'}</td>
                    <td className="td text-right tabular-nums">{money(Number(t.amount), t.currency)}</td><td className="td">{t.currency}</td>
                    <td className="td"><StatusBadge status={t.direction} /></td><td className="td"><StatusBadge status={t.settlement_status} /></td>
                  </tr>
                ))}
                {data.results.length === 0 && <tr><td colSpan={9} className="td py-10 text-center text-muted">No transactions match these filters. Clear a filter to see more.</td></tr>}
              </tbody>
            </table>
          )}
        </div>
        <div className="flex items-center justify-between border-t border-line px-5 py-3 text-sm">
          <span className="text-muted">{count.toLocaleString()} transactions · page {Math.min(page, pages)} of {pages}</span>
          <div className="flex gap-1.5">
            <button className="btn-outline !p-2" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page"><ChevronLeft size={16} /></button>
            <button className="btn-outline !p-2" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page"><ChevronRight size={16} /></button>
          </div>
        </div>
      </Card>
    </div>
  )
}
