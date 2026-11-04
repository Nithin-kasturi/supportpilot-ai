from langgraph.graph import END, START, StateGraph

from app.agent.memory import MEMORY
from app.agent.nodes import (
    classify_node,
    clarify_node,
    prepare_action_node,
    respond_node,
    retrieve_policy_node,
    route_after_classify,
    route_after_tool,
    run_order_tool_node,
)
from app.agent.state import AgentState
from app.core.config import settings
from app.schemas.agent import AgentChatResponse
from app.schemas.chat import Source
from app.tools.support_tools import ToolContext


def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("classify", classify_node)
    builder.add_node("clarify", clarify_node)
    builder.add_node("retrieve_policy", retrieve_policy_node)
    builder.add_node("run_order_tool", run_order_tool_node)
    builder.add_node("prepare_action", prepare_action_node)
    builder.add_node("respond", respond_node)

    builder.add_edge(START, "classify")
    builder.add_conditional_edges(
        "classify",
        route_after_classify,
        {
            "clarify": "clarify",
            "retrieve_policy": "retrieve_policy",
            "run_order_tool": "run_order_tool",
            "prepare_action": "prepare_action",
            "respond": "respond",
        },
    )
    builder.add_conditional_edges(
        "run_order_tool",
        route_after_tool,
        {"retrieve_policy": "retrieve_policy", "respond": "respond"},
    )
    builder.add_edge("retrieve_policy", "respond")
    builder.add_edge("clarify", END)
    builder.add_edge("prepare_action", END)
    builder.add_edge("respond", END)
    return builder.compile()


AGENT_GRAPH = build_graph()


def run_agent(ctx: ToolContext, conversation_id: str, message: str) -> AgentChatResponse:
    memory = MEMORY.get(ctx.customer.id, conversation_id)
    final = AGENT_GRAPH.invoke(
        {
            "ctx": ctx,
            "message": message,
            "history": list(memory.history),
            "last_order_number": memory.last_order_number,
            "slots": dict(memory.slots),
            "tool_results": [],
            "actions": [],
        },
        {"recursion_limit": settings.agent_recursion_limit},
    )

    reply = final["reply"]
    memory.history.extend(
        [{"role": "user", "content": message}, {"role": "assistant", "content": reply}]
    )
    del memory.history[: -settings.agent_history_messages]
    if final.get("verified_order"):
        memory.last_order_number = final["verified_order"]
    memory.slots = dict(final.get("next_slots") or {})

    return AgentChatResponse(
        reply=reply,
        intent=final["intent"],
        sources=[
            Source(
                document=c.source,
                category=c.category,
                section=c.section,
                chunk_id=c.chunk_id,
                similarity=c.similarity,
            )
            for c in final.get("chunks") or []
        ],
        actions=final.get("actions", []),
        confirmation=final.get("confirmation"),
    )