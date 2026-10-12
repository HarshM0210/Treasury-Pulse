// ─────────────────────────────────────────────────────────────
// API SERVICE LAYER — every backend call goes through here.
// Pages never call fetch() directly.
//
// Auth: Django session cookie (tp_session) + CSRF token (csrftoken cookie
// sent back as the X-CSRFToken header on POST/PATCH/PUT/DELETE).
// In development Vite proxies /api to Django (see vite.config.js).
// ─────────────────────────────────────────────────────────────
const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

function getCookie(name) {
  const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'))
  return m ? decodeURIComponent(m[1]) : null
}

export class ApiError extends Error {
  constructor(status, message, body) {
    super(message)
    this.status = status
    this.body = body
  }
}

async function ensureCsrf() {
  if (!getCookie('csrftoken')) await fetch(`${BASE_URL}/api/auth/csrf/`, { credentials: 'include' })
}

async function request(path, { method = 'GET', body, form, query } = {}) {
  const unsafe = method !== 'GET'
  if (unsafe) await ensureCsrf()
  const qs = query
    ? '?' + new URLSearchParams(Object.entries(query).filter(([, v]) => v !== undefined && v !== null && v !== '')).toString()
    : ''
  const headers = {}
  if (unsafe) headers['X-CSRFToken'] = getCookie('csrftoken') || ''
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(`${BASE_URL}${path}${qs}`, {
    method,
    credentials: 'include',
    headers,
    body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
  })
  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = { detail: text } }
  if (!res.ok) {
    const msg = data?.detail || data?.error?.message || (data && typeof data === 'object' ? Object.values(data).flat().join(' ') : '') || `Request failed (${res.status})`
    throw new ApiError(res.status, msg, data)
  }
  return data
}

// ── Auth ─────────────────────────────────────────────────────
export const login = async (username, password) => {
  await ensureCsrf()
  return request('/api/auth/login/', { method: 'POST', body: { username, password } })
}
export const logout = () => request('/api/auth/logout/', { method: 'POST' })
export const getMe = () => request('/api/auth/me/')

// ── ML pipeline ──────────────────────────────────────────────
// Script 2: fits Prophet only if the data changed since the last run.
export const refreshForecasts = (force = false) => request('/api/v1/ml/refresh/', { method: 'POST', body: { force } })

// ── Analytics (Script 2 output, stored in the database) ──────
export const getSummary = (horizon = 30) => request('/api/v1/analytics/summary/', { query: { horizon } })
export const getForecast = (entityId, horizon = 30, history = 30) =>
  request(`/api/v1/analytics/forecast/${entityId}/`, { query: { horizon, history } })
export const getTotalForecast = (horizon = 30, history = 30) => request('/api/v1/analytics/forecast/total/', { query: { horizon, history } })
export const getUpcoming = (days = 7, limit = 8) => request('/api/v1/analytics/upcoming/', { query: { days, limit } })
export const getCounterparties = () => request('/api/v1/analytics/counterparties/')

// Script 3: what-if. parameters = { payment_delay_days, capex_postpone_days,
// fx_shock_pct, rate_shock_bps, rating_shift: { counterparty, new_rating } }
export const runWhatIf = ({ entityId, horizon = 30, parameters = {} }) =>
  request('/api/v1/analytics/what-if/', { method: 'POST', body: { entity_id: entityId, horizon, parameters } })

// ── Alerts ───────────────────────────────────────────────────
export const getAlerts = () => request('/api/v1/alerts/')
export const acknowledgeAlert = (id) => request(`/api/v1/alerts/${id}/acknowledge/`, { method: 'POST' })
export const resolveAlert = (id) => request(`/api/v1/alerts/${id}/resolve/`, { method: 'POST' })

// ── Transactions ─────────────────────────────────────────────
export const getTransactions = (params) => request('/api/v1/transactions/', { query: params })
export function uploadTransactionsCsv(file) {
  const form = new FormData()
  form.append('file', file)
  return request('/api/v1/transactions/upload/', { method: 'POST', form })
}

// ── Admin ────────────────────────────────────────────────────
export const setCurrencyThreshold = (currency, minimumBalance) =>
  request('/api/v1/admin-liquidity-thresholds/set-currency/', { method: 'POST', body: { currency, minimum_balance: minimumBalance } })
export const getUsers = () => request('/api/v1/admin/users/')
export const createUser = (data) => request('/api/v1/admin/users/', { method: 'POST', body: data })
export const updateUser = (id, data) => request(`/api/v1/admin/users/${id}/`, { method: 'PATCH', body: data })
export const setUserActive = (id, isActive) => request(`/api/v1/admin/users/${id}/set-active/`, { method: 'POST', body: { is_active: isActive } })

// ─────────────────────────────────────────────────────────────
// AI ASSISTANT — server/copilot (POST /api/v1/assistant/chat/)
// Returns { reply, intent, params, visualization, llm_used, model, ... }.
// Facts come from live data scoped to the logged-in user; an LLM (Ollama) only rephrases them.
// ─────────────────────────────────────────────────────────────
export const askAssistant = ({ message, history = [], context = {} }) =>
  request('/api/v1/assistant/chat/', {
    method: 'POST',
    body: {
      message,
      history: history.filter((m) => m.role === 'user' || m.role === 'assistant').slice(-8).map(({ role, content }) => ({ role, content })),
      context,
    },
  })
export const getAssistantStatus = () => request('/api/v1/assistant/status/')
