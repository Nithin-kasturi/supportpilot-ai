import type { ChatMessage } from '../types/chat'

function documentLabel(category: string): string {
  const name = category
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
  return `${name} Policy`
}

interface Props {
  message: ChatMessage
  busy?: boolean
  onDecision?: (messageId: string, decision: 'confirm' | 'cancel') => void
}

export function MessageBubble({ message, busy = false, onDecision }: Props) {
  const sources = message.sources ?? []
  const actions = message.actions ?? []
  const confirmation = message.confirmation
  const state = message.confirmationState ?? 'pending'

  return (
    <div className={`message-row ${message.role}`}>
      <div className="bubble-wrapper">
        {actions.length > 0 && (
          <div className="agent-actions">
            {actions.map((action, index) => (
              <span key={`${action.tool}-${index}`} className={`action-chip ${action.ok ? 'ok' : 'failed'}`}>
                {action.ok ? '✓' : '✕'} {action.label}
              </span>
            ))}
          </div>
        )}
        <div className="bubble">{message.content}</div>
        {confirmation && (
          <div className="confirm-card">
            <strong>{confirmation.title}</strong>
            <ul>
              {confirmation.details.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            {state === 'done' ? (
              <span className="muted">This confirmation has been resolved.</span>
            ) : (
              <div className="button-row">
                <button
                  className="primary-button"
                  disabled={busy || state === 'working'}
                  onClick={() => onDecision?.(message.id, 'confirm')}
                >
                  {state === 'working' ? 'Working…' : 'Confirm'}
                </button>
                <button
                  className="secondary-button"
                  disabled={busy || state === 'working'}
                  onClick={() => onDecision?.(message.id, 'cancel')}
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        )}
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