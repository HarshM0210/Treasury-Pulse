import { useEffect, useState } from 'react'
import { Check, Pencil, Plus, UserCheck, UserX } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { useData } from '../context/DataContext'
import * as api from '../services/api'
import { DEFAULT_THRESHOLDS, PERMISSIONS, ROLE_FROM_API, ROLE_TO_API, ROLES, money } from '../lib/format'
import { Badge, Card, DemoTag, ErrorNotice, Loading, Modal, Notice, PageHeader, Select, StatusBadge, Tabs } from '../components/ui'

const blank = { username: '', password: '', name: '', email: '', role: 'Analyst', entities: [], regions: [] }
const roleTone = { Analyst: 'green', 'Treasury Manager': 'blue', Admin: 'violet' }

function ScopePicker({ form, setForm }) {
  const { entities, regions } = useData()
  const toggle = (key, v) => {
    const list = form[key].includes(v) ? form[key].filter((x) => x !== v) : [...form[key], v]
    setForm({ ...form, [key]: list })
  }
  if (form.role === 'Admin') return <p className="text-xs text-muted">Admins can access all entities.</p>
  const isTm = form.role === 'Treasury Manager'
  const opts = isTm ? regions.map((r) => [r, r]) : entities.map((e) => [e.id, `${e.code} (${e.currency})`])
  const key = isTm ? 'regions' : 'entities'
  return (
    <div>
      <span className="label">{isTm ? 'Regions' : 'Entities'} this user can see</span>
      <div className="flex flex-wrap gap-2">
        {opts.map(([v, l]) => (
          <label key={v} className={`flex cursor-pointer items-center gap-1.5 rounded-md border px-2 py-1 text-xs ${form[key].includes(v) ? 'border-brand bg-brand-soft' : 'border-line'}`}>
            <input type="checkbox" className="rounded text-brand" checked={form[key].includes(v)} onChange={() => toggle(key, v)} /> {l}
          </label>
        ))}
      </div>
    </div>
  )
}

