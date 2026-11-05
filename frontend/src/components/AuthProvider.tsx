import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { AuthContext } from '../context/AuthContext'
import type { AuthStatus, AuthValue } from '../context/AuthContext'
import { fetchProfile, login, logout } from '../services/authApi'
import { setUnauthorizedHandler } from '../services/http'
import type { Profile } from '../types/auth'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Profile | null>(null)
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [sessionExpired, setSessionExpired] = useState(false)

  useEffect(() => {
    let cancelled = false
    fetchProfile()
      .then((profile) => {
        if (cancelled) return
        setUser(profile)
        setStatus(profile ? 'authenticated' : 'anonymous')
      })
      .catch(() => {
        if (!cancelled) setStatus('anonymous')
      })
    // Any later 401 means the session ended (expiry, logout elsewhere, deactivation).
    setUnauthorizedHandler(() => {
      setUser(null)
      setStatus('anonymous')
      setSessionExpired(true)
    })
    return () => {
      cancelled = true
      setUnauthorizedHandler(null)
    }
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    const profile = await login(email, password)
    setSessionExpired(false)
    setUser(profile)
    setStatus('authenticated')
  }, [])

  const signOut = useCallback(async () => {
    try {
      await logout()
    } finally {
      setUser(null)
      setStatus('anonymous')
      setSessionExpired(false)
    }
  }, [])

  const value = useMemo<AuthValue>(
    () => ({ user, status, sessionExpired, signIn, signOut }),
    [user, status, sessionExpired, signIn, signOut],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}