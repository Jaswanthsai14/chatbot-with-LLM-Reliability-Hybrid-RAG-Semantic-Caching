# Agentic AI Assistant with MCP, Hybrid RAG & Semantic Caching

An AI-powered assistant built using **Python, LangGraph, Ollama (Llama 3), MCP, Redis, Sentence Transformers, Tavily, and Gradio**.

The assistant dynamically routes user queries to specialized agents for general questions, coding assistance, and tool execution. It integrates external tools through a low-level MCP server, retrieves Indian history knowledge using hybrid BM25 and semantic search, and uses Redis-based semantic caching to reduce repeated processing and response latency.

The system also incorporates model-based and deterministic guardrails, model routing, fallback mechanisms, retry logic, and LangSmith tracing.

## Features

- 🤖 **Agentic AI Workflow** — Routes requests dynamically using LangGraph.
- 🧭 **Intelligent Query Routing** — Selects basic, coding, or tool-calling agents.
- 🔌 **Low-Level MCP Server** — Exposes tools using the MCP Python SDK without a FastMCP wrapper.
- 🌦️ **Weather Information** — Retrieves current weather with primary API retries and a fallback provider.
- 🌐 **Web Search** — Uses Tavily to retrieve relevant web results and source URLs.
- 📚 **Hybrid RAG Retrieval** — Searches Indian history content using BM25 and semantic retrieval.
- 🎯 **RRF Fusion and Reranking** — Combines retrieval rankings and reranks results using a cross-encoder, as described by the history retrieval tool.
- ⚡ **Redis Semantic Caching** — Reuses responses for sufficiently similar queries.
- 🛡️ **Input Guardrails** — Applies deterministic validation and model-based input checks.
- 🔐 **Output Guardrails** — Validates generated responses and blocks selected sensitive credential patterns.
- 🔀 **Model Routing** — Routes queries to specialized agents based on intent.
- 🔄 **Fallback and Retries** — Improves resilience of weather and supported tool operations.
- 🧠 **Cache Decision Workflow** — Uses structured LLM output to decide whether a response is suitable for caching.
- 📊 **LangSmith Tracing** — Adds tracing metadata to the LangGraph workflow.
- 💬 **Gradio Chat Interface** — Provides a browser-based conversational interface.
- 🚀 **Asynchronous Execution** — Uses asynchronous graph execution and offloads blocking tool operations to threads where appropriate.

## Architecture

```text
                         User
                          │
                          ▼
                    Gradio Interface
                          │
                          ▼
                    LangGraph Workflow
                          │
                          ▼
                 Deterministic Guardrail
                          │
                          ▼
                   Model Guardrail
                          │
                          ▼
                    Semantic Cache
                          │
               ┌──────────┴──────────┐
               ▼                     ▼
           Cache Hit              Cache Miss
               │                     │
               │                     ▼
               │               Intent Router
               │                     │
               │          ┌──────────┼──────────┐
               │          ▼          ▼          ▼
               │        Basic      Coding    Tool Calling
               │          │          │          │
               │          │          │          ▼
               │          │          │      MCP Client
               │          │          │          │
               │          │          │          ▼
               │          │          │      MCP Server
               │          │          │          │
               │          │          │     ┌────┼─────────┐
               │          │          │     ▼    ▼         ▼
               │          │          │  Weather Web Search Indian
               │          │          │                     History RAG
               │          └──────────┴─────────┬───────────┘
               │                               ▼
               │                       Output Guardrail
               │                               │
               │                               ▼
               │                         Cache Decision
               │                               │
               │                               ▼
               │                         Cache Storage
               │                               │
               └──────────────┬────────────────┘
                              ▼
                       Markdown Formatting
                              │
                              ▼
                            Response
```

*This diagram represents the major components. A cache hit bypasses agent execution, output validation, and the additional LLM formatting call in the current workflow.*

## LangGraph Workflow

The application uses LangGraph to coordinate the assistant's execution.

### 1. Deterministic Input Guardrail

Validates incoming queries before processing.

- Rejects empty or invalid prompts.
- Enforces a 5,000-character input limit.
- Normalizes valid queries by removing leading and trailing whitespace.

### 2. Model-Based Input Guardrail

Uses the configured guardrail function to assess the user's prompt before routing it to an agent.

Blocked prompts receive a guardrail response instead of continuing through the workflow.

### 3. Semantic Cache Lookup

