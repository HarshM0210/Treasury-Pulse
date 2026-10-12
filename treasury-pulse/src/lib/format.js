// Formatting, level helpers and role policy. All data comes from the API.

export const ROLES = ['Analyst', 'Treasury Manager', 'Admin']
export const ROLE_FROM_API = { ANALYST: 'Analyst', TREASURY_MANAGER: 'Treasury Manager', ADMIN: 'Admin' }
export const ROLE_TO_API = { Analyst: 'ANALYST', 'Treasury Manager': 'TREASURY_MANAGER', Admin: 'ADMIN' }

// Same defaults as server/treasury/defaults.py (shown as "Default" in Settings)
export const DEFAULT_THRESHOLDS = { EUR: 50000, USD: 60000, GBP: 40000, JPY: 5000000, AED: 220000, BRL: 355000, HKD: 470000, INR: 5000000, SGD: 81000 }

export const ALERT_LEVELS = ['emergency', 'critical', 'warning']
export const isAtRisk = (level) => ALERT_LEVELS.includes(String(level || '').toLowerCase())

// ── Formatting ───────────────────────────────────────────────
const isCcy = (c) => typeof c === 'string' && /^[A-Z]{3}$/.test(c)

export const money = (n, ccy = 'USD', opts = {}) => {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '—'
  return new Intl.NumberFormat('en-US', isCcy(ccy)
    ? { style: 'currency', currency: ccy, maximumFractionDigits: 0, ...opts }
    : { maximumFractionDigits: 0, ...opts }).format(n)
}

export const signedMoney = (n, ccy) => {
  if (n === null || n === undefined) return '—'
  return (n > 0 ? '+' : n < 0 ? '−' : '') + money(Math.abs(n), ccy)
}

export const compact = (n, ccy) =>
  new Intl.NumberFormat('en-US', {
    style: isCcy(ccy) ? 'currency' : 'decimal',
    currency: isCcy(ccy) ? ccy : undefined,
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(n)

export const pct = (x, digits = 1) => (x === null || x === undefined ? '—' : `${(x * 100).toFixed(digits)}%`)

export const fmtDay = (iso) => {
  if (!iso) return '—'
  const d = new Date(`${iso}T00:00:00`)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}
export const fmtDate = (iso) => {
  if (!iso) return '—'
  const d = new Date(String(iso).length <= 10 ? `${iso}T00:00:00` : iso)
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}
export const fmtDateTime = (iso) => {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export const CCY_COLORS = ['#3478F6', '#7C6BD6', '#16A34A', '#F59E0B', '#5B7399', '#DC2626', '#0EA5E9', '#A855F7', '#14B8A6', '#F97316']

// ── Role policy (shown in Settings → Role permissions) ───────
export const PERMISSIONS = [
  { capability: 'Assigned entity data', analyst: 'Yes', manager: 'Yes', admin: 'All data' },
  { capability: 'Regional aggregates', analyst: 'Limited', manager: 'Yes', admin: 'Yes' },
  { capability: 'Forecasts', analyst: 'Yes', manager: 'Yes', admin: 'Yes' },
  { capability: 'What-if scenarios', analyst: 'Yes', manager: 'Yes', admin: 'Yes' },
  { capability: 'Alert monitoring', analyst: 'Permitted scope', manager: 'Regional scope', admin: 'Full management' },
  { capability: 'Reports', analyst: 'Personal', manager: 'Regional', admin: 'Full scheduler management' },
  { capability: 'CSV upload', analyst: 'No', manager: 'No', admin: 'Yes' },
  { capability: 'User management', analyst: 'No', manager: 'No', admin: 'Yes' },
  { capability: 'Threshold configuration', analyst: 'No', manager: 'No', admin: 'Yes' },
]
