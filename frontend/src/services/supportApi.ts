import type {
  CreateRefundOutput,
  CreateTicketOutput,
  Eligibility,
  Me,
  OrderDetail,
  OrderSummary,
  RefundReason,
  RefundRequest,
  Ticket,
  TicketCategory,
  ToolResult,
  Tracking,
} from '../types/support'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

async function send(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    })
  } catch {
    throw new Error('Cannot reach the SupportPilot server. Make sure the backend is running.')
  }
}

async function errorMessage(response: Response): Promise<string> {
  if (response.status === 422) {
    return 'Some of the details entered are not valid. Please check them and try again.'
  }
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') return body.detail
  } catch {
    // body was not JSON
  }
  return `Request failed with status ${response.status}.`
}

async function getJson<T>(path: string): Promise<T> {
  const response = await send(path)
  if (!response.ok) throw new Error(await errorMessage(response))
  return (await response.json()) as T
}

/** Tool endpoints answer 404/409 with a structured ToolResult body, so those are returned, not thrown. */
async function postTool<T>(path: string, body: unknown): Promise<ToolResult<T>> {
  const response = await send(path, { method: 'POST', body: JSON.stringify(body) })
  if (response.status === 422 || response.status >= 500) throw new Error(await errorMessage(response))
  let data: unknown
  try {
    data = await response.json()
  } catch {
    throw new Error('Received an unexpected response from the server.')
  }
  if (typeof data !== 'object' || data === null || !('ok' in data)) {
    throw new Error('Received an unexpected response from the server.')
  }
  return data as ToolResult<T>
}

export const getMe = () => getJson<Me>('/api/me')
export const listOrders = () => getJson<OrderSummary[]>('/api/orders')
export const getOrder = (orderNumber: string) =>
  getJson<OrderDetail>(`/api/orders/${encodeURIComponent(orderNumber)}`)
export const getTracking = (orderNumber: string) =>
  getJson<Tracking>(`/api/orders/${encodeURIComponent(orderNumber)}/tracking`)
export const listRefundRequests = () => getJson<RefundRequest[]>('/api/refund-requests')
export const listTickets = () => getJson<Ticket[]>('/api/tickets')

export async function checkEligibility(
  orderNumber: string,
  reason: RefundReason,
  photos: number,
): Promise<Eligibility> {
  const response = await send(`/api/orders/${encodeURIComponent(orderNumber)}/refund-eligibility`, {
    method: 'POST',
    body: JSON.stringify({ reason, evidence_photo_count: photos }),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return (await response.json()) as Eligibility
}

export interface CreateRefundParams {
  order_number: string
  reason: RefundReason
  evidence_photo_count: number
  customer_note: string | null
  confirmed: boolean
}

export const createRefundRequest = (params: CreateRefundParams) =>
  postTool<CreateRefundOutput>('/api/refund-requests', params)

export interface CreateTicketParams {
  order_number: string | null
  category: TicketCategory
  subject: string
  description: string
  confirmed: boolean
}

export const createTicket = (params: CreateTicketParams) =>
  postTool<CreateTicketOutput>('/api/tickets', params)