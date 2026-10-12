import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import * as api from '../services/api'
import { useAuth } from './AuthContext'

const DataContext = createContext(null)

/**
 * Loads shared data once the user is signed in:
 *  1. POST /ml/refresh  → ML Script 2 (fits Prophet only if the data changed)
 *  2. GET  /analytics/summary  → entity rows (balance, forecast, threshold, level)
 *  3. GET  /alerts
 */
export function DataProvider({ children }) {
  const { signedIn, user } = useAuth()
  const [summary, setSummary] = useState(null)
  const [alerts, setAlerts] = useState([])
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)
  const [lastRun, setLastRun] = useState(null)

  const reloadAlerts = useCallback(async () => {
    setAlerts(await api.getAlerts())
  }, [])

  const reload = useCallback(async () => {
    const [s, a] = await Promise.all([api.getSummary(), api.getAlerts()])
    setSummary(s)
    setAlerts(a)
  }, [])

  const runPipeline = useCallback(async (force = false) => {
    setRefreshing(true)
    setError(null)
    try {
      const run = await api.refreshForecasts(force)
      setLastRun(run)
      await reload()
    } catch (e) {
      setError(e.message)
    } finally {
      setRefreshing(false)
    }
  }, [reload])

  useEffect(() => {
    if (!signedIn) { setSummary(null); setAlerts([]); return }
    setLoading(true)
    runPipeline(false).finally(() => setLoading(false))
  }, [signedIn, user?.id, runPipeline])

  const value = useMemo(() => {
    const entities = summary?.entities || []
    const usdRates = summary?.usd_rates || { USD: 1 }
    const thresholds = {}
    entities.forEach((e) => { if (thresholds[e.currency] === undefined) thresholds[e.currency] = e.threshold })
    return {
      summary,
      entities,
      alerts,
      asOf: summary?.as_of,
      regions: summary?.regions || [],
      currencies: summary?.currencies || [],
      usdRates,
      thresholds,
      openAlerts: alerts.filter((a) => a.status !== 'RESOLVED').length,
      toUsd: (amount, ccy) => (amount ?? 0) * (usdRates[ccy] ?? 1),
      loading,
      refreshing,
      error,
      lastRun,
      reload,
      reloadAlerts,
      runPipeline,
    }
  }, [summary, alerts, loading, refreshing, error, lastRun, reload, reloadAlerts, runPipeline])

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>
}

export const useData = () => useContext(DataContext)
