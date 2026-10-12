import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { Eye, EyeOff, Landmark } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { Notice } from '../components/ui'

// Accounts created by `python manage.py seed_demo`
const DEMO_ACCOUNTS = [
  ['admin', 'admin12345', 'Admin · all entities'],
  ['manager_emea', 'manager12345', 'Treasury Manager · EMEA'],
  ['analyst_london', 'analyst12345', 'Analyst · London, Paris'],
]

function Globe() {
  // Simple network-globe illustration
  const nodes = [[110, 90], [200, 60], [270, 120], [160, 170], [90, 200], [250, 220], [190, 250]]
  return (
    <svg viewBox="0 0 360 320" className="mx-auto w-full max-w-[340px]" aria-hidden>
      <defs>
        <radialGradient id="g" cx="40%" cy="35%">
          <stop offset="0%" stopColor="#3478F6" stopOpacity="0.55" />
          <stop offset="100%" stopColor="#101C2D" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="180" cy="160" r="130" fill="url(#g)" />
      <g fill="none" stroke="#3478F6" strokeOpacity="0.45">
        <circle cx="180" cy="160" r="130" />
        <ellipse cx="180" cy="160" rx="55" ry="130" />
        <ellipse cx="180" cy="160" rx="100" ry="130" />
        <path d="M50 160h260M70 100h220M70 220h220" />
      </g>
      <g stroke="#7FB0FF" strokeOpacity="0.7">
        {nodes.slice(1).map((n, i) => <line key={i} x1={nodes[i][0]} y1={nodes[i][1]} x2={n[0]} y2={n[1]} />)}
      </g>
      {nodes.map(([x, y], i) => <circle key={i} cx={x} cy={y} r="4" fill="#9CC4FF" />)}
    </svg>
  )
}

export default function Login() {
  const { signedIn, signIn } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  if (signedIn) return <Navigate to="/overview" replace />

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await signIn(username.trim(), password)
      navigate('/overview')
    } catch (err) {
      setError(err.status === 401 ? 'Invalid username or password.' : err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-full lg:grid-cols-[1.05fr_1fr]">
      <div className="hidden flex-col justify-between bg-navy p-10 text-white lg:flex">
        <div className="flex items-center gap-2.5">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand"><Landmark size={20} /></span>
          <span className="font-heading text-lg font-extrabold">Treasury Pulse</span>
        </div>
        <div>
          <Globe />
          <h1 className="mt-6 text-center text-4xl font-extrabold tracking-tight">Treasury Pulse</h1>
          <p className="mt-2 text-center text-lg text-slate-300">AI-powered short-term liquidity manager</p>
        </div>
        <p className="text-center text-sm text-slate-400">Global visibility &nbsp;•&nbsp; Predictive intelligence &nbsp;•&nbsp; Proactive decisions</p>
      </div>

      <div className="flex items-center justify-center bg-white p-6 sm:p-10">
        <form onSubmit={submit} className="w-full max-w-sm">
          <div className="mb-6 flex items-center gap-2 lg:hidden">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-navy text-white"><Landmark size={18} /></span>
            <span className="font-heading text-lg font-extrabold">Treasury Pulse</span>
          </div>
          <h2 className="text-3xl font-extrabold tracking-tight">Welcome back</h2>
          <p className="mb-6 mt-1 text-sm text-muted">Sign in to your account</p>

          <label className="label" htmlFor="username">Username</label>
          <input id="username" autoComplete="username" className="input mb-4" placeholder="e.g. analyst_london" value={username} onChange={(e) => setUsername(e.target.value)} required />
          <label className="label" htmlFor="pw">Password</label>
          <div className="relative mb-5">
            <input id="pw" type={show ? 'text' : 'password'} autoComplete="current-password" className="input pr-10" placeholder="Enter password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            <button type="button" onClick={() => setShow(!show)} className="absolute right-2.5 top-2.5 text-muted" aria-label={show ? 'Hide password' : 'Show password'}>
              {show ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>

          {error && <div className="mb-4"><Notice tone="red">{error}</Notice></div>}
          <button className="btn-dark w-full py-2.5" type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        </form>
      </div>
    </div>
  )
}
