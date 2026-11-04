export type Role = 'user' | 'assistant'

export interface Source {
  document: string
  category: string
  section: string
  chunk_id: string
  similarity: number
}

export interface AgentAction {
  tool: string
  label: string
  ok: boolean
}

export interface ConfirmationPrompt {
  id: string
  kind: 'refund_request' | 'support_ticket'
  title: string
  details: string[]
  expires_at: string
}

export type ConfirmationState = 'pending' | 'working' | 'done'

export interface ChatMessage {
  id: string
  role: Role
  content: string
  sources?: Source[]
  actions?: AgentAction[]
  confirmation?: ConfirmationPrompt
  confirmationState?: ConfirmationState
}

export interface AgentReply {
  reply: string
  intent: string
  sources: Source[]
  actions: AgentAction[]
  confirmation: ConfirmationPrompt | null
}

export interface ConfirmReply {
  outcome: 'created' | 'cancelled' | 'failed' | 'expired' | 'not_found' | 'already_resolved'
  reply: string
  reference: string | null
  status: string | null
}