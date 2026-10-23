# Agentic RAG Chatbot with Hybrid Retrieval, Guardrails & Semantic Caching

An AI-powered Retrieval-Augmented Generation (RAG) chatbot built using Python, LangGraph, LangChain, Google Gemini, MCP, Redis, Sentence Transformers, and LangSmith.

The chatbot combines **BM25 keyword search and semantic retrieval** to retrieve relevant context, uses model-based and deterministic guardrails to validate requests and outputs, and implements Redis-based semantic caching to reduce repeated LLM calls and response latency.

It also supports MCP tool integration, model routing, automatic fallback, retry mechanisms, and RAG evaluation.

## Features

- 🔎 **Hybrid RAG Retrieval** — Combines BM25 keyword search with semantic similarity search.
- 🤖 **Agentic Chatbot** — Uses LangGraph to orchestrate LLM-powered workflows.
- 🧠 **Semantic Search** — Uses embedding models to identify semantically similar queries.
- ⚡ **Redis Semantic Caching** — Reuses cached responses for similar queries.
- 🛡️ **AI Guardrails** — Combines model-based guardrails with deterministic output validation.
- 🔀 **Model Routing** — Routes requests to configured models.
- 🔄 **Fallback & Retries** — Handles model failures and retries failed operations.
- 🔌 **MCP Tool Integration** — Connects the chatbot to external tools through the Model Context Protocol.
- 📊 **RAG Evaluation** — Evaluates retrieval quality using metrics such as Precision@K, MRR, and NDCG@K.
- 🔍 **Context Relevance Evaluation** — Assesses the relevance of retrieved context.
- 🧪 **LangSmith Integration** — Supports tracing and evaluation of LLM workflows.
- 🚀 **Latency Optimization** — Reduces repeated processing through semantic caching.

## Architecture

```text
                         User Query
                              │
                              ▼
                       LangGraph Workflow
                              │
                              ▼
                       Model Routing
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
          Semantic Cache              Cache Miss
              (Redis)                     │
                 │                         ▼
          Cache Hit Response       Hybrid Retrieval
                                     ┌────┴─────┐
                                     ▼          ▼
                                  BM25      Semantic Search
                                     │          │
                                     └────┬─────┘
                                          ▼
                                  Retrieved Context
                                          │
                                          ▼
                                    MCP Tool Calls
                                          │
                                          ▼
                                  LLM Response Generation
                                          │
                                          ▼
                                      Guardrails
                                          │
                               ┌──────────┴──────────┐
                               ▼                     ▼
                         Output Valid           Validation Failure
                               │                     │
                               ▼                     ▼
                       Cache Response          Retry / Fallback
                               │
                               ▼
                             Response
```

*Architecture is a conceptual overview; exact execution order depends on the implementation.*

## Hybrid Retrieval

The chatbot combines two retrieval approaches:

### BM25 Keyword Retrieval
- Matches query terms against indexed documents.
- Helps retrieve documents containing specific keywords, names, and technical terms.
- Uses lexical relevance scoring.

### Semantic Retrieval
- Converts queries and documents into vector embeddings.
- Identifies semantically similar content even when exact keywords differ.
- Uses vector similarity to rank candidate documents.

### Hybrid Search
Combines keyword-based and semantic retrieval to improve the relevance of the context supplied to the LLM.

Reported evaluation results:

| Metric | Reported Result |
|---|---:|
| Precision@K — before improvement | 0.35 |
| Precision@K — after improvement | 0.80 |
| MRR | 1.00 |
| Context relevance | 1.00 |

*These are reported project results. Evaluation quality depends on the dataset, relevance labels, and evaluation methodology.*

## Semantic Caching

Redis is used to store generated responses and reuse them when incoming queries are sufficiently similar to previously cached queries.

### Workflow

```text
Incoming Query
      │
      ▼
Generate Query Embedding
      │
      ▼
Compare Against Cached Queries
      │
      ▼
Check Similarity Threshold
      │
   ┌──┴───────────────┐
   ▼                  ▼
Cache Hit          Cache Miss
   │                  │
   ▼                  ▼
Return Cached     Run Retrieval
Response          and LLM Workflow
                      │
                      ▼
                 Store Response
                      │
                      ▼
                 Return Response
```

### Reported Performance

- Observed response latency decreased from **73.70 seconds to 0.81 seconds**.
- Reported latency reduction: **98.90%**.
- Approximate speedup: **91×**.
- Cached-response P95 latency: **0.81 seconds across 6 samples**, calculated using the nearest-rank method.

**Note:** The P95 figure is based on only six cached-response measurements, so it should be treated as preliminary rather than a reliable estimate of production performance. The overall latency comparison should also be based on comparable requests and test conditions.

## Guardrails

The chatbot uses model-based and deterministic guardrails to validate requests or generated outputs.

### Model-Based Guardrails
- Uses an LLM-based evaluation approach to assess whether outputs meet the configured criteria.
- Reported model-based guardrail accuracy: **91%**.

### Deterministic Guardrails
- Applies rule-based checks and output validation.
- Provides predictable validation for explicitly defined constraints.

The two approaches complement each other: model-based checks handle more nuanced cases, while deterministic checks enforce defined rules.