Checks Redis-based semantic caching before invoking the intent router.

- **Cache hit:** Returns the cached response.
- **Cache miss:** Continues to intent classification and agent execution.

This avoids repeating the full workflow for queries that match previously cached requests according to the configured similarity threshold.

### 4. Intent Classification

Uses Ollama with the `llama3:latest` model and structured output to select one of three routes.

| Route | Purpose |
|---|---|
| `basic` | General questions, explanations, greetings, and everyday topics |
| `coding` | Programming, debugging, code generation, and technical questions |
| `tool_calling` | Weather, web search, and Indian history questions requiring the MCP tool workflow |

The router uses a Pydantic schema to constrain the selected route.

### 5. Specialized Agents

The selected agent processes the request:

- **Basic Agent:** Handles general-purpose questions.
- **Coding Agent:** Handles programming and technical requests.
- **Tool-Calling Agent:** Executes the configured MCP tool workflow.

The three agent paths continue to output validation after execution.

### 6. Output Guardrail

Checks whether the generated response is a non-empty string and rejects responses containing selected private-key markers.

### 7. Cache Decision

Uses structured LLM output to decide whether the query-response pair should be cached.

The configured policy favors stable, reusable answers and excludes categories such as live weather, changing news, private information, errors, and state-changing action results.

### 8. Final Response Formatting

Formats generated responses as Markdown for the Gradio interface.

Cached responses skip the additional formatting LLM call.

## MCP Server

The project implements its MCP server using the low-level Python SDK:

```python
from mcp.server.lowlevel import Server
import mcp.types as types
```

The server registers tools explicitly and handles tool listing and execution through custom handlers.

**Unlike a FastMCP-based server, this implementation creates the ASGI application directly using `server.streamable_http_app()`.**

### Server Configuration

```python
HOST = "127.0.0.1"
PORT = 8001
```

The configured MCP endpoint is:

```text
http://127.0.0.1:8001/mcp
```

The server is run with Uvicorn.

### MCP Tools

#### 1. `get_weather`

Retrieves current weather information for a specified city.

**Input:**

```json
{
  "city": "Bengaluru"
}
```

**Implementation:**
- Uses wttr.in as the primary weather provider.
- Retries the primary provider up to three times.
- Waits one second between failed primary attempts.
- Uses WeatherAPI.com as a fallback when configured.
- Returns a user-friendly failure message if both providers fail.

The fallback requires `WEATHER_API_KEY` to be configured in the environment.

#### 2. `web_search`

Searches the web using Tavily.

**Input:**

```json
{
  "query": "Latest developments in artificial intelligence"
}
```

**Implementation:**
- Uses Tavily's basic search depth.
- Requests up to five results.
- Returns each result's title, URL, and content.
- Runs the synchronous search operation through `asyncio.to_thread()`.

The tool requires `TAVILY_API_KEY`.

#### 3. `indian_history_search`

Retrieves relevant documents from the Indian history knowledge base.

**Input:**

```json
{
  "query": "Explain the Mauryan Empire",
  "k": 5
}
```

**Implementation:**
- Calls `hybrid_retrieve()` from `history.retrieve`.
- Supports a configurable number of retrieved results.
- Defaults to five results.
- Validates that `k` is a positive integer.
- Returns retrieved document content and reranking scores when available.
- Runs the retrieval operation through `asyncio.to_thread()`.

The retrieval module describes a pipeline involving BM25, semantic retrieval, Reciprocal Rank Fusion (RRF), and cross-encoder reranking.

## Hybrid RAG Retrieval

The Indian history retrieval tool uses a hybrid approach to find relevant knowledge.

### BM25 Retrieval

Uses keyword-based relevance scoring to identify documents that match query terms.

This is useful when a question contains specific historical names, locations, events, or terminology.

### Semantic Retrieval

Uses vector embeddings to find documents that are semantically similar to a query, including cases where the wording differs.

### Reciprocal Rank Fusion (RRF)

Combines the rankings from multiple retrieval methods to produce a unified candidate ranking.

### Cross-Encoder Reranking

Reranks candidate documents according to their relevance to the query before the results are returned.

### Retrieval Flow

```text
Indian History Query
         │
         ▼
   BM25 Retrieval
         │
         ├────────────────┐
         │                │
         ▼                ▼
  Semantic Retrieval   Candidate Rankings
         │                │
         └───────┬────────┘
                 ▼
            RRF Fusion
                 │
                 ▼
       Cross-Encoder Reranking
                 │
                 ▼
        Top-K Relevant Documents
                 │
                 ▼
         MCP Tool Response
```

