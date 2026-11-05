export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export class UnauthorizedError extends Error {}

let unauthorizedHandler: (() => void) | null = null

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

interface Options {
  timeoutMs?: number
  /** Do not treat 401 as an expired session (used for the initial "who am I" call and for login). */
  silent401?: boolean
}

/**
 * Every request sends the session cookie (HttpOnly, so scripts never see the token) and the CSRF
 * header the backend requires. No token is ever stored in JS-accessible storage.
 */
export async function apiFetch(path: string, init: RequestInit = {}, options: Options = {}): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? 30_000)
  try {
    const headers: Record<string, string> = { 'X-Requested-With': 'SupportPilot' }
    if (init.body) headers['Content-Type'] = 'application/json'

    let response: Response
    try {
      response = await fetch(`${API_BASE_URL}${path}`, {
        ...init,
        headers,
        credentials: 'include',
        signal: controller.signal,
      })
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw new Error('The request timed out. Please try again.')
      }
      throw new Error('Cannot reach the SupportPilot server. Make sure the backend is running.')
    }

    if (response.status === 401 && !options.silent401) {
      unauthorizedHandler?.()
      throw new UnauthorizedError('Your session has expired. Please sign in again.')
    }
    return response
  } finally {
    clearTimeout(timer)
  }
}

export async function errorMessage(response: Response): Promise<string> {
  if (response.status === 422) return 'Some of the details entered are not valid. Please check them and try again.'
  if (response.status === 429) return 'Too many requests. Please wait a moment and try again.'
  if (response.status === 403) return 'You do not have permission to do that.'
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') return body.detail
  } catch {
    // body was not JSON
  }
  return `Request failed with status ${response.status}.`
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await apiFetch(path)
  if (!response.ok) throw new Error(await errorMessage(response))
  return (await response.json()) as T
}

export async function sendJson<T>(method: string, path: string, body: unknown): Promise<T> {
  const response = await apiFetch(path, { method, body: JSON.stringify(body) })
  if (!response.ok) throw new Error(await errorMessage(response))
  return (await response.json()) as T
}