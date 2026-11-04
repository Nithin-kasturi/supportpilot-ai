import { useEffect, useState } from 'react'
import {
  getMe,
  getOrder,
  getTracking,
  listOrders,
  listRefundRequests,
  listTickets,
} from '../services/supportApi'
import type { Me, OrderDetail, OrderSummary, RefundRequest, Ticket, Tracking } from '../types/support'
import { formatDate, formatDateTime, formatUsd, titleCase } from '../utils/format'
import { RefundCheck } from './RefundCheck'
import { TicketForm } from './TicketForm'

function StatusBadge({ status, label }: { status: string; label: string }) {
  return <span className={`status-badge status-${status}`}>{label}</span>
}

function OrderDetailView({ orderNumber, onChanged }: { orderNumber: string; onChanged: () => void }) {
  const [data, setData] = useState<{ detail: OrderDetail; tracking: Tracking } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showTicket, setShowTicket] = useState(false)

  useEffect(() => {
    let cancelled = false
    Promise.all([getOrder(orderNumber), getTracking(orderNumber)])
      .then(([detail, tracking]) => {
        if (!cancelled) setData({ detail, tracking })
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load the order.')
      })
    return () => {
      cancelled = true
    }
  }, [orderNumber])

  if (error) return <div className="error-banner">{error}</div>
  if (!data) return <p className="muted">Loading order…</p>
  const { detail, tracking } = data

  return (
    <div className="order-detail">
      <h2>
        {detail.order_number} <StatusBadge status={detail.status} label={detail.status_label} />
      </h2>
      <p className="muted">
        {detail.description} · {titleCase(detail.service_level)} · {detail.origin_city} to{' '}
        {detail.destination_city}
      </p>
      <dl className="facts">
        <div><dt>Shipping fee</dt><dd>{formatUsd(detail.shipping_fee_cents)}</dd></div>
        <div><dt>Declared value</dt><dd>{formatUsd(detail.declared_value_cents)}</dd></div>
        <div><dt>Order value</dt><dd>{formatUsd(detail.order_value_cents)}</dd></div>
        <div><dt>Estimated delivery</dt><dd>{formatDate(detail.estimated_delivery_date)}</dd></div>
        {detail.delivered_at && <div><dt>Delivered</dt><dd>{formatDateTime(detail.delivered_at)}</dd></div>}
        {detail.cancelled_at && <div><dt>Cancelled</dt><dd>{formatDateTime(detail.cancelled_at)}</dd></div>}
        {detail.delay_reason && <div><dt>Delay reason</dt><dd>{titleCase(detail.delay_reason)}</dd></div>}
      </dl>

      <h3>Tracking</h3>
      <ol className="timeline">
        {tracking.events.map((event) => (
          <li key={`${event.at}-${event.label}`}>
            <span className="timeline-time">{formatDateTime(event.at)}</span> {event.label}
          </li>
        ))}
      </ol>

      <h3>Refund</h3>
      <RefundCheck
        orderNumber={detail.order_number}
        onChanged={onChanged}
        onSuggestTicket={() => setShowTicket(true)}
      />

      <h3>Support</h3>
      {showTicket ? (
        <TicketForm orderNumber={detail.order_number} onChanged={onChanged} />
      ) : (
        <button className="secondary-button" onClick={() => setShowTicket(true)}>
          Create a support ticket
        </button>
      )}
    </div>
  )
}

function RecordsLists() {
  const [refunds, setRefunds] = useState<RefundRequest[] | null>(null)
  const [tickets, setTickets] = useState<Ticket[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([listRefundRequests(), listTickets()])
      .then(([r, t]) => {
        if (!cancelled) {
          setRefunds(r)
          setTickets(t)
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load records.')
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (error) return <div className="error-banner">{error}</div>
  if (!refunds || !tickets) return <p className="muted">Loading…</p>

  return (
    <div className="records">
      <h3>Refund requests ({refunds.length})</h3>
      <ul>
        {refunds.map((r) => (
          <li key={r.reference}>
            <strong>{r.reference}</strong> · {r.order_number} · {titleCase(r.reason)} ·{' '}
            {formatUsd(r.amount_cents)} · {titleCase(r.status)}
          </li>
        ))}
      </ul>
      <h3>Support tickets ({tickets.length})</h3>
      <ul>
        {tickets.map((t) => (
          <li key={t.reference}>
            <strong>{t.reference}</strong> · {t.order_number ?? 'general'} · {titleCase(t.category)} ·{' '}
            {titleCase(t.status)}
            <br />
            <span className="muted">{t.subject}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function OrdersPanel() {
  const [me, setMe] = useState<Me | null>(null)
  const [orders, setOrders] = useState<OrderSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [recordsVersion, setRecordsVersion] = useState(0)

  useEffect(() => {
    let cancelled = false
    Promise.all([getMe(), listOrders()])
      .then(([customer, list]) => {
        if (!cancelled) {
          setMe(customer)
          setOrders(list)
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load orders.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="orders-panel">
      <div className="demo-banner">
        {me ? `Demo customer: ${me.name} (${me.email}). ${me.notice}` : 'Loading customer…'}
      </div>
      {error && <div className="error-banner">{error}</div>}
      <div className="orders-body">
        <aside className="orders-list" aria-label="Orders">
          {loading && <p className="muted">Loading orders…</p>}
          {orders.map((order) => (
            <button
              key={order.order_number}
              className={`order-item${order.order_number === selected ? ' selected' : ''}`}
              onClick={() => setSelected(order.order_number)}
            >
              <span className="order-item-top">
                <strong>{order.order_number}</strong>
                <StatusBadge status={order.status} label={order.status_label} />
              </span>
              <span className="muted">
                {order.description} · {formatUsd(order.order_value_cents)}
              </span>
            </button>
          ))}
        </aside>
        <section className="orders-main">
          {selected ? (
            <OrderDetailView
              key={selected}
              orderNumber={selected}
              onChanged={() => setRecordsVersion((v) => v + 1)}
            />
          ) : (
            <p className="muted">Select an order to see its details, tracking and refund options.</p>
          )}
          <h2>My refund requests and tickets</h2>
          <RecordsLists key={recordsVersion} />
          <details className="general-ticket">
            <summary>Need help with something else? Create a general ticket</summary>
            <TicketForm
              orderNumber={null}
              onChanged={() => setRecordsVersion((v) => v + 1)}
            />
          </details>
        </section>
      </div>
    </div>
  )
}