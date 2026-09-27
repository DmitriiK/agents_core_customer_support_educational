"""One chat session, three turns, about the catalog and return policy.

Turn 1 asks for the accessories return policy. Turn 2 asks about the USB-C Hub.
Turn 3 asks what was just discussed and how long that category's return window is.
The prompts do not ask for a refund or a warranty check.

    RUN_E2E=1 uv run --project app/CustomerSupport python -m unittest tests.e2e.test_multistep -v
"""

import os
import unittest
import uuid

from tests.e2e.test_policy_enforcement import STATE_FILE, _access_token, _state, invoke_agent


@unittest.skipUnless(os.environ.get("RUN_E2E") == "1", "Set RUN_E2E=1 to call the deployed agent")
class MultistepConversationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not STATE_FILE.is_file():
            raise unittest.SkipTest(f"No deployed runtime state at {STATE_FILE}")
        cls.runtime_arn = _state()["runtimes"]["CustomerSupport"]["runtimeArn"]
        cls.token = _access_token()

    def _ask(self, prompt, session_id):
        reply = invoke_agent(prompt, self.token, self.runtime_arn, session_id)
        print(f"\nPROMPT: {prompt}\nREPLY: {reply}\n")
        return reply

    def test_follow_up_uses_earlier_turns(self):
        session_id = str(uuid.uuid4())

        policy = self._ask("What's the return policy for accessories?", session_id).lower()
        self.assertRegex(policy, r"14")
        self.assertRegex(policy, r"store credit|exchange")

        product = self._ask(
            "Tell me about the USB-C Hub from the product catalog: name, price, and category only.",
            session_id,
        ).lower()
        self.assertRegex(product, r"usb-c hub|prod-004")
        self.assertRegex(product, r"54\.99")

        follow_up = self._ask(
            "From this conversation: which product did we just discuss, "
            "and how many days is the return window for its category?",
            session_id,
        ).lower()
        self.assertRegex(follow_up, r"usb-c hub|prod-004")
        self.assertRegex(follow_up, r"14")


if __name__ == "__main__":
    unittest.main()
