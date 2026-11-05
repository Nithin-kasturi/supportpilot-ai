# 4. Function-by-function

Format per entry: **What/why**, **In → Out**, **Steps**, **Branches/errors**, **Calls / called by**, **Example** (project data). Examples marked *observed* are values you pasted during development.

## 4.1 RAG ingestion

### `backend/app/ai/rag.py::clean_text`
**What/why:** normalises policy text so chunking is stable. **In → Out:** `str → str`. **Steps:** unify line endings, replace non-breaking spaces, strip trailing spaces, collapse 3+ blank lines to 2. **Called by:** `chunk_document`. **Example:** `"a\r\n\r\n\r\nb  "` → `"a\n\nb"`.

### `backend/app/ai/rag.py::parse_sections`
**What/why:** splits Markdown into (title, [(heading, body)]) so each `##` section becomes a self-contained unit. **Steps:** iterate lines; `# ` first line = title; `## ` starts a section; other lines append to the current section; text before the first `##` is ignored. **Limitation:** relies on this heading format. **Example:** `damaged_parcel_policy.md` → title "SwiftParcel Damaged Parcel Policy", sections "Reporting deadline", "Required evidence", ...

### `backend/app/ai/rag.py::split_body`
**What/why:** splits an oversized section (more than `chunk_max_chars`=800) at line boundaries with overlap (`chunk_overlap_chars`=100, whole lines carried back). **Branches:** short sections return one part. In the delivered policies every section fits one chunk (observed: 31 chunks, max length below 800).

### `backend/app/ai/rag.py::chunk_document`
**In → Out:** `Path → list[Chunk]`. **Steps:** read UTF-8 (BOM-safe), `clean_text`, `parse_sections`, category = filename stem minus `_policy`, for each section `split_body`, build `Chunk(chunk_id=f"{stem}-{section:02d}-{part}", text=f"{title} - {heading}\n{part}", ...)`. The heading prefix puts the topic into the embedding. **Example (observed):** id `damaged_parcel_policy-00-0`.

### `backend/app/ai/rag.py::load_all_chunks`
Rejects non-`.md` files in the policies folder (this caught `refund_policy,md` during development), raises if no files, raises if a file yields no chunks (no silent skips). Returns all chunks in sorted file order, so ids are deterministic.

### `backend/app/ai/rag.py::ingest`
**What/why:** builds the vector store idempotently. **Steps:** `load_all_chunks`; optional `--rebuild` deletes the collection; `collection.upsert(ids, documents, embeddings=embed_texts(...), metadatas)`; delete ids no longer present (`stale`); write the index version (`compute_index_version`) to the file in the Chroma directory; `CACHE.clear_by_prefix("rag")`. **Why upsert + deterministic ids:** re-running cannot duplicate (observed: 31 chunks each run). **Returns:** counts, `index_version`, `rag_cache_purged`.

### `backend/app/ai/rag.py::get_index_version`
Reads the version file, memoised by file mtime. Missing file → `"none"`. Part of every RAG cache key, so a re-index makes old entries unreachable.

## 4.2 Embeddings and retrieval

### `backend/app/ai/embeddings.py::embed_texts`
`list[str] → ndarray (n, 384)` of unit vectors (`normalize_embeddings=True`, batch 32), wrapped in `span("embedding.encode")`. Never cached (used for ingestion and as the miss path). *Observed:* related pair similarity 0.6957 vs unrelated 0.4054.

### `backend/app/ai/embeddings.py::embed_query`
**Steps:** `normalize_query` → `is_cacheable_query` → Redis `embedding` get with material `model@revision|normalized` → on miss `embed_texts([text])[0]` → set (TTL `cache_ttl_embedding`). **Branch:** queries with `SP-1004`-style references or masked PII skip the cache both ways.

### `backend/app/ai/embeddings.py::is_cacheable_query`
Regex for order/ticket/refund references (`SP-1004`, `TK-SEED0001`) and the masking placeholders (`[email]`, `[phone]`, ...). False → never stored in Redis.

### `backend/app/services/retrieval_service.py::retrieve`
**In → Out:** `(question, top_k?, min_similarity?) → list[RetrievedChunk]`. **Steps:** strip; normalise; build key material (model signature, `get_index_version()`, k, threshold, query); try Redis `rag`; else `collection.count()` (0 → `KnowledgeBaseEmptyError`); `embed_query`; `collection.query` inside `span("rag.chroma_query")`; similarity `1 - distance/2`; drop below threshold (0.40); cache; count chunks (`rag.retrievals`, `rag.chunks_total`, trace note). **Why threshold not padding:** greetings return `[]`. *Observed:* "How long do I have to report a damaged parcel?" → Reporting deadline 0.6603, Required evidence 0.5495, Approval by order value 0.4947.

