# 1. System architecture

## 1.1 Overall diagram
```mermaid
flowchart TB
  subgraph Browser
    UI["React app (frontend/src)"]
  end
  subgraph FastAPI["FastAPI process (backend/app)"]
    MW["Middleware: CORS, observability, headers, body limit"]
    ROUTES["Routers: auth, chat, agent, orders, refunds, tickets, staff, admin, ops"]
    DEPS["security/deps.py: get_principal, require_permission, customer_context"]
    AGENT["LangGraph agent (app/agent)"]
    TOOLS["Tool layer (tools/support_tools.py)"]
    SVC["Services (app/services)"]
    RAGM["RAG: ai/rag.py, ai/embeddings.py, services/retrieval_service.py"]
    CACHE["CacheService (cache/service.py)"]
    OBS["Metrics and tracing (observability)"]
  end
  MCP["MCP server, separate process, STDIO (mcp_server.py)"]
  SQLITE[("SQLite file")]
  CHROMA[("ChromaDB files")]
  REDIS[("Redis, optional")]
  OLLAMA["Ollama :11434 /api/chat"]
  UI -->|"JSON + cookie"| MW --> ROUTES --> DEPS
  ROUTES --> AGENT
  ROUTES --> TOOLS
  AGENT --> TOOLS
  AGENT --> RAGM
  AGENT -->|"httpx"| OLLAMA
  TOOLS --> SVC --> SQLITE
  RAGM --> CHROMA
  RAGM -.-> CACHE -.-> REDIS
  MCP --> TOOLS
  MW -.-> OBS
```

## 1.2 Components
| Component | Responsibility and why | Technology | Key files | Receives → produces | Depended on by |
|---|---|---|---|---|---|
| Frontend | Login, chat, orders, staff and admin screens; never trusts itself for authorization | React + TypeScript + Vite | `frontend/src/App.tsx`, `frontend/src/services/http.ts` | user input → HTTP requests; renders JSON | users |
| Backend API | Validates requests, authenticates, routes to tools/agent | FastAPI, Pydantic | `backend/app/main.py`, `backend/app/api/routes/agent.py` | HTTP → JSON | frontend |
| Auth and RBAC | Identity from a validated token, central permissions | Argon2, PyJWT | `backend/app/security/deps.py`, `backend/app/security/permissions.py` | cookie/bearer → `Principal` | every protected route, tools, MCP |
| Agent | Classifies intent, gathers data, prepares actions, phrases answers | LangGraph | `backend/app/agent/graph.py`, `backend/app/agent/nodes.py` | message + context → `AgentChatResponse` | `routes/agent.py`, eval harness |
| LLM | Language understanding (classification) and phrasing | Ollama via httpx | `backend/app/services/llm_service.py` | messages → text/JSON | agent, legacy chat |
| RAG | Policy knowledge: chunk, embed, store, retrieve | ChromaDB, sentence-transformers | `backend/app/ai/rag.py`, `backend/app/ai/embeddings.py`, `backend/app/services/retrieval_service.py` | question → ranked `RetrievedChunk` list | agent, legacy chat |
| Database | Source of truth for orders, refunds, tickets, users, audit | SQLite + SQLAlchemy 2 | `backend/app/models/entities.py`, `backend/app/database/session.py` | queries → rows | services, tools |
| Tool layer | Permission, ownership, audit, metrics for customer operations | plain Python | `backend/app/tools/support_tools.py` | typed input + `ToolContext` → `ToolResult` | REST routes, agent, MCP |
| Business rules | Deterministic refund eligibility | plain Python | `backend/app/services/refund_eligibility_service.py` | order + reason → `EligibilityResult` | tools |
| MCP server | Same tools over the Model Context Protocol | MCP SDK 1.x (`FastMCP`) | `backend/app/mcp_server.py` | JSON-RPC over STDIO → tool results | external MCP clients |
| Cache | Optional speed-up for embeddings, retrieval, opt-in answers | Redis (redis-py) | `backend/app/cache/service.py` | key material → JSON or miss | embeddings, retrieval, agent |
| Observability | Trace ids, spans, metrics, request log | stdlib | `backend/app/observability/metrics.py`, `backend/app/observability/middleware.py` | requests → log lines, counters | admin metrics endpoint |
| Evaluation | Repeatable quality and rule checks | scripts + JSON | `backend/evals/run.py`, `backend/evals/bench.py` | datasets → reports | developers |

## 1.3 Frontend architecture
```mermaid
flowchart TB
  APP["App.tsx: AuthProvider + Shell"] --> LOGIN["LoginPage"]
  APP --> CHAT["ChatPage"]
  APP --> ORD["OrdersPanel"]
  APP --> STAFF["StaffPanel"]
  APP --> ADMIN["AdminPanel"]
  CHAT --> MB["MessageBubble"]
  ORD --> RC["RefundCheck"]
  ORD --> TF["TicketForm"]
  APP --> CTX["context/AuthContext.ts + hooks/useAuth.ts"]
  CHAT --> CA["services/chatApi.ts"]
  ORD --> SA["services/supportApi.ts"]
  STAFF --> AA["services/adminApi.ts"]
  ADMIN --> AA
  LOGIN --> AU["services/authApi.ts"]
  CA --> HTTP["services/http.ts apiFetch"]
  SA --> HTTP
  AA --> HTTP
  AU --> HTTP
```
`Shell` (in `frontend/src/App.tsx`) chooses the screens by `user.role`; the backend enforces the same rules independently. `frontend/src/main.tsx` comes from the Vite template (content **unverified**).

