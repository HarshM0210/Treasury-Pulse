import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import * as api from '../services/api'
import { ROLE_FROM_API } from '../lib/format'

const AuthContext = createContext(null)

// Real authentication against Django (session cookie). The role comes from
// the server; the UI cannot switch it.
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    api.getMe().then(setUser).catch(() => setUser(null)).finally(() => setChecking(false))
  }, [])

  const signIn = useCallback(async (username, password) => {
    const res = await api.login(username, password)
    if (!res.user?.role) throw new Error('This account has no Treasury Pulse role. Ask an admin to assign one.')
    setUser(res.user)
    return res.user
  }, [])

  const signOut = useCallback(async () => {
    try { await api.logout() } catch { /* session may already be gone */ }
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({
      user,
      checking,
      signedIn: !!user,
      role: ROLE_FROM_API[user?.role] || 'Analyst',
      signIn,
      signOut,
    }),
    [user, checking, signIn, signOut]
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)
