export type OrderStatus =
  | 'placed' | 'processing' | 'shipped' | 'in_transit' | 'out_for_delivery'
  | 'delivered' | 'delayed' | 'cancelled' | 'lost'
export type ServiceLevel = 'express' | 'standard' | 'economy'
export type RefundReason = 'cancelled' | 'late_express' | 'lost' | 'damaged' | 'billing_error' | 'other'
export type RefundStatus = 'approved' | 'pending_review' | 'rejected'
export type TicketCategory =
  | 'delivery_issue' | 'damaged_parcel' | 'refund' | 'cancellation' | 'complaint' | 'other'
export type TicketStatus = 'open' | 'in_progress' | 'resolved' | 'closed'

export interface Me {
  name: string
  email: string
  identity_mode: string
  notice: string
}

export interface OrderSummary {
  order_number: string
  status: OrderStatus
  status_label: string
  service_level: ServiceLevel
  description: string
  destination_city: string
  order_value_cents: number
  estimated_delivery_date: string
  created_at: string
}

export interface OrderDetail extends OrderSummary {
  origin_city: string
  shipping_fee_cents: number
  declared_value_cents: number
  delivered_at: string | null
  cancelled_at: string | null
  last_tracking_update_at: string | null
  delay_reason: 'weather' | 'other' | null
}

export interface TrackingEvent {
  at: string
  label: string
}

export interface Tracking {
  order_number: string
  status: OrderStatus
  status_label: string
  service_level: ServiceLevel
  estimated_delivery_date: string
  last_update_at: string | null
  events: TrackingEvent[]
}

export interface Eligibility {
  order_number: string
  refund_reason: RefundReason
  eligible: boolean | null
  reason: string
  applicable_policy: string
  requires_support_approval: boolean
  next_action: string
  refundable_amount_cents: number | null
  rule_code: string
}

export interface RefundRequest {
  reference: string
  order_number: string
  reason: RefundReason
  status: RefundStatus
  amount_cents: number
  requires_support_approval: boolean
  evidence_photo_count: number
  rule_code: string
  customer_note: string | null
  created_at: string
  updated_at: string
}

export interface Ticket {
  reference: string
  order_number: string | null
  category: TicketCategory
  status: TicketStatus
  subject: string
  description: string
  created_at: string
  updated_at: string
}

export interface ToolError {
  code: string
  message: string
}

export interface ToolResult<T> {
  ok: boolean
  data: T | null
  error: ToolError | null
}

export type Outcome = 'confirmation_required' | 'created' | 'not_created'

export interface CreateRefundOutput {
  outcome: Outcome
  eligibility: Eligibility | null
  status_if_created: RefundStatus | null
  refund_request: RefundRequest | null
}

export interface TicketPreview {
  order_number: string | null
  category: TicketCategory
  subject: string
  description: string
}

export interface CreateTicketOutput {
  outcome: Outcome
  preview: TicketPreview | null
  ticket: Ticket | null
}