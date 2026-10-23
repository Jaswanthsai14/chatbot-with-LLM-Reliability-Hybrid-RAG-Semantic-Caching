
from typing import TypedDict, Literal

import gradio as gr

from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from guardrails.checkpoint import check_guardrail
from agents.basic import Basic
from agents.coding import Coding
from agents.tool_call import tool_calling

from cache import get_cached_response, cache_response
import os
from dotenv import load_dotenv

load_dotenv()
os.environ["LANGSMITH_TRACING"] = "true"
os.environ["LANGSMITH_PROJECT"] = os.getenv(
    "LANGSMITH_PROJECT",
    "ai-assistant-project"
)

ollama = ChatOllama(
    model="llama3:latest",
    temperature=0
)




class State(TypedDict):
    query: str
    next: str
    isChache: bool
    cache: str
    res: str




class RouterOutput(BaseModel):
    next: Literal["basic", "coding", "tool_calling"] = Field(
        description="Selected agent"
    )


# ---------------- CACHE DECISION ----------------

class CacheDecision(BaseModel):
    cache: bool = Field(
        description="Whether this response should be cached"
    )
    reason: str = Field(
        description="Reason for the cache decision"
    )


# ---------------- INPUT GUARDRAIL ----------------

def deterministic_guardrail(state: State):
    query = state.get("query", "")

    if not isinstance(query, str) or not query.strip():
        state["res"] = "Please enter a valid prompt."
        state["next"] = "final"
        return state

    if len(query) > 5000:
        state["res"] = "Your prompt exceeds the 5000-character limit."
        state["next"] = "final"
        return state

    state["query"] = query.strip()
    state["next"] = "model_guardrail"
    return state


def model_guardrail(state: State):
    if check_guardrail(state["query"]):
        state["res"] = "Your prompt was blocked by the input guardrail."
        state["next"] = "final"
        return state

    state["next"] = "router"
    return state


# ---------------- ROUTER + SEMANTIC CACHE ----------------

def router(state: State):
    query = state["query"]

    # Check Redis semantic cache first
    cached_response = get_cached_response(query)

    if cached_response is not None:
        print("Semantic cache HIT")

        state["res"] = cached_response
        state["isChache"] = True
        state["next"] = "final"
        return state

    print("Semantic cache MISS")

    state["isChache"] = False

    router_llm = ollama.with_structured_output(RouterOutput)

    router_prompt = ChatPromptTemplate.from_messages([
        (
    "system",
    """Choose exactly one route:

    basic: General questions, explanations, greetings, and everyday topics
    unrelated to Indian history, weather, or web search.

    coding: Programming, code generation, debugging, algorithms, and
    technical implementation questions.

    tool_calling: Weather queries, web search requests, and ALL questions
    related to Indian history that should use the Indian History RAG pipeline.
    This includes historical empires, dynasties, kings, rulers, battles,
    monuments, historical events, and ancient, medieval, or modern Indian history.

    Examples:
    - "Tell me about the Mauryan Empire" -> tool_calling
    - "Who was Ashoka?" -> tool_calling
    - "Explain the Gupta Empire" -> tool_calling
    - "When was the Battle of Plassey?" -> tool_calling
    - "What is the weather in Hyderabad?" -> tool_calling
    - "Search for the latest AI news" -> tool_calling
    - "Explain Python decorators" -> coding
    - "What is photosynthesis?" -> basic
    - "Hello" -> basic

    Rules:
    - Always choose tool_calling for Indian history questions.
    - If the query asks about Indian history, do not classify it as basic.
    - Choose exactly one route: basic, coding, or tool_calling.
    - Return only the route label, with no explanation.
    - Do not answer the user's question."""
),
("human", "{query}")
    ])

    result = (router_prompt | router_llm).invoke({
        "query": query
    })
    print(result.next)
    state["next"] = result.next
    return state




def basic_agent(state: State):
    result = Basic(state["query"]).chat()

    state["res"] = result
    state["next"] = "output_guardrail"

    return state


def coding_agent(state: State):
    result = Coding(state["query"]).chat()

    state["res"] = result
    state["next"] = "output_guardrail"

    return state


async def tool_agent(state: State):
    result = await tool_calling(state["query"])

    state["res"] = (
        result.content
        if hasattr(result, "content")
        else str(result)
    )

    state["next"] = "output_guardrail"

    return state


# ---------------- OUTPUT GUARDRAIL ----------------

