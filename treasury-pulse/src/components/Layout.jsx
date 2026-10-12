import { useMemo, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Bell, Bot, ChevronRight, FileText, Globe2, Landmark, LayoutDashboard, LogOut, Menu, RefreshCw,
  Settings, ShieldCheck, ShieldAlert, SlidersHorizontal, Table2, TrendingUp, Users, X,
} from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { useData } from '../context/DataContext'
import { fmtDate } from '../lib/format'
import ChatWidget from './ChatWidget'

const NAV = [
  { to: '/overview', label: 'Overview', icon: LayoutDashboard },
  { to: '/transactions', label: 'Transactions', icon: Table2 },
  { to: '/forecasts', label: 'Forecasts', icon: TrendingUp },
  { to: '/alerts', label: 'Risk & Alerts', icon: ShieldAlert, badge: true, analystHidden: true },
  { to: '/what-if', label: 'What-if Analysis', icon: SlidersHorizontal },
  { to: '/counterparty', label: 'Counterparty Risk', icon: Users },
  { to: '/assistant', label: 'AI Assistant', icon: Bot },
  { to: '/reports', label: 'Reports', icon: FileText },
  { to: '/settings', label: 'Settings', icon: Settings, adminOnly: true },
]

const CRUMBS = Object.fromEntries(NAV.map((n) => [n.to, n.label]))

export const roleTone = { Analyst: 'bg-ok-soft text-ok', 'Treasury Manager': 'bg-brand-soft text-brand-dark', Admin: 'bg-violet-soft text-violet' }

function Sidebar({ onNavigate }) {
  const { role, user, signOut } = useAuth()
  const { openAlerts } = useData()
  const navigate = useNavigate()
  const items = NAV.filter((n) => (!n.adminOnly || role === 'Admin') && (!n.analystHidden || role !== 'Analyst'))

  return (
    <div className="flex h-full flex-col bg-navy text-slate-300">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand text-white">
          <Landmark size={19} />
        </span>
        <span className="font-heading text-lg font-extrabold text-white">Treasury Pulse</span>
      </div>
      <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-2" aria-label="Main navigation">
        {items.map(({ to, label, icon: Icon, badge }) => (
          <NavLink
            key={to}
            to={to}
            onClick={onNavigate}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold transition-colors ${
                isActive ? 'bg-brand text-white' : 'hover:bg-white/5 hover:text-white'
              }`
            }
          >
            <Icon size={18} />
            <span className="flex-1">{label}</span>
            {badge && openAlerts > 0 && (
              <span className="rounded-full bg-crit px-1.5 py-0.5 text-[10px] font-bold leading-none text-white">{openAlerts}</span>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="space-y-3 border-t border-white/10 p-4">
        <div className="flex items-center gap-2 rounded-lg bg-white/5 px-3 py-2 text-xs">
          <ShieldCheck size={16} className="text-ok" />
          <div>
            <p className="font-semibold text-white">Secure workspace</p>
            <p className="text-slate-400">Signed in as {user?.username}</p>
          </div>
        </div>
        <button
          onClick={async () => { await signOut(); navigate('/login') }}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-semibold hover:bg-white/5 hover:text-white"
        >
          <LogOut size={18} /> Sign out
        </button>
      </div>
    </div>
  )
}

export default function Layout() {
  const [drawer, setDrawer] = useState(false)
  const { role, user } = useAuth()
  const { openAlerts, asOf, refreshing, error } = useData()
  const initials = (user?.name || user?.username || '?').split(/[\s_]+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase()
  const { pathname } = useLocation()
  const page = useMemo(() => CRUMBS[pathname] || 'Overview', [pathname])

  return (
    <div className="flex h-full">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 lg:block">
        <Sidebar />
      </aside>

      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-navy/60" onClick={() => setDrawer(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 shadow-pop">
            <button className="absolute right-3 top-4 z-10 rounded p-1 text-slate-300 hover:bg-white/10" onClick={() => setDrawer(false)} aria-label="Close menu">
              <X size={18} />
            </button>
            <Sidebar onNavigate={() => setDrawer(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col lg:pl-64">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-line bg-white px-4 lg:px-6">
          <button className="rounded-lg p-2 text-ink hover:bg-surface lg:hidden" onClick={() => setDrawer(true)} aria-label="Open menu">
            <Menu size={20} />
          </button>
          <nav className="flex items-center gap-1.5 text-sm" aria-label="Breadcrumb">
            <span className="hidden text-muted sm:inline">Treasury Pulse</span>
            <ChevronRight size={14} className="hidden text-muted sm:inline" />
            <span className="font-semibold text-ink">{page}</span>
          </nav>

          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            <span className={`hidden items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold md:flex ${error ? 'bg-crit-soft text-crit' : 'bg-violet-soft text-violet'}`} title={error || ''}>
              <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
              {error ? 'Forecast refresh failed' : refreshing ? 'Updating forecast…' : `Forecast as of ${fmtDate(asOf)}`}
            </span>
            {role !== 'Analyst' && (
              <NavLink to="/alerts" className="relative rounded-lg p-2 text-ink hover:bg-surface" aria-label={`${openAlerts} open alerts`}>
                <Bell size={19} />
                <span className="absolute right-1 top-1 flex h-4 w-4 items-center justify-center rounded-full bg-crit text-[10px] font-bold text-white">{openAlerts}</span>
              </NavLink>
            )}
            <span className={`rounded-lg px-2.5 py-1.5 text-xs font-bold ${roleTone[role]}`} title="Your role (set by an admin)">{role}</span>
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-navy-700 text-xs font-bold text-white" title={user?.name} aria-hidden>
              {initials}
            </span>
          </div>
        </header>

        <main className="flex-1 px-4 py-5 lg:px-6">
          <Outlet />
        </main>
        <footer className="no-print flex items-center gap-1.5 px-6 pb-4 text-xs text-muted">
          <Globe2 size={13} /> Amounts stay in their own currency unless labelled “USD equivalent” (converted at FX rates derived from the transaction data).
        </footer>
      </div>

      <ChatWidget />
    </div>
  )
}
