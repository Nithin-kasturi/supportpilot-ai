import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { MessageBubble } from '../components/MessageBubble'
import { sendChatMessage } from '../services/chatApi'
import type { ChatMessage } from '../types/chat'

const WELCOME: ChatMessage = {
  id: 'welcome',
  role: 'assistant',
  content:
    "Hi, I'm SupportPilot AI. I can help with order tracking, damaged parcels, refunds and complaints. How can I help you today?",
}

export function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
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
      const reply = await sendChatMessage(text)
      setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'assistant', content: reply }])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setIsLoading(false)
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
          <MessageBubble key={m.id} message={m} />
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