### `backend/app/services/retrieval_service.py::needs_policy_lookup`
`False` only for short (<=6 words) messages made entirely of greeting/thanks words; used by the legacy `/api/chat` (the agent uses classification instead).

## 4.3 LLM service

### `backend/app/services/llm_service.py::chat_completion`
**What/why:** synchronous Ollama call used by agent nodes (graph runs in a worker thread). **In → Out:** `(messages, temperature?, json_schema?) → str`. **Steps:** build payload (`stream False`, `keep_alive`, `options.temperature`, `num_predict`, optional `format` schema); `httpx.Client.post` inside `span("llm.inference")`; `_content`. **Errors:** `httpx.HTTPError` → `_service_error` → `LLMServiceError` (503 connect, 504 timeout, 502 other).

### `backend/app/services/llm_service.py::_content`
Maps status 404 → "model not installed" (503), non-200 → 502; parses JSON, adds Ollama's `prompt_eval_count`/`eval_count` to token counters, returns `message.content`; malformed body → `LLMServiceError(502)`.

### `backend/app/services/llm_service.py::generate_reply`
Async twin used only by the legacy `routes/chat.py::chat`: system prompt plus `build_user_prompt` (context tags neutralised).

## 4.4 Agent

### `backend/app/agent/graph.py::build_graph`
Registers six nodes, `START→classify`, two conditional edges (`route_after_classify`, `route_after_tool`) and terminal edges, then `compile()`. `AGENT_GRAPH` is built once at import.

### `backend/app/agent/graph.py::run_agent_with_state`
**What/why:** one chat turn; also returns the final state for evaluation. **Steps:** `MEMORY.get(customer.id, conversation_id)`; invoke the graph with `recursion_limit` inside `span("agent.graph")`; append masked user/assistant messages to history (trimmed to `agent_history_messages`); remember `verified_order`; store `next_slots`; build `AgentChatResponse` (sources from state chunks). The `ctx` object lives in graph state (no checkpointer, so no serialization).

### `backend/app/agent/nodes.py::classify_node`
**What/why:** decides intent and resolves entities, deterministically where possible. **Steps:** (1) `_fill_awaiting` if a slot was requested last turn, skipping the LLM; else `_classify_with_llm` + `_sanity_check_intent`; (2) order number = regex in message, else slot, else last verified order (not for tickets); (3) reason = keyword parse, else slot, else the LLM value **only** for eligibility questions (creation needs a keyword-backed reason); (4) photos by regex; (5) ticket description only if the user's own words (>=6 words and flagged as a description); (6) compute `missing`. **Example:** "Please submit a refund request for SP-1002" → intent `refund_request`, `missing="reason"`.