The exact retrieval settings, embedding model, and reranking model are defined in the `history.retrieve` implementation.

## Redis Semantic Caching

The assistant uses a semantic cache to avoid repeating expensive processing for sufficiently similar queries.

### Workflow

```text
Incoming Query
      │
      ▼
Generate Embedding
      │
      ▼
Search Cached Queries
      │
      ▼
Check Similarity Threshold
      │
   ┌──┴─────────────┐
   ▼                ▼
Cache Hit        Cache Miss
   │                │
   ▼                ▼
Return Cached   Run Agent Workflow
Response            │
                    ▼
               Validate Output
                    │
                    ▼
              Decide Cacheability
                    │
                    ▼
               Store If Allowed
```

### Cache Behavior

- Looks up semantically similar cached queries before intent classification.
- Returns a cached response when a suitable entry is found.
- Uses an LLM-based cacheability decision after output validation.
- Avoids caching certain dynamic, private, or action-oriented responses according to the configured prompt.
- Calls the cache storage function when the model decides that a response is suitable for caching.

The cache implementation is imported from `cache.py`; the embedding model, Redis schema, similarity threshold, TTL, and task queue behavior are defined in that module and its dependencies.

### Reported Performance

The project has reported the following measurements:

| Metric | Result |
|---|---:|
| Observed response latency before caching | 73.70 seconds |
| Observed response latency after caching | 0.81 seconds |
| Reported latency reduction | 98.90% |
| Approximate speedup | 91× |
| Cached-response P95 latency | 0.81 seconds |
| Samples used for P95 | 6 |

**Benchmark note:** The P95 result was calculated from six cached-response latency measurements using the nearest-rank method. It is a preliminary estimate, not a robust production P95. The before-and-after latency figures should be compared under equivalent conditions.

## Guardrails

The application uses deterministic checks and a model-based guardrail.

### Deterministic Input Validation

- Rejects empty prompts.
- Enforces a maximum input length of 5,000 characters.
- Trims whitespace from valid input.

### Model-Based Input Validation

Calls the configured `check_guardrail()` function before intent routing.

The implementation of that function determines the exact blocking criteria.

### Deterministic Output Validation

- Rejects empty or invalid model responses.
- Checks for selected private-key markers.
- Replaces blocked responses with a safe message.

The current code checks specific private-key header patterns; it should not be described as a comprehensive secret-detection system without additional validation.

## Model Routing and Resilience

The assistant uses structured output from Ollama to route queries to specialized agents.

The MCP tools also contain resilience mechanisms:

- Weather API retries.
- Weather fallback provider.
- Exception handling around tool execution.
- Error responses for failed tool calls.
- Input validation for MCP arguments.

The weather tool retries its primary provider three times before attempting its fallback provider. The web search and history retrieval tools use exception handling, but the provided code does not implement a general retry loop for those tools.

## LangSmith Tracing

The application configures LangSmith tracing through environment variables.

```python
os.environ["LANGSMITH_TRACING"] = "true"
os.environ["LANGSMITH_PROJECT"] = os.getenv(
    "LANGSMITH_PROJECT",
    "ai-assistant-project"
)
```

The LangGraph invocation includes:

- A run name: `gradio_ai_assistant`
- Tags: `gradio` and `semantic-cache`
- Metadata identifying the Gradio interface and enabled caching

This configuration supports workflow tracing and debugging, provided the required LangSmith credentials and environment settings are configured.

## Tech Stack

### AI & LLM

- Python
- Ollama
- Llama 3
- LangGraph
- LangChain
- Pydantic

### MCP & Tool Integration

- MCP Python SDK
- Low-level MCP `Server`
- Streamable HTTP transport
- Uvicorn
- HTTPX
- Tavily Search API
- wttr.in
- WeatherAPI.com

### Retrieval & RAG

- Retrieval-Augmented Generation
- BM25
- Semantic Retrieval
- Reciprocal Rank Fusion
- Cross-Encoder Reranking
- Embeddings

### Caching & Background Processing

- Redis-based semantic caching
- Sentence Transformers, as configured in the cache implementation
- Celery, where configured by the cache storage workflow

### Interface & Monitoring

- Gradio
- LangSmith
- Python `asyncio`
- `asyncio.to_thread()`