## Model Routing & Reliability

The chatbot includes mechanisms designed to improve model execution reliability:

- **Model Routing:** Selects a configured model for a request.
- **Fallback:** Attempts an alternative configured model when the primary model fails.
- **Retries:** Retries eligible failed operations.
- **Resilient Tool Execution:** Uses fallback APIs and retries for supported MCP tool operations.

Actual routing policies, retry limits, and fallback conditions depend on the application configuration.

## MCP Tool Integration

The project integrates tools using the **Model Context Protocol (MCP)**.

The MCP integration connects the agent workflow with external tool capabilities without adding extra wrapper layers around the MCP tools.

### Tool Execution
- Connects to the configured MCP server.
- Exposes supported tools to the agent workflow.
- Supports fallback APIs and retry mechanisms where implemented.
- Allows the chatbot to incorporate tool results into its response-generation process.

### Example MCP Server URL

```text
http://127.0.0.1:8001/mcp
```

The URL above reflects the development endpoint used in the project configuration. The actual endpoint and transport depend on the MCP server setup.

## RAG Evaluation

The project uses LangSmith to support tracing and evaluation of retrieval workflows.

### Evaluation Metrics

| Metric | Purpose |
|---|---|
| Precision@K | Measures the proportion of the top-K retrieved documents that are relevant. |
| MRR | Measures how highly the first relevant result is ranked. |
| NDCG@K | Evaluates ranking quality while accounting for the positions of relevant results. |
| Context Relevance | Evaluates whether the retrieved context is relevant to the query. |
| Retrieval Latency | Measures the time required to retrieve relevant context. |

Evaluation results should be interpreted alongside the dataset, relevance labels, and evaluation methodology.

## Tech Stack

### AI & LLM Engineering
- Python
- LangChain
- LangGraph
- Google Gemini
- Sentence Transformers
- Embeddings and semantic similarity

### Retrieval
- BM25
- Semantic Search
- Hybrid Retrieval
- Retrieval-Augmented Generation (RAG)

### Backend & Caching
- Redis
- MCP
- FastAPI, where configured
- Retry and fallback mechanisms

### Evaluation & Monitoring
- LangSmith
- Precision@K
- Mean Reciprocal Rank (MRR)
- Normalized Discounted Cumulative Gain (NDCG@K)
- Context relevance evaluation

## Installation

### 1. Clone the Repository

```bash
git clone <your-repository-url>
cd <your-project-directory>
```

Replace the placeholders with your actual GitHub repository URL and project directory.

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

If your repository includes a `requirements.txt` file:

```bash
pip install -r requirements.txt
```

Otherwise, install the dependencies specified by your project.

### 4. Configure Environment Variables

Create a `.env` file and add the credentials required by your implementation.

Example:

```env
GOOGLE_API_KEY=your_google_api_key
LANGSMITH_API_KEY=your_langsmith_api_key
REDIS_URL=redis://localhost:6379/0
```

Add any additional environment variables required by your project. Do not commit API keys or other secrets to GitHub.

### 5. Start Redis

Ensure that Redis is installed and running at the configured address.

Default development URL:

```text
redis://localhost:6379/0
```

### 6. Start the MCP Server

Run the MCP server using the entry-point file configured in your repository.

For example, if the server entry point is `server.py`:

```bash
python server.py
```

Replace `server.py` with the actual MCP server filename.

### 7. Run the Chatbot

Start the application using your configured entry point.

For example:

```bash
python main.py
```

Replace `main.py` with the actual application entry point.

## Example Use Cases

### Knowledge Retrieval

```text
Explain the main concepts discussed in the knowledge base.
```

### Semantic Query Matching

```text
Find information about a concept even if the document uses different wording.
```

### Context-Grounded Question Answering

```text
Answer my question using the retrieved context.
```

### MCP Tool Execution

```text
Use the appropriate available tool to retrieve the required information.
```

### Reliability

```text
Handle a model failure using the configured fallback mechanism.
```

These prompts illustrate possible interactions; actual behavior depends on the tools and workflows enabled in your implementation.

## Current Capabilities

- Agentic workflow orchestration using LangGraph
- Retrieval-Augmented Generation
- BM25 and semantic hybrid retrieval
- Redis semantic caching
- Model routing and fallback mechanisms
- Retry mechanisms for supported operations
- Model-based and deterministic guardrails
- MCP tool integration
- LangSmith-based tracing and evaluation
- Retrieval quality measurement

## Future Improvements

- Expand the retrieval evaluation dataset.
- Collect larger-scale latency benchmarks.
- Improve semantic cache threshold tuning.
- Add cache hit-rate and cache-miss monitoring.
- Evaluate model routing policies across different workloads.
- Add more comprehensive automated tests.
- Improve guardrail evaluation with a larger labelled test set.
- Add containerized deployment with Docker.
- Introduce scalable deployment and observability.
- Add authentication and access controls where required.

## License

Specify the license used by your repository. If no license has been selected, choose one before publishing the project for reuse.

## Author

**Jaswanth Sai**

AI Engineer | Agentic AI | LangGraph | MCP | RAG | LLM Applications
