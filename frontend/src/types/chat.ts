export type Role = 'user' | 'assistant'

export interface Source {
  document: string
  category: string
  section: string
  chunk_id: string
  similarity: number
}

export interface ChatMessage {
  id: string
  role: Role
  content: string
  sources?: Source[]
}

export interface ChatReply {
  reply: string
  sources: Source[]
}