import { createContext } from 'react'
import type { Profile } from '../types/auth'

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

export interface AuthValue {
  user: Profile | null
  status: AuthStatus
  sessionExpired: boolean
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthValue | null>(null)