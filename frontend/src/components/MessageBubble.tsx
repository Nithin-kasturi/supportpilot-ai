import type { ChatMessage } from '../types/chat'

export function MessageBubble({ message }: { message: ChatMessage }) {
  return (
    <div className={`message-row ${message.role}`}>
      <div className="bubble">{message.content}</div>
    </div>
  )
}