function UserManagement() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState(null)
  const [form, setForm] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = () => api.getUsers().then(setUsers).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])

  const isNew = form && !form.id
  const valid = form && form.name.trim() && (!form.email || /^\S+@\S+\.\S+$/.test(form.email)) && (!isNew || (form.username.trim() && form.password.length >= 8))

  const save = async () => {
    if (!valid) return
    const [first_name, ...rest] = form.name.trim().split(' ')
    const payload = { first_name, last_name: rest.join(' '), email: form.email, role: ROLE_TO_API[form.role], entities: form.entities, regions: form.regions }
    setBusy(true)
    setError(null)
    try {
      if (isNew) await api.createUser({ ...payload, username: form.username.trim(), password: form.password })
      else await api.updateUser(form.id, payload)
      setForm(null)
      await load()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const toggle = async (u) => {
    try { await api.setUserActive(u.id, !u.is_active); await load() } catch (e) { setError(e.message) }
  }
  const edit = (u) => setForm({ id: u.id, username: u.username, password: '', name: u.name, email: u.email, role: ROLE_FROM_API[u.role], entities: u.entities, regions: u.regions })

  return (
    <Card title="Users" subtitle="Stored in the backend. Analysts see assigned entities; Treasury Managers see assigned regions." action={<button className="btn-primary" onClick={() => setForm(blank)}><Plus size={15} /> Add user</button>} pad={false}>
      <div className="px-5"><ErrorNotice error={error} /></div>
      <div className="mt-3 overflow-x-auto">
        {!users ? <Loading /> : (
          <table className="w-full">
            <thead><tr>{['Name', 'Username', 'Email', 'Role', 'Data access', 'Status', 'Actions'].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="hover:bg-surface">
                  <td className="td font-semibold">{u.name}</td><td className="td">{u.username}</td><td className="td">{u.email || '—'}</td>
                  <td className="td"><Badge tone={roleTone[ROLE_FROM_API[u.role]]}>{ROLE_FROM_API[u.role]}</Badge></td><td className="td">{u.scope}</td>
                  <td className="td"><StatusBadge status={u.is_active ? 'Active' : 'Suspended'} /></td>
                  <td className="td">
                    <div className="flex gap-1.5">
                      <button className="btn-outline !px-2.5 !py-1 text-xs" onClick={() => edit(u)}><Pencil size={12} /> Edit</button>
                      {u.id !== me?.id && <button className="btn-outline !px-2.5 !py-1 text-xs" onClick={() => toggle(u)}>{u.is_active ? <><UserX size={12} /> Suspend</> : <><UserCheck size={12} /> Activate</>}</button>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Modal open={!!form} title={isNew ? 'Add user' : 'Edit user'} onClose={() => setForm(null)}
        footer={<><button className="btn-outline" onClick={() => setForm(null)}>Cancel</button><button className="btn-primary" disabled={!valid || busy} onClick={save}>{isNew ? 'Add user' : 'Save changes'}</button></>}>
        {form && (
          <>
            {isNew && (
              <div className="grid grid-cols-2 gap-3">
                <div><label className="label" htmlFor="uu">Username</label><input id="uu" className="input" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></div>
                <div><label className="label" htmlFor="up">Password (8+)</label><input id="up" type="password" className="input" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
              </div>
            )}
            <div><label className="label" htmlFor="un">Full name</label><input id="un" className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
            <div><label className="label" htmlFor="ue">Email</label><input id="ue" type="email" className="input" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
            <Select label="Role" value={form.role} onChange={(v) => setForm({ ...form, role: v })} options={ROLES} />
            <ScopePicker form={form} setForm={setForm} />
          </>
        )}
      </Modal>
    </Card>
  )
}

function Permissions() {
  return (
    <Card title="Role permissions" subtitle="Enforced by the backend (scoping.py and permissions.py)." pad={false}>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full">
          <thead><tr>{['Capability', 'Analyst', 'Treasury Manager', 'Admin'].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
          <tbody>
            {PERMISSIONS.map((p) => (
              <tr key={p.capability}>
                <td className="td font-semibold">{p.capability}</td>
                {[p.analyst, p.manager, p.admin].map((v, i) => (
                  <td key={i} className="td"><Badge tone={v === 'No' ? 'grey' : v === 'Limited' || v === 'Personal' ? 'amber' : 'green'}>{v}</Badge></td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function Thresholds() {
  const { thresholds, currencies, reload } = useData()
  const [draft, setDraft] = useState(thresholds)
  const [saved, setSaved] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => { setDraft(thresholds) }, [thresholds])

  const save = async (c) => {
    const v = Number(draft[c])
    if (!Number.isFinite(v) || v <= 0) return
    setError(null)
    try {
      await api.setCurrencyThreshold(c, v)
      await reload()
      setSaved(c)
      setTimeout(() => setSaved(null), 1800)
    } catch (e) { setError(e.message) }
  }

  return (
    <Card title="Minimum cash thresholds" subtitle="Each currency has its own threshold. They are never converted or applied across currencies.">
      <ErrorNotice error={error} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {currencies.map((c) => (
          <div key={c} className="rounded-lg border border-line p-4">
            <div className="mb-2 flex items-center justify-between"><span className="font-heading text-base font-extrabold">{c}</span><span className="text-xs text-muted">Default {money(DEFAULT_THRESHOLDS[c] ?? 60000, c)}</span></div>
            <label className="label" htmlFor={`t-${c}`}>Minimum balance ({c})</label>
            <input id={`t-${c}`} type="number" min="1" className="input" value={draft[c] ?? ''} onChange={(e) => setDraft({ ...draft, [c]: e.target.value })} />
            <button className="btn-primary mt-3 w-full" onClick={() => save(c)}>{saved === c ? <><Check size={15} /> Saved</> : 'Save'}</button>
          </div>
        ))}
      </div>
      <div className="mt-4"><Notice tone="blue">Saving re-evaluates the stored forecasts and alerts for that currency immediately (no model refit needed).</Notice></div>
    </Card>
  )
}

export default function Settings() {
  const [tab, setTab] = useState('User management')
  return (
    <div className="space-y-4">
      <PageHeader title="Settings" description="Administer users, role permissions and per-currency thresholds."><DemoTag /></PageHeader>
      <Tabs tabs={['User management', 'Role permissions', 'Threshold configuration']} value={tab} onChange={setTab} />
      {tab === 'User management' && <UserManagement />}
      {tab === 'Role permissions' && <Permissions />}
      {tab === 'Threshold configuration' && <Thresholds />}
    </div>
  )
}
