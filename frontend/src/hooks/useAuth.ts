import { useContext } from 'react'
import { AuthContext } from '../context/AuthContext'
import type { AuthValue } from '../context/AuthContext'

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (value === null) throw new Error('useAuth must be used inside AuthProvider')
  return value
}