import type { AgentAction, AgentReply, ConfirmationPrompt, ConfirmReply, Source } from '../types/chat'
import { apiFetch, errorMessage } from './http'

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
  const response = await apiFetch(
    path,
    { method: 'POST', body: JSON.stringify(body) },
    { timeoutMs: REQUEST_TIMEOUT_MS },
  )
  if (!response.ok) throw new Error(await errorMessage(response))
  try {
    return await response.json()
  } catch {
    throw new Error('Received an unexpected response from the server.')
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