## Project Structure

The following is a conceptual structure based on the modules referenced in the provided code. Update it to match the actual repository layout.

```text
.
├── agents/
│   ├── basic.py
│   ├── coding.py
│   └── tool_call.py
├── guardrails/
│   └── checkpoint.py
├── history/
│   └── retrieve.py
├── cache.py
├── server.py          # MCP server entry point; use actual filename
├── graph.py           # LangGraph and Gradio application; use actual filename
├── .env
├── requirements.txt
└── README.md
```

## Installation

### 1. Clone the Repository

```bash
git clone <your-repository-url>
cd <your-project-directory>
```

Replace the placeholders with your repository URL and directory.

### 2. Create a Virtual Environment

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.venv\Scripts\activate
```

On Linux/macOS:

```bash
source .venv/bin/activate
```

### 3. Install Dependencies

If a `requirements.txt` file is available:

```bash
pip install -r requirements.txt
```

Ensure the dependencies used by your code are installed, including the MCP SDK, Uvicorn, HTTPX, Tavily client, LangGraph, LangChain integrations, Gradio, and dotenv.

### 4. Configure Environment Variables

Create a `.env` file.

Example:

```env
WEATHER_API_KEY=your_weatherapi_key
TAVILY_API_KEY=your_tavily_api_key
LANGSMITH_API_KEY=your_langsmith_api_key
LANGSMITH_PROJECT=ai-assistant-project
```

Add other variables required by your cache and retrieval modules.

Do not commit `.env`, API keys, or other secrets to GitHub.

### 5. Start Redis

Ensure Redis is running at the address configured by your cache implementation.

For example:

```text
redis://localhost:6379/0
```

If your cache uses Celery for background storage, start the required Celery worker as well.

### 6. Start Ollama

Install Ollama and ensure the configured model is available.

```bash
ollama pull llama3:latest
```

Verify that Ollama is running before launching the assistant.

### 7. Start the MCP Server

Run the Python file containing the low-level MCP server:

```bash
python <your-mcp-server-file>.py
```

The server is configured to listen at:

```text
http://127.0.0.1:8001/mcp
```

Use the actual filename from your repository.

### 8. Start the Assistant

Run the file containing the LangGraph workflow and Gradio interface:

```bash
python <your-assistant-file>.py
```

Gradio launches the browser interface when the application starts.

Replace the placeholder with the actual entry-point filename.

## Example Prompts

### General Question

```text
Explain how Python decorators work.
```

Expected route: `coding`

### Indian History

```text
Explain the Mauryan Empire.
```

Expected route: `tool_calling`, using the Indian history retrieval tool.

### Weather

```text
What is the current weather in Bengaluru?
```

Expected route: `tool_calling`, using `get_weather`.

### Web Search

```text
Search the web for recent developments in AI agents.
```

Expected route: `tool_calling`, using `web_search`.

### Semantic Cache

```text
Explain what a Python generator is.
```

Repeating the same or a sufficiently similar query may return a cached response if a matching cache entry exists and the cache is enabled.

## Current Capabilities

- Dynamic agent routing using LangGraph.
- Specialized basic, coding, and tool-calling agents.
- Low-level MCP server implementation.
- Current weather retrieval with retries and fallback.
- Tavily-powered web search.
- Indian history RAG through hybrid retrieval.
- BM25 and semantic retrieval with RRF and reranking.
- Redis semantic cache lookup and conditional storage.
- Deterministic and model-based input guardrails.
- Deterministic output validation.
- Structured LLM output for routing and cache decisions.
- LangSmith tracing configuration.
- Gradio chat interface.

## Future Improvements

- Add automated tests for routing, retrieval, guardrails, and MCP tools.
- Evaluate cache precision and false-positive cache hits.
- Collect a larger set of latency measurements.
- Add cache hit-rate and cache-miss monitoring.
- Expand the Indian history evaluation dataset.
- Add explicit timeout and retry policies to web search and retrieval where appropriate.
- Improve secret detection beyond specific private-key header patterns.
- Add authentication and authorization for deployed services.
- Add structured logging and application metrics.
- Containerize the MCP server, Redis, worker, and application using Docker.
- Add deployment configuration and health checks.
- Expand support for additional MCP tools.


## Author

**Jaswanth Sai**

AI Engineer | Agentic AI | LangGraph | MCP | RAG | LLM Applications
