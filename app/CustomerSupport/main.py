from strands import Agent
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from model.load import load_model
from mcp_client.client import get_streamable_http_mcp_client, get_gateway_mcp_client
from memory.session import get_memory_session_manager
from prompts.load import load_system_prompt
from tools.customer_support import get_product_info, get_return_policy
import jwt

app = BedrockAgentCoreApp()
log = app.logger

_agent = None

def get_or_create_agent(session_id, user_id, auth_header):
    global _agent

    session_manager = get_memory_session_manager(session_id, user_id)

    # MCP clients: Exa AI (web search) + AgentCore Gateway (Lambda tools)
    mcp_clients = [get_streamable_http_mcp_client(), get_gateway_mcp_client(auth_header)]
    tools = [get_return_policy, get_product_info]

    # Add MCP client (Exa AI web search) to tools
    for mcp_client in mcp_clients:
        if mcp_client:
            tools.append(mcp_client)

    if _agent is None:
        _agent = Agent(
            model=load_model(),
            session_manager=session_manager,
            system_prompt=load_system_prompt(),
            tools=tools
        )
    return _agent

def extract_user_id(auth_header) -> str | None:
    """Extract user_id from JWT bearer token (username claim) or fall back to custom header."""

    if auth_header and auth_header.startswith("Bearer "):
        try:
            token = auth_header.split(" ", 1)[1]
            claims = jwt.decode(token, options={"verify_signature": False})
            username = claims.get("username")
            if username:
                return username
        except Exception as e:
            log.warning(f"Failed to decode JWT for user_id: {e}")
    else:
        log.info(f"No Bearer token found. Auth header present: {auth_header is not None}")
        raise Exception("No authorization header")

@app.entrypoint
async def invoke(payload, context):
    log.info("Invoking Agent.....")

    session_id = context.session_id
    request_headers = context.request_headers

    # Access request headers - handle None case
    request_headers = context.request_headers or {}

    # Get Client JWT token
    auth_header = request_headers.get('Authorization', '')

    if not auth_header:
        raise Exception("No authorization header")

    user_id = extract_user_id(auth_header)

    if not session_id or not user_id:
        raise ValueError("session_id and user_id are required. Pass --session-id and --user-id when invoking.")

    agent = get_or_create_agent(session_id, user_id, auth_header)
    stream = agent.stream_async(payload.get("prompt"))
    async for event in stream:
        if "data" in event and isinstance(event["data"], str):
            yield event["data"]

if __name__ == "__main__":
    app.run()