def output_guardrail(state: State):
    response = state.get("res", "")

    if not isinstance(response, str) or not response.strip():
        state["res"] = (
            "I couldn't generate a valid response. Please try again."
        )
        state["next"] = "final"
        return state

    blocked_patterns = [
        "-----BEGIN PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----",
    ]

    if any(pattern in response for pattern in blocked_patterns):
        state["res"] = (
            "The response was blocked because it may contain "
            "sensitive credentials."
        )
        state["next"] = "final"
        return state

    state["res"] = response.strip()
    state["next"] = "cache_decision"

    return state


# ---------------- CACHE DECISION ----------------

def cache_decision(state: State):
    cache_llm = ollama.with_structured_output(CacheDecision)

    cache_prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            """Decide whether the query-response pair is safe and
            useful to store in a semantic cache.

            Cache:
            - Stable, reusable general knowledge
            - Useful, reasonably complete explanations

            Do not cache:
            - Errors or failure messages
            - Live weather, news or changing information
            - Private, confidential or user-specific information
            - Email sending or other state-changing action results
            - Incomplete or clarification responses

            Be conservative. If uncertain, return cache=false."""
        ),
        (
            "human",
            "Query:\n{query}\n\nResponse:\n{response}"
        )
    ])

    decision = (cache_prompt | cache_llm).invoke({
        "query": state["query"],
        "response": state["res"]
    })

    state["cache"] = decision.reason

    if decision.cache:
        # Celery queues the task.
        # The worker embeds the query and stores the entry in Redis.
        cache_response(
            state["query"],
            state["res"]
        )

        print("Cache storage task queued")

    state["next"] = "final"

    return state


# ---------------- FINAL NODE ----------------

def final(state: State):
    response = state.get("res", "")

    if not response:
        state["res"] = "Please enter a valid prompt."
        return state

    # Avoid another LLM call just to format a cached response.
    if state.get("isChache", False):
        return state
    
    markdown_response = ollama.invoke(
        f"""Format the following content as clean Markdown
for display in a Gradio Markdown component.

Preserve the original meaning and technical details.
Return only the formatted Markdown.

Content:
{response}"""
    )

    state["res"] = (
        markdown_response.content
        if hasattr(markdown_response, "content")
        else str(markdown_response)
    )
   
   

    return state


# ---------------- BUILD GRAPH ----------------

work = StateGraph(State)

work.add_node("init", deterministic_guardrail)
work.add_node("model_guardrail", model_guardrail)
work.add_node("router", router)

work.add_node("basic", basic_agent)
work.add_node("coding", coding_agent)
work.add_node("tool_calling", tool_agent)

work.add_node("output_guardrail", output_guardrail)
work.add_node("cache_decision", cache_decision)
work.add_node("final", final)

work.set_entry_point("init")

work.add_conditional_edges(
    "init",
    lambda s: s["next"],
    {
        "model_guardrail": "model_guardrail",
        "final": "final",
    }
)

work.add_conditional_edges(
    "model_guardrail",
    lambda s: s["next"],
    {
        "router": "router",
        "final": "final",
    }
)

work.add_conditional_edges(
    "router",
    lambda s: s["next"],
    {
        "basic": "basic",
        "coding": "coding",
        "tool_calling": "tool_calling",
        "final": "final",
    }
)

for node in ["basic", "coding", "tool_calling"]:
    work.add_edge(node, "output_guardrail")

work.add_conditional_edges(
    "output_guardrail",
    lambda s: s["next"],
    {
        "cache_decision": "cache_decision",
        "final": "final",
    }
)

work.add_edge("cache_decision", "final")
work.add_edge("final", END)

graph = work.compile()


# ---------------- GRADIO INVOKE ----------------



async def invoke(message, history):
    # Intentionally ignore history.

    config: RunnableConfig = {
        "run_name": "gradio_ai_assistant",
        "tags": ["gradio", "semantic-cache"],
        "metadata": {
            "interface": "gradio",
            "cache_enabled": True,
        },
    }

    result = await graph.ainvoke(
        {
            "query": message,
            "next": "",
            "isChache": False,
            "cache": "",
            "res": "",
        },
        config=config,
    )

    return result["res"]


# ---------------- GRADIO UI ----------------

def inter():
    with gr.Blocks(
        css="""
        .gradio-container {
            max-width: 900px !important;
            margin: auto !important;
        }
        """
    ) as demo:

        gr.ChatInterface(
            fn=invoke,
            title="📧 AI Assistant",
            description=(
                "Ask questions about programming, general topics, "
                "weather, web search and Indian history."
            )
        )

    demo.launch()


if __name__ == "__main__":
    inter()
