
import os
import asyncio
import httpx
import uvicorn

from urllib.parse import quote
from dotenv import load_dotenv
from tavily import TavilyClient

from mcp.server.lowlevel import Server
import mcp.types as types

from history.retrieve import hybrid_retrieve


# ---------------- CONFIGURATION ----------------

load_dotenv()

HOST = "127.0.0.1"
PORT = 8001

WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")


# ---------------- WEB SEARCH ----------------

def search_web(query: str) -> str:
    if not TAVILY_API_KEY:
        raise ValueError("TAVILY_API_KEY is not configured")

    client = TavilyClient(api_key=TAVILY_API_KEY)

    response = client.search(
        query=query,
        max_results=5,
        search_depth="basic",
    )

    results = response.get("results", [])

    if not results:
        return "No relevant search results found."
    print("web")
    print(query)
    print(results)
    return "\n\n".join(
        (
            f"Title: {item.get('title', 'No title')}\n"
            f"URL: {item.get('url', '')}\n"
            f"Content: {item.get('content', '')}"
        )
        for item in results
    )


# ---------------- WEATHER ----------------

async def get_weather_primary(city: str) -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"https://wttr.in/{quote(city)}",
            params={"format": "3"},
        )
        response.raise_for_status()
        return response.text


async def get_weather_fallback(city: str) -> str:
    if not WEATHER_API_KEY:
        raise ValueError("WEATHER_API_KEY is not configured")

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            "https://api.weatherapi.com/v1/current.json",
            params={
                "key": WEATHER_API_KEY,
                "q": city,
            },
        )
        response.raise_for_status()

        data = response.json()
        current = data["current"]
        location = data["location"]

        return (
            f"Weather in {location['name']}:\n"
            f"Temperature: {current['temp_c']} °C\n"
            f"Condition: {current['condition']['text']}\n"
            f"Humidity: {current['humidity']}%\n"
            f"Wind speed: {current['wind_kph']} km/h"
        )


async def fetch_weather(city: str) -> str:
    for attempt in range(3):
        try:
            print(f"Primary weather API attempt {attempt + 1}")
            return await get_weather_primary(city)

        except (httpx.HTTPError, ValueError) as exc:
            print(f"Primary weather API failed: {exc}")

            if attempt < 2:
                await asyncio.sleep(1)

    try:
        print("Using WeatherAPI.com fallback")
        return await get_weather_fallback(city)

    except (httpx.HTTPError, ValueError, KeyError) as exc:
        print(f"Fallback weather API failed: {exc}")
        return "Weather service unavailable. Please try again later."


# ---------------- TOOL SCHEMAS ----------------

TOOLS = [
    types.Tool(
        name="get_weather",
        description=(
            "Get current weather for a city. "
            "Retries the primary API and uses a fallback if needed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name, e.g. Bengaluru",
                }
            },
            "required": ["city"],
        },
    ),
    types.Tool(
        name="web_search",
        description=(
            "Search the web using Tavily for relevant information, "
            "recent developments, and source URLs."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The web search query",
                }
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="indian_history_search",
        description=(
            "Search the Indian History knowledge base using hybrid "
            "BM25 and semantic retrieval, RRF fusion, and "
            "cross-encoder reranking."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Question about Indian history",
                },
                "k": {
                    "type": "integer",
                    "description": "Number of relevant chunks to return",
                    "default": 5,
                    "minimum": 1,
                },
            },
            "required": ["query"],
        },
    ),
]


# ---------------- LIST TOOLS HANDLER ----------------

async def handle_list_tools(ctx, params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=TOOLS)


# ---------------- CALL TOOL HANDLER ----------------

async def handle_call_tool(
    ctx,
    params: types.CallToolRequestParams,
) -> types.CallToolResult:

    name = params.name
    arguments = params.arguments or {}

    try:
        # Weather
        if name == "get_weather":
            city = arguments.get("city", "").strip()

            if not city:
                result = "Please provide a valid city name."
            else:
                result = await fetch_weather(city)

        # Web search
        elif name == "web_search":
            query = arguments.get("query", "").strip()

            if not query:
                result = "Please provide a search query."
            else:
                result = await asyncio.to_thread(
                    search_web,
                    query,
                )

        # Indian History RAG
        elif name == "indian_history_search":
            query = arguments.get("query", "").strip()
            k = arguments.get("k", 5)

            if not query:
                result = "Please provide an Indian history question."

            elif (
                not isinstance(k, int)
                or isinstance(k, bool)
                or k < 1
            ):
                result = "The number of results must be a positive integer."

            else:
                documents = await asyncio.to_thread(
                    hybrid_retrieve,
                    query,
                    k=k,
                )

                if not documents:
                    result = "No relevant Indian history documents found."
                else:
                    formatted_results = []

                    for index, doc in enumerate(documents, start=1):
                        formatted_results.append(
                            f"Document {index}:\n"
                            f"Content: {doc.page_content}\n"
                            f"Rerank score: "
                            f"{doc.metadata.get('rerank_score', 'N/A')}"
                        )

                    result = "\n\n".join(formatted_results)

        else:
            result = f"Unknown tool: {name}"

        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=result,
                )
            ]
        )

    except Exception as exc:
        print(f"Tool {name} failed: {exc}")

        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=f"Tool execution failed: {name}. Please try again.",
                )
            ],
            isError=True,
        )


# ---------------- LOW-LEVEL MCP SERVER ----------------

server = Server(
    "mcp-server",
    version="1.0.0",
    on_list_tools=handle_list_tools,
    on_call_tool=handle_call_tool,
)


# Create the ASGI app directly.
# No FastMCP wrapper and no manual Starlette Mount.
app = server.streamable_http_app(
    streamable_http_path="/mcp",
    host=HOST,
)


# ---------------- START SERVER ----------------

if __name__ == "__main__":
    print(f"MCP server starting at http://{HOST}:{PORT}/mcp")

    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
    )
