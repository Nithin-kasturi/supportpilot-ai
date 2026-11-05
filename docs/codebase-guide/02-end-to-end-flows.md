# 2. End-to-end flows

Notation: `path::symbol`. Every step below was traced from the code; where an SDK's internal behaviour is involved it is marked **unverified**.

## Flow 1: Open the app and authenticate
```mermaid
sequenceDiagram
  autonumber
  participant AP as AuthProvider.tsx
  participant AA as authApi.ts
  participant H as http.ts apiFetch
  participant GP as deps.get_principal
  participant LG as routes/auth.login
  participant DB as SQLite
  AP->>AA: fetchProfile()
  AA->>H: apiFetch("/api/me", silent401)
  H->>GP: GET /api/me, no cookie
  GP-->>H: 401 Not authenticated
  H-->>AA: response (401 not treated as expiry)
  AA-->>AP: null, status anonymous, LoginPage shown
  AP->>AA: signIn(email, password) -> login()
  AA->>LG: POST /api/auth/login + X-Requested-With
  LG->>LG: enforce_csrf, LIMITER.hit (ip, account)
  LG->>DB: select User by email
  LG->>LG: verify_password or verify_dummy
  LG->>LG: create_token, set_cookie HttpOnly
  LG-->>AA: ProfileOut (no token in body)
  AA-->>AP: Profile, Shell renders by role
```
Details: `backend/app/api/routes/auth.py::login` returns the same 401 text for an unknown user, a wrong password and an inactive account; each writes an `auth.login` audit row. `frontend/src/components/AuthProvider.tsx::AuthProvider` registers `setUnauthorizedHandler` so any later 401 flips the app back to the login page.

## Flows 2-8: A policy question (message → RAG → Ollama → render)
```mermaid
sequenceDiagram
  autonumber
  participant CP as ChatPage.handleSubmit
  participant CA as chatApi.sendAgentMessage
  participant R as routes/agent.agent_chat
  participant G as graph.run_agent_with_state
  participant CN as nodes.classify_node
  participant RN as nodes.retrieve_policy_node
  participant RT as retrieval_service.retrieve
  participant EM as embeddings.embed_query
  participant CH as ChromaDB
  participant RS as nodes.respond_node
  participant LL as llm_service.chat_completion
  participant OL as Ollama
  CP->>CA: sendAgentMessage(text, conversationId)
  CA->>R: POST /api/agent/chat (cookie, CSRF header)
  R->>R: rate_limit_user, customer_context(AGENT_USE), sanitize_user_text
  R->>G: run_agent(ctx, conversation_id, message)
  G->>CN: AGENT_GRAPH.invoke(state)
  CN->>LL: classification (temperature 0, JSON schema)
  LL->>OL: POST /api/chat
  OL-->>CN: {"intent":"policy_question",...}
  CN-->>G: route_after_classify -> retrieve_policy
  G->>RN: retrieve_policy_node
  RN->>RT: retrieve(mask_pii(message))
  RT->>EM: embed_query (cache, else SentenceTransformer)
  RT->>CH: collection.query(vector, n_results=3)
  CH-->>RT: ids, documents, metadatas, distances
  RT-->>RN: chunks with similarity = 1 - distance/2 (above 0.40)
  RN->>RN: screen_chunks, audit quarantined
  G->>RS: respond_node
  RS->>LL: build_respond_messages -> chat_completion
  LL->>OL: POST /api/chat
  OL-->>RS: reply text
  RS->>RS: filter_reply, guard_claims
  G-->>R: AgentChatResponse (reply, sources, actions)
  R-->>CA: JSON
  CA-->>CP: AgentReply (validated)
  CP->>CP: MessageBubble renders chips, text, sources
```
Step notes:
1. `ChatPage.handleSubmit` appends the user bubble, then calls `sendAgentMessage`, which calls `post` → `apiFetch` with `timeoutMs 240000`.
2. Middleware order (outermost first): CORS, `ObservabilityMiddleware` (trace id), `SecurityHeadersMiddleware`, `BodySizeLimitMiddleware`, then the router.
3. `customer_context(Permission.AGENT_USE)` runs `get_principal` → `require_permission` → loads `Customer` → builds `ToolContext(channel="api")`; the route re-creates it with `channel="agent"`.
4. `classify_node` → `_classify_with_llm` → `chat_completion(..., json_schema=CLASSIFICATION_SCHEMA)`.
5. Embeddings: `embed_query` normalises (lowercase, collapse whitespace), checks Redis `embedding`, else `embed_texts` (`SentenceTransformer.encode`, normalised 384-d).
6. Observed during development (your pasted output): the question "How long do I have to report a damaged parcel?" ranked `damaged_parcel_policy.md / Reporting deadline` first at similarity 0.6603.
7. The reply is the model's text after `filter_reply` and `guard_claims`; `sources` are the retrieved sections, not proof the model used them.

## Flow 9: Order status
`classify_node` (intent `order_status`, order from `parse_order_number`) → `route_after_classify` → `run_order_tool_node` → `support_tools.get_order_status` → `_allowed(ORDERS_READ_OWN)` → `_owned_order` → `order_service.get_order` (SQL `WHERE customer_id = ? AND order_number = ?`) → `order_service.build_tracking` → `ToolResult` → `_record` → `respond_node` (the LLM phrases `tool_results`). A foreign order (SP-3001) returns `ORDER_NOT_FOUND`; `audit.record_denied_lookup` logs it; the user sees a generic "not found".

