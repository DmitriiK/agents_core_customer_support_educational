"""End-to-end checks for the Lab 7 policy scenarios.

Gateway tests call the secured gateway tools with the workshop Cognito user.
Cedar permits `process_refund` only when `amount < 100`, and permits
`check_warranty` for any authenticated user. A denied call never reaches Lambda.

Chat tests send the workshop prompts through the deployed runtime. Each chat
case uses a new session and a new order id. The $500 chat check asserts the
customer is refused. The gateway check asserts Cedar denied the tool call.

These calls need a deployed runtime and spend model tokens on the chat cases.
They stay skipped unless you opt in:

    RUN_E2E=1 uv run --project app/CustomerSupport python -m unittest tests.e2e.test_policy_enforcement -v
"""

import asyncio
import json
import os
import random
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import boto3
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError

REGION = "us-east-1"
WORKSHOP_USER = "workshopuser@example.com"
WORKSHOP_PASS = "WorkshopPass1!"
REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_FILE = REPO_ROOT / "agentcore" / ".cli" / "deployed-state.json"
REFUND_TOOL = "ProcessRefund___process_refund"
WARRANTY_TOOL = "WarrantyCheck___check_warranty"


def _state():
    return json.loads(STATE_FILE.read_text())["targets"]["default"]["resources"]


def _access_token():
    ssm = boto3.client("ssm", region_name=REGION)
    client_id = ssm.get_parameter(Name="/app/customersupport/agentcore/web_client_id")["Parameter"]["Value"]
    cognito = boto3.client("cognito-idp", region_name=REGION)
    resp = cognito.initiate_auth(
        AuthFlow="USER_PASSWORD_AUTH",
        ClientId=client_id,
        AuthParameters={"USERNAME": WORKSHOP_USER, "PASSWORD": WORKSHOP_PASS},
    )
    return resp["AuthenticationResult"]["AccessToken"]


def _parse_runtime_body(body):
    """Join SSE data lines the same way the chat UI does."""
    chunks = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        chunk = line[6:].strip()
        if not chunk:
            continue
        if chunk.startswith('"') and chunk.endswith('"'):
            chunk = json.loads(chunk)
        chunks.append(chunk)
    return "".join(chunks) if chunks else body


def invoke_agent(prompt, token, runtime_arn, session_id):
    escaped = urllib.parse.quote(runtime_arn, safe="")
    url = f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{escaped}/invocations?qualifier=DEFAULT"
    request = urllib.request.Request(
        url,
        data=json.dumps({"prompt": prompt}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = response.read().decode()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise AssertionError(f"Runtime invocation failed ({exc.code}): {detail}") from exc
    reply = _parse_runtime_body(body).strip()
    if not reply:
        raise AssertionError(f"Empty agent reply for prompt: {prompt}")
    return reply


def _order_id():
    return f"ORD-{random.randint(10000, 99999)}"


async def _call_tool(gateway_mcp_url, token, name, arguments):
    """Return the tool result, or the policy denial message.

    McpError is caught inside the MCP session. If it propagates out of the
    streamable HTTP client, anyio wraps it in an ExceptionGroup and the
    denial text is harder to assert on.
    """
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(headers=headers, timeout=30) as http_client:
        async with streamable_http_client(gateway_mcp_url, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                try:
                    return await session.call_tool(name, arguments)
                except McpError as exc:
                    return exc


def call_tool(gateway_mcp_url, token, name, arguments):
    result = asyncio.run(_call_tool(gateway_mcp_url, token, name, arguments))
    if isinstance(result, McpError):
        raise result
    return result


def _tool_text(result):
    return "\n".join(block.text for block in result.content if getattr(block, "text", None))


@unittest.skipUnless(os.environ.get("RUN_E2E") == "1", "Set RUN_E2E=1 to call the deployed agent")
class PolicyEnforcementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not STATE_FILE.is_file():
            raise unittest.SkipTest(f"No deployed runtime state at {STATE_FILE}")
        resources = _state()
        cls.runtime_arn = resources["runtimes"]["CustomerSupport"]["runtimeArn"]
        cls.gateway_mcp_url = resources["gateways"]["my-gateway-secure"]["gatewayUrl"].rstrip("/") + "/mcp"
        cls.token = _access_token()

    def _ask(self, prompt, session_id=None):
        session_id = session_id or str(uuid.uuid4())
        reply = invoke_agent(prompt, self.token, self.runtime_arn, session_id)
        print(f"\nPROMPT: {prompt}\nREPLY: {reply}\n")
        return reply

    def test_gateway_permits_refund_under_100(self):
        order_id = _order_id()
        result = call_tool(
            self.gateway_mcp_url,
            self.token,
            REFUND_TOOL,
            {"order_id": order_id, "amount": 50, "reason": "item arrived damaged"},
        )
        self.assertFalse(result.isError)
        body = json.loads(json.loads(_tool_text(result))["body"])
        self.assertEqual(body["status"], "approved")
        self.assertEqual(body["order_id"], order_id)
        self.assertEqual(body["refund_amount"], 50)

    def test_gateway_denies_refund_of_100_or_more(self):
        for amount in (100, 500):
            with self.subTest(amount=amount):
                with self.assertRaises(McpError) as caught:
                    call_tool(
                        self.gateway_mcp_url,
                        self.token,
                        REFUND_TOOL,
                        {
                            "order_id": _order_id(),
                            "amount": amount,
                            "reason": "item arrived damaged",
                        },
                    )
                message = str(caught.exception)
                self.assertIn("Tool Execution Denied", message)
                self.assertIn("policy enforcement", message)
                self.assertNotIn("processed successfully", message)

    def test_gateway_permits_warranty_check(self):
        result = call_tool(
            self.gateway_mcp_url,
            self.token,
            WARRANTY_TOOL,
            {"product_id": "PROD-002"},
        )
        self.assertFalse(result.isError)
        body = json.loads(json.loads(_tool_text(result))["body"])
        self.assertEqual(body["product"], "Smart Watch")
        self.assertEqual(body["status"], "active")
        self.assertEqual(body["warranty_months"], 24)
        self.assertEqual(body["expires"], "2028-01-15")

    def test_chat_refund_under_limit_is_processed(self):
        order_id = _order_id()
        reply = self._ask(
            f"I need a refund of $50 for order {order_id}. The item arrived damaged. "
            "Please process it now and tell me the tool result."
        )
        lowered = reply.lower()
        self.assertIn(order_id.lower(), lowered, reply)
        self.assertRegex(lowered, r"process|approved|success", reply)
        self.assertNotRegex(
            lowered,
            r"unable to process|cannot process|not permitted|denied|exceeds",
            reply,
        )

    def test_chat_refund_at_or_over_limit_is_denied(self):
        order_id = _order_id()
        session_id = str(uuid.uuid4())
        reply = self._ask(
            f"Process a refund of $500 for order {order_id}. "
            "I want a full refund because the item arrived damaged.",
            session_id,
        )
        lowered = reply.lower()
        self.assertIn(order_id.lower(), lowered, reply)
        self.assertNotIn("processed successfully", lowered, reply)
        self.assertRegex(
            lowered,
            r"denied|declined|cannot|unable|not permitted|not allowed|policy|contact",
            reply,
        )

    def test_chat_warranty_check_is_permitted(self):
        reply = self._ask("Check the warranty for PROD-002 and include the product name, status, and expiration.")
        lowered = reply.lower()
        self.assertRegex(lowered, r"smart watch|prod-002", reply)
        self.assertIn("active", lowered, reply)
        self.assertRegex(lowered, r"24|2028", reply)


if __name__ == "__main__":
    unittest.main()
