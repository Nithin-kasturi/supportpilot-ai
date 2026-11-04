import { useState } from 'react'
import { checkEligibility, createRefundRequest } from '../services/supportApi'
import type {
  CreateRefundOutput,
  Eligibility,
  RefundReason,
  RefundRequest,
  RefundStatus,
} from '../types/support'
import { formatUsd } from '../utils/format'

const REASONS: { value: RefundReason; label: string }[] = [
  { value: 'damaged', label: 'Parcel arrived damaged' },
  { value: 'late_express', label: 'Express parcel delivered late' },
  { value: 'lost', label: 'Parcel lost' },
  { value: 'cancelled', label: 'Order cancelled' },
  { value: 'billing_error', label: 'Billing error' },
  { value: 'other', label: 'Other / change of mind' },
]

const STATUS_LABEL: Record<RefundStatus, string> = {
  approved: 'Approved automatically',
  pending_review: 'Pending support review',
  rejected: 'Rejected',
}

type Stage = 'form' | 'confirm' | 'created'

function verdict(result: Eligibility): { label: string; className: string } {
  if (result.eligible === true) return { label: 'Eligible', className: 'verdict-yes' }
  if (result.eligible === false) return { label: 'Not eligible', className: 'verdict-no' }
  return { label: 'Needs manual review', className: 'verdict-review' }
}

function EligibilityCard({ result }: { result: Eligibility }) {
  const v = verdict(result)
  return (
    <div className="result-card">
      <span className={`verdict ${v.className}`}>{v.label}</span>
      <p>{result.reason}</p>
      {result.refundable_amount_cents !== null && (
        <p>
          <strong>Refundable amount:</strong> {formatUsd(result.refundable_amount_cents)}
          {result.requires_support_approval && ' (needs support approval)'}
        </p>
      )}
      <p>
        <strong>Next step:</strong> {result.next_action}
      </p>
      <p className="muted">Policy: {result.applicable_policy}</p>
    </div>
  )
}

interface Props {
  orderNumber: string
  onChanged: () => void
  onSuggestTicket: () => void
}

export function RefundCheck({ orderNumber, onChanged, onSuggestTicket }: Props) {
  const [reason, setReason] = useState<RefundReason>('damaged')
  const [photos, setPhotos] = useState(0)
  const [note, setNote] = useState('')
  const [stage, setStage] = useState<Stage>('form')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [eligibility, setEligibility] = useState<Eligibility | null>(null)
  const [preview, setPreview] = useState<CreateRefundOutput | null>(null)
  const [created, setCreated] = useState<RefundRequest | null>(null)

  function resetResults() {
    setStage('form')
    setEligibility(null)
    setPreview(null)
    setCreated(null)
    setError(null)
  }

  async function handleCheck() {
    resetResults()
    setBusy(true)
    try {
      setEligibility(await checkEligibility(orderNumber, reason, photos))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not check eligibility.')
    } finally {
      setBusy(false)
    }
  }

  async function submit(confirmed: boolean) {
    setBusy(true)
    setError(null)
    try {
      const result = await createRefundRequest({
        order_number: orderNumber,
        reason,
        evidence_photo_count: photos,
        customer_note: note.trim() || null,
        confirmed,
      })
      if (!result.ok || !result.data) {
        setError(result.error?.message ?? 'The refund request could not be created.')
        setStage('form')
        return
      }
      if (result.data.outcome === 'confirmation_required') {
        setPreview(result.data)
        setStage('confirm')
      } else if (result.data.outcome === 'created' && result.data.refund_request) {
        setCreated(result.data.refund_request)
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
      <div className="refund-check">
        <div className="success-banner">
          Refund request <strong>{created.reference}</strong> created: {STATUS_LABEL[created.status]},{' '}
          {formatUsd(created.amount_cents)}. This demo only records the request; no money is moved.
        </div>
        <button className="secondary-button" onClick={resetResults}>
          Check another reason
        </button>
      </div>
    )
  }

  if (stage === 'confirm' && preview?.eligibility) {
    const amount = preview.eligibility.refundable_amount_cents ?? 0
    return (
      <div className="refund-check">
        <div className="result-card">
          <p>
            <strong>Please confirm.</strong> You are about to submit a refund request for{' '}
            <strong>{formatUsd(amount)}</strong> on order {orderNumber}.
          </p>
          <p>
            Resulting status:{' '}
            <strong>{preview.status_if_created ? STATUS_LABEL[preview.status_if_created] : 'Pending'}</strong>
          </p>
          <p className="muted">This records a request only. No refund is executed and no money is moved.</p>
        </div>
        {error && <div className="error-banner">{error}</div>}
        <div className="button-row">
          <button className="primary-button" disabled={busy} onClick={() => submit(true)}>
            {busy ? 'Submitting…' : 'Confirm and submit'}
          </button>
          <button className="secondary-button" disabled={busy} onClick={resetResults}>
            Back
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="refund-check">
      <div className="form-row">
        <label>
          Reason
          <select
            value={reason}
            onChange={(e) => {
              setReason(e.target.value as RefundReason)
              resetResults()
            }}
          >
            {REASONS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        {reason === 'damaged' && (
          <label>
            Photos provided
            <input
              type="number"
              min={0}
              max={20}
              value={photos}
              onChange={(e) => {
                setPhotos(Math.max(0, Math.min(20, Number(e.target.value) || 0)))
                resetResults()
              }}
            />
          </label>
        )}
        <button className="primary-button" disabled={busy} onClick={handleCheck}>
          {busy ? 'Checking…' : 'Check eligibility'}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {eligibility && <EligibilityCard result={eligibility} />}

      {eligibility?.eligible === true && (
        <>
          <textarea
            placeholder="Optional note for the support team"
            maxLength={500}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <button className="primary-button" disabled={busy} onClick={() => submit(false)}>
            Submit refund request
          </button>
        </>
      )}
      {eligibility && eligibility.eligible !== true && (
        <button className="secondary-button" onClick={onSuggestTicket}>
          Create a support ticket
        </button>
      )}
    </div>
  )
}