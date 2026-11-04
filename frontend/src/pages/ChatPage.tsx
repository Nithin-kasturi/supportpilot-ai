import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { MessageBubble } from '../components/MessageBubble'
import { resolveConfirmation, sendAgentMessage } from '../services/chatApi'
import type { ChatMessage } from '../types/chat'

const WELCOME: ChatMessage = {
  id: 'welcome',
  role: 'assistant',
  content:
    "Hi, I'm SupportPilot AI. I can check your orders, explain refund eligibility and company policies, and help you request a refund or open a support ticket. How can I help you today?",
}

export function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [conversationId] = useState(() => crypto.randomUUID())
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading, error])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const text = input.trim()
    if (!text || isLoading) return

    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'user', content: text }])
    setInput('')
    setError(null)
    setIsLoading(true)

    try {
      const reply = await sendAgentMessage(text, conversationId)
      const next: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: reply.reply,
        sources: reply.sources,
        actions: reply.actions,
        confirmation: reply.confirmation ?? undefined,
        confirmationState: reply.confirmation ? 'pending' : undefined,
      }
      setMessages((prev) => [
        // The server cancels older pending confirmations when a new one is prepared.
        ...prev.map((m) =>
          reply.confirmation && m.confirmation && m.confirmationState !== 'done'
            ? { ...m, confirmationState: 'done' as const }
            : m,
        ),
        next,
      ])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setIsLoading(false)
    }
  }

  async function handleDecision(messageId: string, decision: 'confirm' | 'cancel') {
    const target = messages.find((m) => m.id === messageId)
    if (!target?.confirmation) return

    setError(null)
    setMessages((prev) =>
      prev.map((m) => (m.id === messageId ? { ...m, confirmationState: 'working' as const } : m)),
    )
    try {
      const result = await resolveConfirmation(target.confirmation.id, decision)
      setMessages((prev) => [
        ...prev.map((m) => (m.id === messageId ? { ...m, confirmationState: 'done' as const } : m)),
        { id: crypto.randomUUID(), role: 'assistant', content: result.reply },
      ])
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) => (m.id === messageId ? { ...m, confirmationState: 'pending' as const } : m)),
      )
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    }
  }

  return (
    <div className="chat-container">
      <header className="chat-header">
        <span className="logo">📦</span>
        <div>
          <h1>SupportPilot AI</h1>
          <p>Parcel delivery support assistant</p>
        </div>
      </header>

      <main className="chat-messages">
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} busy={isLoading} onDecision={handleDecision} />
        ))}
        {isLoading && (
          <div className="message-row assistant">
            <div className="bubble typing" aria-label="SupportPilot is typing">
              <span />
              <span />
              <span />
            </div>
          </div>
        )}
        {error && <div className="error-banner">{error}</div>}
        <div ref={bottomRef} />
      </main>

      <form className="chat-input" onSubmit={handleSubmit}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type your message..."
          disabled={isLoading}
          autoFocus
        />
        <button type="submit" disabled={isLoading || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  )
}