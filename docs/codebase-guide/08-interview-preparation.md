# 8. Interview preparation

Answers are based on what the code does. Where something is unmeasured or unverified, say so; that honesty reads well in interviews.

## 8.1 Pitches
**2 minutes.** "SupportPilot AI is a customer-support agent for a fictional parcel company. A React front end talks to a FastAPI backend. A LangGraph agent classifies each message with a local Ollama model, then either retrieves policy chunks from ChromaDB, calls customer-scoped tools backed by SQLite, or prepares a refund request or ticket. The key design rule: the LLM handles language only. Eligibility is deterministic code, tool arguments are built by code, identity comes from a JWT, and anything that creates a record needs a server-side single-use confirmation. I also added RBAC, audit logging, an MCP server exposing the same tools, an evaluation harness and an optional Redis cache."

**5-minute walkthrough.** (1) Login: Argon2 password, JWT in an HttpOnly cookie, role read from the DB each request. (2) A chat message reaches `agent_chat` through rate limiting and a permission dependency. (3) `classify_node` asks Ollama for schema-constrained JSON; slot filling and entity extraction are deterministic. (4) Policy questions embed the masked query (MiniLM, cached), query ChromaDB, filter by similarity 0.40, screen chunks, and `respond_node` phrases an answer from `<policy_context>`. (5) Order and eligibility questions call the tool layer, which checks permission, scopes SQL by `customer_id`, audits, and returns a structured result that the LLM only explains. (6) Refund and ticket requests produce a confirmation card; `/api/agent/confirm` claims a pending action atomically and re-runs the tool. (7) Observability, evaluation and caching sit around this.

**Architecture explanation.** Layers: routes (HTTP) → dependencies (identity) → tool layer (permission, ownership, audit) → services (queries, rules) → SQLite. The agent and the MCP server both call the tool layer, so authorization is implemented once. RAG is offline ingestion plus online retrieval; Redis only caches pure functions of (query, model, index version).

**Real-world scenario.** "My Express parcel SP-1004 arrived late, can I get a refund?" → intent `refund_eligibility`, order from regex, reason from keyword → `check_eligibility`: Express, more than 2 business days late, cause not weather, within 30 days → eligible for the $25.00 shipping fee only, below $50 so auto-approvable. The user asks to submit it → confirmation card → Confirm → record created with status `approved` (a record only; no money moves).

## 8.2 Beginner
1. **What does the project do?** See the 2-minute pitch.
2. **What is RAG and why use it?** Retrieve relevant policy text and put it in the prompt so answers come from company documents instead of the model's memory; here `retrieve` → `<policy_context>`.
3. **What is an embedding?** A vector (384 numbers) where similar meanings are close; `embed_texts` with MiniLM.
4. **Why a vector database?** Fast nearest-neighbour search plus metadata; ChromaDB persists chunks and vectors.
5. **What is Ollama?** A local LLM server; we call `/api/chat` over HTTP.
6. **What does the backend validate?** Pydantic schemas; unknown fields are rejected on tool inputs.
7. **How is the user authenticated?** Login verifies an Argon2 hash and sets a JWT in an HttpOnly cookie.
8. **What is SQLite used for?** The source of truth for orders, refunds, tickets, users and audit.
*Follow-up:* "Why not put policies in the prompt directly?" Too long and unfilterable; retrieval keeps context small for a 3B model.

## 8.3 Intermediate
1. **Why chunk by section?** Each `##` section is a self-contained rule set, so a retrieved chunk answers a question alone; a heading prefix puts the topic into the embedding.
2. **How is similarity computed?** Chroma returns a squared-L2 distance for unit vectors; the code uses `1 - distance/2` as cosine similarity and keeps results at or above 0.40.
3. **Why a similarity threshold and not just top-k?** So irrelevant questions retrieve nothing instead of padding the prompt.
4. **How does the agent decide what to do?** A schema-constrained classification (temperature 0), then deterministic routing in `route_after_classify`.
5. **How do multi-turn flows work?** `next_slots` with an `awaiting` field; the next message is parsed for that slot first (`_fill_awaiting`).
6. **How are confirmations bound to an operation?** The parameters are stored server-side in `pending_actions`; the client sends only the id and a decision.
7. **How are duplicates prevented?** Service check plus partial unique indexes; the tool catches `IntegrityError`.
8. **What does RBAC look like?** One `Permission` table in `security/permissions.py`, enforced in dependencies and again inside tools.
*Follow-up:* "What if the classifier says `refund_request` for a question?" `_sanity_check_intent` downgrades it unless there is a creation verb and the word refund; and creation still needs a confirmation.

