# 6. Concepts and design decisions

Each concept lists: meaning, why here, where, internals, why chosen, alternatives, trade-offs, practices demonstrated by the code, and weaknesses. "Demonstrated" claims point at code.

## FastAPI and dependency injection
| | |
|---|---|
| Meaning | Python web framework; `Depends` builds per-request objects and runs them in order |
| Why/where | Identity and permissions as dependencies: `backend/app/security/deps.py::get_principal`, `require_permission`, `customer_context` |
| Internals | Dependencies are cached per request, so `get_principal` runs once even if three dependencies need it |
| Why chosen / alternatives | Type-driven validation and composition; Flask/Django need more glue |
| Pros/cons | Declarative security; but permission logic spread over decorators needs discipline (hence one `Permission` table) |
| Demonstrated | Routes contain no business logic; sync `def` routes run in a thread pool for blocking SQLAlchemy |
| Weakness | Mixed async (`routes/chat.py`) and sync (agent) styles |

## React component architecture
| | |
|---|---|
| Where | `frontend/src/App.tsx`, `components/*`, `services/*` |
| Internals | State in components; data loaders use `useEffect` + a `cancelled` flag; remount-by-`key` to reload lists |
| Why | Small app; no router or state library needed |
| Alternatives | React Router, TanStack Query, Redux |
| Trade-offs | Simple, but no caching/retry layer and role "routes" are conditional rendering |
| Demonstrated | A single API client (`apiFetch`), response validation in `chatApi.ts`, no token in JS |
| Weakness | No frontend tests; authorization shown by visibility only (the backend enforces it) |

## REST and HTTP methods
GET for reads, POST for actions, PATCH for partial updates (`/api/me`, ticket status, role). Preview-then-create uses POST with a `confirmed` flag. Status codes carry meaning: 401 unauthenticated, 403 forbidden, 404 for both missing and foreign records, 409 duplicates/state conflicts, 422 validation, 429 rate limit.

## Pydantic validation
| | |
|---|---|
| Where | `backend/app/schemas/*.py` |
| Internals | Types, regex and length constraints; `ConfigDict(extra="forbid")` rejects unknown fields |
| Why | Boundary validation and mass-assignment protection (`UpdateProfileIn` rejects `role`) |
| Weakness | Order-number pattern is duplicated in routes and schemas |

## SQLAlchemy and relational design
| | |
|---|---|
| Where | `backend/app/models/*.py`, `database/session.py` |
| Why | Typed ORM, relationships, constraints |
| Decisions | Integer cents; enums stored as text; naive UTC; partial unique indexes for duplicates; FK pragma enabled because SQLite ignores FKs by default |
| Alternatives | PostgreSQL, raw SQL, async SQLAlchemy |
| Weaknesses | `create_all` only (no migrations); SQLite single writer; audit and sessions share the DB |

## Embeddings and semantic search
`all-MiniLM-L6-v2` maps text to 384-d unit vectors, so cosine similarity is a dot product (`ai/embeddings.py::embed_texts`). Chosen for CPU speed on a 12 GB laptop. Alternatives: larger models, hosted embeddings. Weakness: similarity measures topical closeness, not answerability (e.g. "same day delivery" retrieves shipping chunks although no such policy exists).

## Vector databases and ChromaDB
Persistent local store (`ai/rag.py::get_client`); HNSW approximate nearest-neighbour; we pass our own embeddings (otherwise Chroma uses its default model). Distance converted with `1 - d/2` (valid for unit vectors with Chroma's default squared-L2; you validated plausible scores). Alternatives: FAISS, Qdrant, pgvector. Single-process only.

## Chunking and similarity search
Section-based chunks with a heading prefix and deterministic ids; threshold 0.40 chosen from a handful of observed queries (provisional). Weakness: no reranker or hybrid search; observed ordering quirk where "Escalation to Level 3" outranked Level 2.

## RAG and prompt construction
Retrieved text goes into `<policy_context>` as reference data in the user turn, rules stay in the system prompt (`agent/prompts.py::build_respond_messages`). Instruction to answer only from context and abstain otherwise. Weakness: a 3B model can still ignore instructions; sources shown are "retrieved", not "used".

## Ollama and local LLM inference
HTTP `/api/chat` through httpx (`services/llm_service.py`). Structured output via the `format` JSON schema for classification. `keep_alive` and `num_predict` bound latency. Why local: free, private. Trade-off: weaker instruction following and slow CPU inference. Native tool-calling was deliberately not used; the model only classifies and phrases, and code builds tool arguments.

## LangGraph
| | |
|---|---|
| Meaning | State machine of nodes and conditional edges over a shared state dict |
| Where | `backend/app/agent/graph.py::build_graph`, `nodes.py` |
| Why | Explicit, inspectable routing; no loops means bounded work per turn |
| Alternatives | A plain function pipeline, LangChain agents, native tool-calling loop |
| Pros/cons | Clear structure and testable nodes; but the current graph is linear enough that a function chain would also work, and it supports one tool per turn |
| Demonstrated | Deterministic parts (slot filling, routing) outside the LLM |

## MCP
STDIO JSON-RPC server (`backend/app/mcp_server.py`, `FastMCP`). Exposes the same tool layer so other MCP clients can use it. Identity: a scoped `aud=mcp` token in an env var, validated per call. Creation tools are prepare-only. Alternatives: HTTP transport with OAuth. Weakness: token sits in the process environment; SDK behaviour beyond what the code shows is unverified.

## Redis caching
Optional layer (`backend/app/cache/service.py`): TTL plus version-in-key invalidation plus targeted purge at ingest. Breaker avoids per-request timeouts when Redis is down. Chosen because embeddings and retrieval are pure functions of (query, model, index). Not cached: anything about customers or decisions. Alternatives: in-process LRU, no cache. Weakness: effect on latency is **unmeasured here** (benchmark harness exists; no results recorded).

## JWT authentication and RBAC
Short-lived HS256 token in an HttpOnly cookie; role and active status read from the database on each request; revocation list for logout; audience separation (`api` vs `mcp`). Permissions in one table (`security/permissions.py`) and checked again in the tool layer. Alternatives: server-side sessions, OAuth/OIDC. Weaknesses: shared secret, no rotation, no refresh tokens, no MFA.

## Password hashing
Argon2 via argon2-cffi (`security/passwords.py`), rehash on login if parameters change, dummy verification for unknown users to equalise timing, 12-128 character policy. Alternatives: bcrypt/scrypt. No lockout (rate limiting only).

## Prompt injection and trust boundaries
Principle: the model is not a security boundary. Controls that matter are structural: identity from the token, permissions/ownership in code, deterministic eligibility, server-side confirmation, tool arguments from code. Heuristic layers: sanitising, PII masking, chunk quarantine, canary, claim guard. Weakness: heuristics are best-effort; users can still lie about the reason or photo count (eligibility facts come from the database, evidence count does not).

## Logging, tracing and performance measurement
Per-request trace id, span timings, JSON request log without bodies, in-memory percentiles (`observability/*`), SQL timing via SQLAlchemy events, benchmark and evaluation scripts under `backend/evals/`. Why not Langfuse: extra services for little gain here. Weakness: metrics reset on restart; no distributed tracing.