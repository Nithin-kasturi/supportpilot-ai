import type { Profile } from '../types/auth'
import { apiFetch, errorMessage } from './http'

export async function login(email: string, password: string): Promise<Profile> {
  const response = await apiFetch(
    '/api/auth/login',
    { method: 'POST', body: JSON.stringify({ email, password }) },
    { silent401: true },
  )
  if (response.status === 401) throw new Error('Invalid email or password.')
  if (!response.ok) throw new Error(await errorMessage(response))
  return (await response.json()) as Profile
}

export async function logout(): Promise<void> {
  await apiFetch('/api/auth/logout', { method: 'POST' }, { silent401: true })
}

/** Returns null when not signed in (no "session expired" banner for the initial check). */
export async function fetchProfile(): Promise<Profile | null> {
  const response = await apiFetch('/api/me', {}, { silent401: true })
  if (response.status === 401) return null
  if (!response.ok) throw new Error(await errorMessage(response))
  return (await response.json()) as Profile
}