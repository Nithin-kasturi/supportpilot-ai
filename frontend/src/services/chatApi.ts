import type { AgentAction, AgentReply, ConfirmationPrompt, ConfirmReply, Source } from '../types/chat'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
// A turn can involve two model calls, so allow longer than a single Ollama timeout.
const REQUEST_TIMEOUT_MS = 240_000

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

function isAction(value: unknown): value is AgentAction {
  if (typeof value !== 'object' || value === null) return false
  const a = value as Record<string, unknown>
  return typeof a.tool === 'string' && typeof a.label === 'string' && typeof a.ok === 'boolean'
}

function isConfirmation(value: unknown): value is ConfirmationPrompt {
  if (typeof value !== 'object' || value === null) return false
  const c = value as Record<string, unknown>
  return (
    typeof c.id === 'string' &&
    (c.kind === 'refund_request' || c.kind === 'support_ticket') &&
    typeof c.title === 'string' &&
    Array.isArray(c.details) &&
    typeof c.expires_at === 'string'
  )
}

async function post(path: string, body: unknown): Promise<unknown> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

  try {
    let response: Response
    try {
      response = await fetch(`${API_BASE_URL}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
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
        const data = await response.json()
        if (typeof data.detail === 'string') detail = data.detail
      } catch {
        // response body was not JSON; keep the default message
      }
      throw new Error(detail)
    }

    try {
      return await response.json()
    } catch {
      throw new Error('Received an unexpected response from the server.')
    }
  } finally {
    clearTimeout(timer)
  }
}

export async function sendAgentMessage(message: string, conversationId: string): Promise<AgentReply> {
  const data = (await post('/api/agent/chat', { message, conversation_id: conversationId })) as {
    reply?: unknown
    intent?: unknown
    sources?: unknown
    actions?: unknown
    confirmation?: unknown
  } | null

  if (typeof data?.reply !== 'string' || !data.reply.trim()) {
    throw new Error('Received an unexpected response from the server.')
  }
  return {
    reply: data.reply,
    intent: typeof data.intent === 'string' ? data.intent : '',
    sources: Array.isArray(data.sources) ? data.sources.filter(isSource) : [],
    actions: Array.isArray(data.actions) ? data.actions.filter(isAction) : [],
    confirmation: isConfirmation(data.confirmation) ? data.confirmation : null,
  }
}

export async function resolveConfirmation(
  confirmationId: string,
  decision: 'confirm' | 'cancel',
): Promise<ConfirmReply> {
  const data = (await post('/api/agent/confirm', {
    confirmation_id: confirmationId,
    decision,
  })) as ConfirmReply | null
  if (typeof data?.reply !== 'string' || typeof data.outcome !== 'string') {
    throw new Error('Received an unexpected response from the server.')
  }
  return data
}