### `backend/app/agent/nodes.py::_classify_with_llm`
Calls the model with `CLASSIFICATION_SCHEMA` (plain inline enums so Ollama's grammar conversion works; "none" sentinel for nullable fields). Bad JSON or unknown intent → `parsing.py::heuristic_intent` fallback. `LLMServiceError` is not caught (503/504 reach the route).

### `backend/app/agent/nodes.py::_sanity_check_intent`
A question can never become a creation request: `refund_request` needs a creation verb **and** the word "refund", else downgrade to `refund_eligibility`; `ticket_request` needs ticket/complaint/escalate wording, else `policy_question`.

### `backend/app/agent/nodes.py::_fill_awaiting`
Handles `awaiting` of `order_number`, `reason`, `photos` (bare numbers and "none" allowed), `description` (>=10 chars). Returns updated slots, or `None` if the reply doesn't answer the question (the user changed topic; slots are discarded).

### `backend/app/agent/nodes.py::route_after_classify`
Pure routing on state: `missing` → `clarify`; `policy_question` → `retrieve_policy`; `order_status|list_orders|refund_eligibility` → `run_order_tool`; `refund_request|ticket_request` → `prepare_action`; otherwise `respond`.

### `backend/app/agent/nodes.py::run_order_tool_node`
Maps intent → one tool call with validated models (`GetOrderStatusInput`, `GetCustomerOrdersInput(limit=10)`, `CheckRefundEligibilityInput`); `ValidationError` → `INVALID_INPUT` result; `_record` appends `tool_results` and a UI `AgentAction`; sets `verified_order` only when the tool succeeded.

### `backend/app/agent/nodes.py::retrieve_policy_node`
`retrieve(mask_pii(message))`; `KnowledgeBaseEmptyError` → empty chunks and `policy_error`; `ai_safety.screen_chunks` quarantines instruction-like chunks (audited as `rag.chunk_quarantined`); appends the `search_policies` action. Other Chroma exceptions are not caught here (they become a 500).

### `backend/app/agent/nodes.py::prepare_action_node`
Calls `prepare_refund_request` or `prepare_support_ticket`. Success → fixed reply text plus a `ConfirmationPrompt` (nothing created). Failure → `describe_failure` text (not-found, not-eligible with next action, duplicate...). The reply is deterministic, not LLM-written, so it cannot overclaim.

### `backend/app/agent/nodes.py::respond_node`
Off-topic → fixed refusal. Otherwise: optional LLM cache lookup (`_llm_cache_material`, policy-only), `build_respond_messages`, `chat_completion`, `ai_safety.filter_reply`, `guard_claims`; caches only if the filters left the text unchanged.

### `backend/app/agent/nodes.py::clarify_node`
Returns the fixed question for the missing slot and `next_slots = carry + awaiting`.

### `backend/app/agent/parsing.py::parse_photos`
Regex for "2 photos", "two photos", "no photos"; with `allow_bare` accepts "3" or "none". Clamped to 20. Photo count is self-declared (there is no upload).

### `backend/app/agent/parsing.py::heuristic_intent`
Keyword fallback ordered: greeting, ticket verbs + ticket, refund verbs without question words, refund + order/"eligible", list-orders phrases, order + status words, policy words, else `off_topic`.

### `backend/app/agent/prompts.py::build_respond_messages`
Message list: system prompt, last 4 history messages, then one user message of `<tool_results>` (humanised JSON, cents → dollar strings, internal keys hidden), `<policy_context>` (numbered chunks or `NO_POLICY_FOUND`) and `Customer message:` (PII-masked). Tag strings are stripped from all untrusted text by `neutralize`.

### `backend/app/agent/prompts.py::guard_claims`
If the reply matches "I've/your refund has been submitted|created|approved..." appends a note that nothing was created. Defence in depth for informational replies.

### `backend/app/agent/memory.py::MemoryStore.get`
LRU dict keyed `(customer_id, conversation_id)` with a lock; creates on first use; evicts beyond 200 conversations. In-process only (lost on restart).

## 4.5 Confirmation workflow

### `backend/app/agent/actions.py::prepare_refund_request`
Runs `create_refund_request(confirmed=False)`; only on `confirmation_required` stores a `PendingAction` (`create_pending`, parameters minus `confirmed`) and returns `ConfirmationPrompt` with amount and resulting status; audits `refund.prepare`. Otherwise returns the failed `ToolResult`.

### `backend/app/agent/actions.py::resolve_pending`
**Steps:** `get_owned` (not found → audit + `not_found`); status not PENDING → `already_resolved`; expired → claim EXPIRED; `cancel` → claim CANCELLED; `confirm` → atomic `claim(CONFIRMED)` (loser gets `already_resolved`), audit, then `_execute`. **Why claim first:** single use even under double-click races.

### `backend/app/agent/actions.py::_execute`
Rebuilds `CreateRefundRequestInput`/`CreateSupportTicketInput` from the **stored** JSON with `confirmed=True` and calls the tool again, which re-checks permission, ownership, duplicates and eligibility. Success → fixed "Done..." text with the reference; failure → status FAILED and an honest "Nothing was created".

### `backend/app/services/pending_action_service.py::create_pending`
Cancels the customer's other PENDING actions (one active confirmation per customer), inserts a new row with `expires_at = now + pending_action_ttl_minutes`.

### `backend/app/services/pending_action_service.py::claim`
`UPDATE ... WHERE id=? AND status='pending'`, returns `rowcount == 1`; the database arbitrates races.

## 4.6 Tools and business rules

### `backend/app/tools/support_tools.py::ToolContext`
Frozen dataclass `(db, customer, principal, channel)`. `__post_init__` raises `PermissionError` if `principal.customer_id != customer.id`, so a staff principal can never build a customer context.

### `backend/app/tools/support_tools.py::_owned_order`
Wraps `order_service.get_order` (SQL includes `customer_id`); a miss is audited via `record_denied_lookup` and returns `None`. Foreign and missing orders are indistinguishable to the caller.

### `backend/app/tools/support_tools.py::create_refund_request`
Order of checks: permission → owned order → existing active request (`DUPLICATE_REQUEST`) → `check_eligibility` (`False` → `NOT_ELIGIBLE`, `None` → `MANUAL_REVIEW_REQUIRED`) → status via `status_for` → if `confirmed` false return the preview → insert + commit (`IntegrityError` → duplicate via the partial unique index) → audit. All five tools are wrapped at the bottom of the module by `instrument_tool` (timing and success counters).

### `backend/app/tools/support_tools.py::create_support_ticket`
Same pattern; optional order (general tickets are not de-duplicated); duplicate = open ticket for the same order and category.

### `backend/app/services/refund_eligibility_service.py::check_eligibility`
Pure function `(order, reason, photos, now?) → EligibilityResult`. Order: billing error → manual review; any `exception_reason` → excluded; then `_check_cancelled|_check_late_express|_check_lost|_check_damaged|_check_other`. Money in cents; auto-approval below 5000.

### `backend/app/services/refund_eligibility_service.py::_check_late_express`
Not Express → not eligible; cancelled/lost → not applicable; deadline = `add_business_days(estimated_delivery_date, 2)`; arrival = delivered date or today; on time → not delayed; weather → excluded; unknown cause → manual review; older than 30 days → expired; else refund = shipping fee only. **Example:** SP-1004 (Express, delivered 5 days after estimate, cause "other") → eligible, 2500.

### `backend/app/services/refund_eligibility_service.py::_check_damaged`
Not delivered → not eligible; `now - delivered_at > 48 h` → expired; fewer than 2 photos → manual review; else eligible for fee + min(declared, 50000); approval if amount >= 5000. **Example:** SP-1002 (delivered ~20 h before seeding, $135.00) → eligible, approval required, 13500.

### `backend/app/services/refund_eligibility_service.py::add_business_days`
Adds Monday-Friday days (no holiday calendar). **Example:** Friday 2026-11-06 + 2 → 2026-11-10 (you verified this output).

### `backend/app/services/order_service.py::get_order`
`WHERE customer_id = ? AND order_number = upper(?)`; raises `OrderNotFoundError`. Ownership is in the query, so another customer's row is never loaded.

### `backend/app/services/order_service.py::build_tracking`
Derives a timeline from `created_at`, `first_scanned_at`, `delivered_at`, `cancelled_at` and the last tracking update (no events table).

### `backend/app/database/seed.py::seed`
Optional drop of all tables, `init_db`, deterministic data (22 scenario + 40 filler orders, fixed RNG seed 42), idempotent by natural keys (email, order number, reference). Scenario dates are relative to seeding.

### `backend/app/database/session.py::init_db`
Imports `app.models` (registers tables) and runs `create_all`; creates only missing tables, never alters.

## 4.7 Security

### `backend/app/security/deps.py::get_principal`
Cookie first, then Bearer. No token → 401. Cookie → `enforce_csrf`. `principal_from_token` (audience `api`); failure → audit `auth.token_rejected` (reason code only) and 401. Success → `set_user` for tracing.

### `backend/app/security/deps.py::enforce_csrf`
Unsafe methods only: a present `Origin` must be in `CORS_ORIGINS`, and `X-Requested-With: SupportPilot` is required. Defence in depth with SameSite=Lax.

### `backend/app/security/deps.py::require_permission`
Dependency factory; 403 plus an `authz.denied` audit row when the role lacks the permission.

### `backend/app/security/deps.py::customer_context`
Permission check, loads `Customer` by `principal.customer_id` (403 if none), returns `ToolContext(channel="api")`. Customer identity can only come from here.

### `backend/app/security/authn.py::principal_from_token`
Decode (signature, pinned algorithm, issuer, audience, expiry, required claims) → revocation lookup → load user → active check → `Principal` with the **database** role. Used by the API (audience `api`) and MCP (audience `mcp`).

### `backend/app/security/tokens.py::decode_token`
`jwt.decode(..., algorithms=[HS256], audience, issuer, options={"require": [...]})`; expiry → `TokenExpired`; anything else → `TokenError`. Rejects `alg=none` and algorithm confusion.

### `backend/app/api/routes/auth.py::login`
`enforce_csrf` → two rate-limit hits (per IP and per account hash) → user lookup → `verify_password` or `verify_dummy` (constant-ish time) → generic 401 on any failure → optional rehash → `create_token` → HttpOnly cookie → audit. The body never contains the token.

### `backend/app/security/ai_safety.py::filter_reply`
Replaces the reply with a refusal if the canary or a long verbatim system-prompt line appears; otherwise `redact_secrets` (JWT-like and bearer strings).

### `backend/app/security/ai_safety.py::screen_chunks`
Pattern screen for instruction-like retrieved text ("ignore previous instructions", role tags, "approve refunds"...). Heuristic only; the structural defences are the real protection.

### `backend/app/security/pii.py::mask_pii`
Regex masking: JWT/bearer/password-like values, SSN, card-like and phone-like numbers, emails. Order numbers (`SP-1004`) survive. Applied to prompts, retrieval queries, stored history and logs.

### `backend/app/security/rate_limit.py::SlidingWindowLimiter.hit`
Per-key deque of timestamps under a lock; returns `(allowed, retry_after)`. In-memory, per process.

### `backend/app/security/audit.py::record`
Writes an `AuditLog` in its **own** session/transaction so it survives a failed operation; failures are logged, not raised.

## 4.8 Cache and observability

### `backend/app/cache/service.py::CacheService.get`
Skips if disabled or the breaker is open; GET inside `span("redis.get")`; `RedisError/OSError` → `_fail` (counter, 10 s breaker) and a miss; JSON decode; counts `cache.<ns>.hit|miss`.

### `backend/app/cache/service.py::CacheService.set`
Refuses payloads that look like secrets (JWT/bearer/password patterns); `SET ... EX ttl`.

### `backend/app/cache/service.py::CacheService.clear_by_prefix`
`SCAN` with the app prefix (batches of 200) and `UNLINK`; never `KEYS` or `FLUSHDB`.

### `backend/app/observability/metrics.py::span`
Context manager timing a block into the registry and the current request's trace (`spans[name] = [total_ms, count]`).

### `backend/app/observability/metrics.py::Registry.snapshot`
Counters plus latency summaries; P50/P95 only with >=20 samples and P99 with >=100; tool success rates; cache hit rates; token totals.

### `backend/app/observability/middleware.py::ObservabilityMiddleware`
Pure ASGI: generates the trace id, starts the trace context, adds `X-Trace-Id`, and in `finally` records latency/counters and writes one JSON line (method, path, status, ms, user id, spans). No query strings or bodies are logged.

### `backend/app/security/middleware.py::BodySizeLimitMiddleware`
Rejects by `Content-Length` and while streaming (`_TooLarge` caught, 413).

## 4.9 MCP

### `backend/app/mcp_server.py::_run`
Per call: read `SUPPORTPILOT_MCP_TOKEN`, `principal_from_token(aud=mcp)`, rate limit, require a customer principal with `AGENT_USE`, build `ToolContext(channel="mcp")`, run the tool. Failures return `{ok:false, error:{code}}` (`UNAUTHENTICATED`, `FORBIDDEN`, `RATE_LIMITED`).

### `backend/app/mcp_server.py::_prepared`
Turns a `ConfirmationPrompt` into a result with `created: false`, `confirmation_id` and instructions to confirm via the API.

## 4.10 Frontend

### `frontend/src/services/http.ts::apiFetch`
Adds `X-Requested-With`, JSON content type when a body exists, `credentials: "include"`, an abort timeout; network failure → friendly error; 401 (unless `silent401`) → calls the registered handler and throws `UnauthorizedError`.

### `frontend/src/components/AuthProvider.tsx::AuthProvider`
On mount `fetchProfile()` decides `authenticated|anonymous`; registers the unauthorized handler (sets `sessionExpired`); exposes `signIn`/`signOut`.

### `frontend/src/App.tsx::Shell`
Loading → login page if no user → role-based navigation: customers get Chat and My Orders (both kept mounted, hidden with `hidden`), staff the support console, admins the admin panel.

### `frontend/src/pages/ChatPage.tsx::handleSubmit`
Appends the user bubble, calls `sendAgentMessage`, stores `sources`, `actions` and `confirmation`; when a new confirmation arrives, older cards are marked done (the server cancels them too).

### `frontend/src/pages/ChatPage.tsx::handleDecision`
Sets the card to `working`, calls `resolveConfirmation(id, decision)`, appends the server's fixed reply, marks the card done; on error restores `pending`.

### `frontend/src/services/chatApi.ts::sendAgentMessage`
POSTs `{message, conversation_id}`; validates the response (`isSource`, `isAction`, `isConfirmation` filters) so a malformed payload degrades instead of crashing.

### `frontend/src/components/RefundCheck.tsx::RefundCheck`
Stages `form → confirm → created`: `checkEligibility` (read-only) → `createRefundRequest(confirmed=false)` returns the server-computed preview → user clicks "Confirm and submit" → `createRefundRequest(confirmed=true)`. The UI never computes eligibility.

### `frontend/src/components/MessageBubble.tsx::MessageBubble`
Renders action chips, the text, the confirmation card (Confirm/Cancel while pending) and "Policy sections consulted".