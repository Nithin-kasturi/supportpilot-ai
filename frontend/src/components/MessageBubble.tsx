import type { ChatMessage } from '../types/chat'

function documentLabel(category: string): string {
  const name = category
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
  return `${name} Policy`
}

export function MessageBubble({ message }: { message: ChatMessage }) {
  const sources = message.sources ?? []

  return (
    <div className={`message-row ${message.role}`}>
      <div className="bubble-wrapper">
        <div className="bubble">{message.content}</div>
        {sources.length > 0 && (
          <div className="sources">
            <span className="sources-label">Policy sections consulted</span>
            <ul>
              {sources.map((source) => (
                <li
                  key={source.chunk_id}
                  title={`${source.document} · match score ${source.similarity.toFixed(2)}`}
                >
                  {documentLabel(source.category)} · {source.section}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}