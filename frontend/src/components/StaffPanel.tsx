import { useEffect, useState } from 'react'
import { listStaffRefunds, listStaffTickets, reviewRefund, updateTicketStatus } from '../services/adminApi'
import type { StaffRefund, StaffTicket } from '../types/auth'
import { formatUsd, titleCase } from '../utils/format'

const STATUSES = ['open', 'in_progress', 'resolved', 'closed']

function Tickets({ onChanged }: { onChanged: () => void }) {
  const [rows, setRows] = useState<StaffTicket[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listStaffTickets()
      .then((data) => {
        if (!cancelled) setRows(data)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load tickets.')
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function change(reference: string, status: string) {
    setError(null)
    try {
      await updateTicketStatus(reference, status)
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update the ticket.')
    }
  }

  if (error) return <div className="error-banner">{error}</div>
  if (!rows) return <p className="muted">Loading…</p>
  return (
    <ul className="records-list">
      {rows.map((t) => (
        <li key={t.reference}>
          <strong>{t.reference}</strong> · {titleCase(t.category)} · {t.order_number ?? 'general'} ·{' '}
          {t.customer_name} ({t.customer_email})
          <br />
          <span className="muted">{t.subject}</span>
          <br />
          <label>
            Status{' '}
            <select value={t.status} onChange={(e) => change(t.reference, e.target.value)}>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {titleCase(s)}
                </option>
              ))}
            </select>
          </label>
        </li>
      ))}
    </ul>
  )
}

function Refunds({ onChanged }: { onChanged: () => void }) {
  const [rows, setRows] = useState<StaffRefund[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listStaffRefunds()
      .then((data) => {
        if (!cancelled) setRows(data)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load refund requests.')
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function review(reference: string, decision: 'approve' | 'reject') {
    setError(null)
    try {
      await reviewRefund(reference, decision)
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not record the decision.')
    }
  }

  if (error) return <div className="error-banner">{error}</div>
  if (!rows) return <p className="muted">Loading…</p>
  return (
    <ul className="records-list">
      {rows.map((r) => (
        <li key={r.reference}>
          <strong>{r.reference}</strong> · {r.order_number} · {titleCase(r.reason)} · {formatUsd(r.amount_cents)} ·{' '}
          {titleCase(r.status)}
          <br />
          <span className="muted">
            {r.customer_name} ({r.customer_email}) · photos: {r.evidence_photo_count}
          </span>
          {r.status === 'pending_review' && (
            <div className="button-row">
              <button className="primary-button" onClick={() => review(r.reference, 'approve')}>
                Approve
              </button>
              <button className="secondary-button" onClick={() => review(r.reference, 'reject')}>
                Reject
              </button>
            </div>
          )}
        </li>
      ))}
    </ul>
  )
}

export function StaffPanel() {
  const [version, setVersion] = useState(0)
  const bump = () => setVersion((v) => v + 1)
  return (
    <div className="ops-panel">
      <h2>Tickets</h2>
      <Tickets key={`t${version}`} onChanged={bump} />
      <h2>Refund requests</h2>
      <Refunds key={`r${version}`} onChanged={bump} />
    </div>
  )
}