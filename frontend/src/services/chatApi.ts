import type { ChatReply, Source } from '../types/chat'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const REQUEST_TIMEOUT_MS = 130_000

function isSource(value: unknown): value is Source {
  if (typeof value !== 'object' || value === null) return false
  const s = value as Record<string, unknown>
  return (
    typeof s.document === 'string' &&
    typeof s.category === 'string' &&
    typeof s.section === 'string' &&
    typeof s.chunk_id === 'string' &&
    typeof s.similarity === 'number'
  )
}

export async function sendChatMessage(message: string): Promise<ChatReply> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

  try {
    let response: Response
    try {
      response = await fetch(`${API_BASE_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
        signal: controller.signal,
      })
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw new Error('The request timed out. Please try again.')
      }
      throw new Error('Cannot reach the SupportPilot server. Make sure the backend is running.')
    }

    if (!response.ok) {
      if (response.status === 422) {
        throw new Error('Your message must be between 1 and 2000 characters.')
      }
      let detail = `Request failed with status ${response.status}.`
      try {
        const body = await response.json()
        if (typeof body.detail === 'string') detail = body.detail
      } catch {
        // response body was not JSON; keep the default message
      }
      throw new Error(detail)
    }

    let data: unknown
    try {
      data = await response.json()
    } catch {
      throw new Error('Received an unexpected response from the server.')
    }

    const body = data as { reply?: unknown; sources?: unknown } | null
    const reply = body?.reply
    if (typeof reply !== 'string' || !reply.trim()) {
      throw new Error('Received an unexpected response from the server.')
    }

    const rawSources = body?.sources
    const sources = Array.isArray(rawSources) ? rawSources.filter(isSource) : []
    return { reply, sources }
  } finally {
    clearTimeout(timer)
  }
}