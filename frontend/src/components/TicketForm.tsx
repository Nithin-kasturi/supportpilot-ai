import { useState } from 'react'
import { createTicket } from '../services/supportApi'
import type { CreateTicketOutput, Ticket, TicketCategory } from '../types/support'
import { titleCase } from '../utils/format'

const CATEGORIES: { value: TicketCategory; label: string }[] = [
  { value: 'delivery_issue', label: 'Delivery issue' },
  { value: 'damaged_parcel', label: 'Damaged parcel' },
  { value: 'refund', label: 'Refund' },
  { value: 'cancellation', label: 'Cancellation' },
  { value: 'complaint', label: 'Complaint' },
  { value: 'other', label: 'Other' },
]

type Stage = 'form' | 'confirm' | 'created'

interface Props {
  orderNumber: string | null
  defaultCategory?: TicketCategory
  onChanged: () => void
}

export function TicketForm({ orderNumber, defaultCategory = 'other', onChanged }: Props) {
  const [category, setCategory] = useState<TicketCategory>(defaultCategory)
  const [subject, setSubject] = useState('')
  const [description, setDescription] = useState('')
  const [stage, setStage] = useState<Stage>('form')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<CreateTicketOutput | null>(null)
  const [created, setCreated] = useState<Ticket | null>(null)

  const valid = subject.trim().length >= 3 && description.trim().length >= 10

  function reset() {
    setStage('form')
    setPreview(null)
    setCreated(null)
    setError(null)
    setSubject('')
    setDescription('')
  }

  async function submit(confirmed: boolean) {
    setBusy(true)
    setError(null)
    try {
      const result = await createTicket({
        order_number: orderNumber,
        category,
        subject: subject.trim(),
        description: description.trim(),
        confirmed,
      })
      if (!result.ok || !result.data) {
        setError(result.error?.message ?? 'The ticket could not be created.')
        setStage('form')
        return
      }
      if (result.data.outcome === 'confirmation_required') {
        setPreview(result.data)
        setStage('confirm')
      } else if (result.data.outcome === 'created' && result.data.ticket) {
        setCreated(result.data.ticket)
        setStage('created')
        onChanged()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  if (stage === 'created' && created) {
    return (
      <div className="ticket-form">
        <div className="success-banner">
          Ticket <strong>{created.reference}</strong> created (status: {titleCase(created.status)}). The
          support team will follow up.
        </div>
        <button className="secondary-button" onClick={reset}>
          Create another ticket
        </button>
      </div>
    )
  }

  if (stage === 'confirm' && preview?.preview) {
    const p = preview.preview
    return (
      <div className="ticket-form">
        <div className="result-card">
          <p>
            <strong>Please confirm.</strong> A support ticket will be created:
          </p>
          <p>
            {titleCase(p.category)}
            {p.order_number ? ` · order ${p.order_number}` : ' · general'}
          </p>
          <p>
            <strong>{p.subject}</strong>
          </p>
          <p>{p.description}</p>
        </div>
        {error && <div className="error-banner">{error}</div>}
        <div className="button-row">
          <button className="primary-button" disabled={busy} onClick={() => submit(true)}>
            {busy ? 'Creating…' : 'Confirm and create ticket'}
          </button>
          <button className="secondary-button" disabled={busy} onClick={() => setStage('form')}>
            Back
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="ticket-form">
      <label>
        Category
        <select value={category} onChange={(e) => setCategory(e.target.value as TicketCategory)}>
          {CATEGORIES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Subject
        <input
          type="text"
          maxLength={150}
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          placeholder="Short summary (at least 3 characters)"
        />
      </label>
      <label>
        Description
        <textarea
          maxLength={2000}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What happened? (at least 10 characters)"
        />
      </label>
      {error && <div className="error-banner">{error}</div>}
      <button className="primary-button" disabled={busy || !valid} onClick={() => submit(false)}>
        Review ticket
      </button>
    </div>
  )
}