## 1.4 Backend architecture (layers)
```mermaid
flowchart TB
  R["api/routes/*: HTTP only"] --> D["security/deps: identity, permission, rate limit"]
  R --> T["tools/support_tools: permission + ownership + audit"]
  R --> A["agent/*: orchestration"]
  A --> T
  T --> S["services/*: queries and rules"]
  S --> M["models + database/session"]
  T --> SEC["security/audit, permissions"]
```
Rule of the codebase: routes contain no business logic; tools are the single choke point for customer operations.

## 1.5 AI / LLM and RAG architecture
```mermaid
flowchart LR
  MSG["message"] --> CL["classify_node: Ollama JSON, temperature 0"]
  CL --> RP["retrieve_policy_node"]
  RP --> RET["retrieval_service.retrieve"]
  RET -->|"hit"| RC["Redis rag cache"]
  RET -->|"miss"| EMB["embeddings.embed_query"]
  EMB -->|"hit"| EC["Redis embedding cache"]
  EMB -->|"miss"| ST["SentenceTransformer"]
  EMB --> CH["Chroma collection.query"]
  CH --> SC["screen_chunks"]
  SC --> RESP["respond_node: Ollama text"]
```
Ingestion (offline): `backend/app/ai/rag.py::ingest` reads `data/policies/*.md`, chunks by `##` section, embeds with `embed_texts`, upserts to Chroma, writes the index version file, purges the `rag` cache namespace.

## 1.6 Database architecture
See the ER diagram in [05-data-flow.md](05-data-flow.md). Eight tables: `customers`, `orders`, `refund_requests`, `support_tickets`, `pending_actions`, `users`, `revoked_tokens`, `audit_logs`, created by `backend/app/database/session.py::init_db` (`create_all`, no migrations).

## 1.7 LangGraph orchestration
```mermaid
flowchart TB
  START --> classify
  classify -->|"missing slot"| clarify --> END1["END"]
  classify -->|"policy_question"| retrieve_policy
  classify -->|"order_status, list_orders, refund_eligibility"| run_order_tool
  classify -->|"refund_request, ticket_request"| prepare_action --> END2["END"]
  classify -->|"chitchat, off_topic"| respond
  run_order_tool -->|"needs_policy"| retrieve_policy
  run_order_tool --> respond
  retrieve_policy --> respond --> END3["END"]
```
Built in `backend/app/agent/graph.py::build_graph`. No loops: a turn runs at most one tool, one retrieval and two LLM calls.

## 1.8 MCP architecture
```mermaid
flowchart LR
  CLIENT["MCP client (Inspector or agent host)"] -->|"STDIO JSON-RPC"| SRV["mcp_server.py FastMCP tools"]
  SRV --> RUN["_run: validate aud=mcp token per call"]
  RUN --> TOOLS["support_tools (channel mcp)"]
  RUN --> PREP["agent/actions.prepare_*: prepare-only"]
  PREP --> PEND[("pending_actions")]
  PEND -. "customer confirms in the app" .-> CONF["POST /api/agent/confirm"]
```
The MCP process is separate from the API process and opens SQLite directly. It shares the in-process code, not the API.

## 1.9 Redis caching architecture
```mermaid
flowchart LR
  EQ["embed_query"] --> CS["CacheService"]
  RQ["retrieve"] --> CS
  RN["respond_node (opt-in)"] --> CS
  CS -->|"error"| BR["breaker: skip Redis 10 s, count cache.error"]
  CS --> R[("Redis")]
  ING["rag.ingest"] -->|"clear_by_prefix rag"| CS
```
Namespaces: `embedding`, `rag`, `llm`. SQLite and ChromaDB remain the sources of truth; eligibility, authorization and customer data are never cached.

## 1.10 Authentication and authorization
```mermaid
flowchart LR
  REQ["request"] --> EX["extract_token: cookie then Bearer"]
  EX --> CS["enforce_csrf (cookie, unsafe methods)"]
  CS --> PT["principal_from_token: signature, aud, exp, revoked, user active"]
  PT --> P["Principal (role from DB)"]
  P --> RP["require_permission"]
  RP --> CC["customer_context -> ToolContext"]
  CC --> Q["SQL WHERE customer_id = principal.customer_id"]
```

## 1.11 External and local dependencies
| Dependency | Link | Used by |
|---|---|---|
| Ollama | HTTP to `OLLAMA_BASE_URL` `/api/chat` (httpx) | `backend/app/services/llm_service.py` |
| sentence-transformers / PyTorch | in-process | `backend/app/ai/embeddings.py` |
| ChromaDB | in-process `PersistentClient` on disk | `backend/app/ai/rag.py::get_client` |
| SQLite | in-process file via SQLAlchemy | `backend/app/database/session.py` |
| Redis | TCP via redis-py pool, 0.25 s timeouts | `backend/app/cache/service.py` |
| MCP client | STDIO JSON-RPC | `backend/app/mcp_server.py` |
| Browser | HTTP, cookie `sp_session` | `frontend/src/services/http.ts` |