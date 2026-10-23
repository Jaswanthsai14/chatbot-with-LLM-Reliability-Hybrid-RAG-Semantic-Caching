
from dotenv import load_dotenv

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from langchain.agents import create_agent
from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langsmith import traceable

from pydantic import create_model, Field


load_dotenv()

MCP_URL = "http://127.0.0.1:8001/mcp"


def make_langchain_tool(session, mcp_tool):
    """Convert an MCP tool into a LangChain tool."""

    schema = (
        getattr(mcp_tool, "input_schema", None)
        or getattr(mcp_tool, "inputSchema", None)
        or {}
    )

    properties = schema.get("properties", {})
    required = schema.get("required", [])

    type_map = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    fields = {}

    for name, definition in properties.items():
        python_type = type_map.get(
            definition.get("type", "string"),
            str,
        )

        default = ... if name in required else None

        fields[name] = (
            python_type,
            Field(
                default=default,
                description=definition.get("description", ""),
            ),
        )

    args_schema = create_model(
        f"{mcp_tool.name.title().replace('_', '')}Input",
        **fields,
    )

    async def execute_tool(**kwargs):
        """Call the corresponding MCP server tool."""

        result = await session.call_tool(
            mcp_tool.name,
            arguments=kwargs,
        )

        is_error = getattr(
            result,
            "is_error",
            getattr(result, "isError", False),
        )

        output = []

        for item in getattr(result, "content", []):
            item_text = getattr(item, "text", None)

            if item_text is not None:
                output.append(item_text)

        response = "\n".join(output)

        if is_error:
            return f"MCP tool error: {response}"

        return response or str(result)

    # IMPORTANT: Return the LangChain tool.
    return StructuredTool(
        name=mcp_tool.name,
        description=mcp_tool.description or mcp_tool.name,
        args_schema=args_schema,
        coroutine=execute_tool,
    )


@traceable(name="MCP Tool Calling Agent", run_type="chain")
async def tool_calling(query: str) -> str:
    """Connect to MCP and run the Gemini agent."""

    async with streamable_http_client(MCP_URL) as (
        read_stream,
        write_stream,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
        ) as session:

            await session.initialize()

            mcp_result = await session.list_tools()

            print("Available MCP tools:")

            for tool in mcp_result.tools:
                schema = (
                    getattr(tool, "input_schema", None)
                    or getattr(tool, "inputSchema", None)
                    or {}
                )

                print(
                    f"- {tool.name}: "
                    f"{list(schema.get('properties', {}).keys())}"
                )

            langchain_tools = [
                make_langchain_tool(session, tool)
                for tool in mcp_result.tools
            ]

            model = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                temperature=0,
            )

            agent = create_agent(
                model=model,
                tools=langchain_tools,
                system_prompt=(
                    "You are a helpful assistant. "
                    "Use available tools when necessary. "
                    "Answer clearly using tool results when relevant."
                ),
            )

            result = await agent.ainvoke({
                "messages": [
                    {"role": "user", "content": query}
                ]
            })

            message = result["messages"][-1]
            content = message.content

            if isinstance(content, str):
              return content

            if isinstance(content, list):
               return "\n".join(
        item.get("text", str(item))
        if isinstance(item, dict)
        else getattr(item, "text", str(item))
        for item in content
        if (
            isinstance(item, dict) and item.get("type") == "text"
        ) or getattr(item, "type", None) == "text"
    )

    return str(content)