## Flow 10: Refund eligibility
Same path with intent `refund_eligibility` and `support_tools.check_refund_eligibility` → `refund_eligibility_service.check_eligibility` → `EligibilityResult` (eligible true/false/None, reason, amount, rule code, next action). The LLM only explains it. Example: SP-1004 + `late_express` → eligible, 2500 cents, `LATE_EXPRESS_ELIGIBLE` (verified by you in Milestone 3 and Step 5).

## Flow 11: Customer requests and confirms a refund
```mermaid
sequenceDiagram
  autonumber
  participant CP as ChatPage
  participant PA as nodes.prepare_action_node
  participant AC as actions.prepare_refund_request
  participant TL as support_tools.create_refund_request
  participant PS as pending_action_service
  participant CF as routes/agent.agent_confirm
  participant RP as actions.resolve_pending
  participant DB as SQLite
  CP->>PA: "submit a refund request for SP-1004, it was late"
  PA->>AC: prepare_refund_request(ctx, order, reason, photos)
  AC->>TL: create_refund_request(confirmed=false)
  TL-->>AC: outcome confirmation_required + eligibility
  AC->>PS: create_pending (cancels older pending)
  PS->>DB: INSERT pending_actions
  AC-->>CP: ConfirmationPrompt (card, nothing created)
  CP->>CF: POST /api/agent/confirm {id, decision}
  CF->>RP: resolve_pending
  RP->>PS: get_owned, then claim(CONFIRMED) atomic UPDATE
  RP->>TL: create_refund_request(confirmed=true)
  TL->>TL: re-check permission, ownership, duplicates, eligibility
  TL->>DB: INSERT refund_requests, commit
  TL-->>CP: ConfirmResponse created + reference
```
The confirm route uses no LLM. A second confirm returns `already_resolved`; an expired one returns `expired` (`utcnow() > action.expires_at`); another customer's id returns `not_found` because `get_owned` filters by `customer_id`.

## Flow 12: Support ticket
Single message ("open a ticket for SP-1012: tracking has not updated...") goes `classify_node` → `prepare_action_node` → `prepare_support_ticket` → `create_support_ticket(confirmed=False)` → pending action → card → confirm → `create_support_ticket(confirmed=True)` → `ticket_service.create_ticket`. If the description is missing, `classify_node` sets `missing="description"`, `clarify_node` stores `next_slots` (`awaiting`), and the next turn `_fill_awaiting` takes the whole message as the description (min 10 characters). A duplicate open ticket (same order and category) returns `DUPLICATE_TICKET`, backed by the partial unique index `uq_open_ticket_per_order_category`.

## Flow 13: MCP tool invocation
```mermaid
sequenceDiagram
  participant C as MCP client
  participant S as mcp_server (FastMCP)
  participant RN as _run
  participant AU as authn.principal_from_token
  participant T as support_tools
  C->>S: tools/call get_order_status {order_number}
  S->>RN: validate input, _run(fn)
  RN->>AU: token from SUPPORTPILOT_MCP_TOKEN, audience mcp
  AU-->>RN: Principal or reason
  RN->>RN: LIMITER, customer + AGENT_USE check
  RN->>T: ToolContext(channel="mcp")
  T-->>C: {ok, data, error}
```
`create_refund_request` and `create_support_ticket` call `actions.prepare_*` and return a `confirmation_id` (`mcp_server.py::_prepared`); they never write. Staff or admin tokens get `FORBIDDEN`. The MCP SDK's own transport and error wrapping are **unverified** here.

## Flow 14: Redis cache hit and miss
```mermaid
sequenceDiagram
  participant RT as retrieve
  participant CS as CACHE
  participant RD as Redis
  participant CH as ChromaDB
  RT->>RT: normalize_query, is_cacheable_query, key material with index version
  RT->>CS: get("rag", material)
  CS->>RD: GET supportpilot:v1:rag:hash
  alt hit
    RD-->>RT: JSON chunks, rebuilt as RetrievedChunk
  else miss
    RT->>CH: embed_query then collection.query
    RT->>CS: set("rag", material, chunks, ttl)
  end
  Note over CS: Redis error: _fail sets 10 s breaker, returns miss
```
Queries containing an order/ticket reference or masked PII are never cached (`embeddings.py::is_cacheable_query`). Ingest changes the index version and calls `CACHE.clear_by_prefix("rag")`.

## Flow 15: Errors and fallbacks
| Situation | Path | User sees |
|---|---|---|
| Invalid body | FastAPI/Pydantic 422 | `errorMessage` text in `frontend/src/services/http.ts` |
| No/expired session | `get_principal` 401 | `UnauthorizedError`, login page with "session has ended" |
| Ollama down | `llm_service.py::_service_error` → `LLMServiceError(503)` → `HTTPException` in `agent_chat` | error banner |
| Ollama timeout | `httpx.TimeoutException` → 504 | error banner |
| Ollama bad JSON for classification | `_classify_with_llm` falls back to `parsing.py::heuristic_intent` | normal answer |
| Empty vector store | `KnowledgeBaseEmptyError` caught in `retrieve_policy_node` | model told "no relevant policy found" |
| Redis down | `CACHE._fail` | normal answer, slower |
| Tool error | `ToolResult(ok=False)` | explained in plain language |
| Unhandled exception | `main.py::unhandled_error` | generic 500 JSON with a trace id in the log |