## 8.4 Advanced
1. **Why not use native tool calling with qwen2.5:3b?** Small models are unreliable at argument extraction; the design keeps the LLM to classification and phrasing and builds arguments in code, so a wrong output cannot hit the database.
2. **How do you stop the LLM from claiming success?** Creation paths are prepare-only for the model; replies for confirmations are fixed text; `guard_claims` appends a correction if an informational reply claims creation.
3. **How is single-use confirmation made race-safe?** `pending_action_service.claim` is an atomic `UPDATE ... WHERE status='pending'`; only the caller with `rowcount == 1` executes.
4. **How does ownership avoid information leaks?** The SQL filters by `customer_id`, so foreign rows are never loaded; the response is the same 404 as a missing record; the attempt is audited.
5. **How does Redis stay consistent with policy changes?** The policy index version (hash of chunks) is in every RAG key and changes at ingest; ingest also purges the `rag` namespace; TTL is only a backstop.
6. **What happens if Redis dies mid-request?** `_fail` counts the error, opens a 10 s breaker and returns a miss; the request continues with ChromaDB/Ollama.
7. **What does the evaluation harness measure and what can it not?** Deterministic proxies (hit/precision/recall against reference sections, required facts, numeric grounding, abstention phrases, tool selection/arguments, rule outcomes); it is not an LLM judge and the dataset is small. No results are recorded in the docs.
8. **How would you scale this?** Postgres, shared rate limiter and sessions, a shared vector store or service, background workers for LLM calls, streaming responses.
*Follow-up:* "Why is HS256 acceptable here and when would you change it?" Single service, one secret, short tokens; change to asymmetric keys with rotation when multiple services verify tokens.

## 8.5 Scenario-based
1. **A customer tries SP-3001 (another customer's order).** `_owned_order` finds nothing → `ORDER_NOT_FOUND`; the reply never mentions the order; `record.access` denied is audited.
2. **Ollama is down.** Chat returns 503 with a clear message; classification fallback does not apply (the error propagates); confirmations still work.
3. **A policy file contains "ignore previous instructions...".** `screen_chunks` quarantines the chunk and audits it; if a variant slips through, it is still delimited as data and cannot create anything.
4. **A user double-clicks Confirm.** The first claim wins and creates one record; the second gets `already_resolved`.
5. **Policy text changes.** Run `python -m app.ai.rag`: new index version, old RAG cache unreachable and purged.
*Follow-up:* "What if two admins demote each other?" `change_role` rejects self-changes and the last active admin.

## 8.6 Code-level
1. Walk through `classify_node` (entity precedence, `missing`).
2. Explain `check_eligibility` ordering and why exclusions come first.
3. Why does `ToolContext.__post_init__` raise?
4. What does `apiFetch` do on 401, and why `silent401` for the first `/api/me` call?
5. How does `ObservabilityMiddleware` record spans across threads? A mutable dict in a `ContextVar` is mutated from worker threads (setting the variable inside a thread would not propagate).
6. Why does `embed_query` skip caching for some queries? References and masked PII could tie a cached entry to a customer's case.

## 8.7 Architecture and trade-offs
| Decision | Gain | Cost |
|---|---|---|
| Classification-only LLM | Predictable, safe tool use | Less flexible than free tool calling |
| Section chunking | Precise matches | Depends on heading format |
| SQLite | Zero setup | Single writer, no migrations |
| In-process rate limiting/memory | Simple | Not shared across workers |
| Role read per request | Instant revocation | One DB read per request |
| Prepare-only MCP creation | Agents cannot self-confirm | MCP-only clients cannot complete a creation alone |
| Optional Redis | Faster repeats, safe to lose | Extra moving part; benefit unmeasured here |
*Follow-up:* "Would you cache LLM answers?" Only anonymous policy-only answers, off by default, because replies can be wrong and frozen; the benchmark exists to quantify the gain.

## 8.8 Limitations and improvements
Single tool per turn; heuristic safety layers; no holiday calendar; self-declared evidence; in-memory memory; no CI; evaluation results not recorded; SQLite. Improvements: hybrid retrieval or reranking, LLM-judged evaluation alongside deterministic checks, PostgreSQL, refresh tokens/MFA, shared limiter/session store, streaming UI.