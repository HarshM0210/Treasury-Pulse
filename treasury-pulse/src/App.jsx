import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import Layout from './components/Layout'
import { Loading } from './components/ui'
import Login from './pages/Login'
import Overview from './pages/Overview'
import Transactions from './pages/Transactions'
import Forecasts from './pages/Forecasts'
import RiskAlerts from './pages/RiskAlerts'
import WhatIf from './pages/WhatIf'
import CounterpartyRisk from './pages/CounterpartyRisk'
import AIAssistant from './pages/AIAssistant'
import Reports from './pages/Reports'
import Settings from './pages/Settings'

function Protected({ children }) {
  const { signedIn, checking } = useAuth()
  if (checking) return <Loading label="Checking your session…" />
  return signedIn ? children : <Navigate to="/login" replace />
}

function AdminOnly({ children }) {
  const { role } = useAuth()
  return role === 'Admin' ? children : <Navigate to="/overview" replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Protected><Layout /></Protected>}>
        <Route path="/overview" element={<Overview />} />
        <Route path="/transactions" element={<Transactions />} />
        <Route path="/forecasts" element={<Forecasts />} />
        <Route path="/alerts" element={<RiskAlerts />} />
        <Route path="/what-if" element={<WhatIf />} />
        <Route path="/counterparty" element={<CounterpartyRisk />} />
        <Route path="/assistant" element={<AIAssistant />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/settings" element={<AdminOnly><Settings /></AdminOnly>} />
      </Route>
      <Route path="*" element={<Navigate to="/overview" replace />} />
    </Routes>
  )
}
