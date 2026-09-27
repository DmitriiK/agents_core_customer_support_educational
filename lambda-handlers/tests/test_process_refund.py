import importlib.util
import json
import unittest
from pathlib import Path


def _load_handler(folder):
    path = Path(__file__).resolve().parents[1] / folder / "index.py"
    spec = importlib.util.spec_from_file_location(f"{folder}_index", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


refund = _load_handler("process_refund")


class ProcessRefundTests(unittest.TestCase):
    def setUp(self):
        refund.clear_results()

    def test_processes_refund(self):
        result = refund.handler(
            {"amount": 25, "order_id": "ORD-10", "reason": "damaged"},
            None,
        )

        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertEqual(body["status"], "approved")
        self.assertEqual(body["order_id"], "ORD-10")
        self.assertEqual(body["refund_amount"], 25)
        self.assertEqual(body["reason"], "damaged")
        self.assertEqual(
            body["message"],
            "Refund of $25 for order ORD-10 processed successfully",
        )

    def test_defaults_missing_fields(self):
        result = refund.handler({}, None)

        body = json.loads(result["body"])
        self.assertEqual(body["refund_amount"], 0)
        self.assertEqual(body["order_id"], "unknown")
        self.assertEqual(body["reason"], "not specified")

    def test_same_idempotency_key_returns_existing_refund(self):
        calls = {"n": 0}
        original = refund._issue_refund

        def counting_issuer(*args):
            calls["n"] += 1
            return original(*args)

        first = refund.refund_customer(
            "ORD-10",
            25,
            "damaged",
            "operation-123",
            issuer=counting_issuer,
            sleep=lambda _delay: None,
        )
        second = refund.refund_customer(
            "ORD-10",
            25,
            "damaged",
            "operation-123",
            issuer=counting_issuer,
            sleep=lambda _delay: None,
        )

        self.assertEqual(calls["n"], 1)
        self.assertEqual(first["refund_id"], second["refund_id"])
        self.assertEqual(second["idempotency_key"], "operation-123")
        self.assertEqual(second["status"], "approved")

    def test_different_idempotency_key_creates_another_refund(self):
        first = refund.refund_customer(
            "ORD-10", 25, "damaged", "operation-123", sleep=lambda _delay: None
        )
        second = refund.refund_customer(
            "ORD-10", 25, "damaged", "operation-456", sleep=lambda _delay: None
        )

        self.assertNotEqual(first["refund_id"], second["refund_id"])

    def test_retries_retryable_failures_with_exponential_backoff(self):
        calls = {"n": 0}
        delays = []

        def flaky(order_id, amount, reason, idempotency_key):
            calls["n"] += 1
            if calls["n"] < 3:
                raise refund.RetryableFailure("throttled")
            return refund._issue_refund(order_id, amount, reason, idempotency_key)

        result = refund.refund_customer(
            "ORD-10",
            25,
            "damaged",
            "operation-123",
            issuer=flaky,
            sleep=delays.append,
        )

        self.assertEqual(calls["n"], 3)
        self.assertEqual(delays, [0.05, 0.1])
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["idempotency_key"], "operation-123")

    def test_exhausted_retries_are_not_stored(self):
        def always_fail(*_args):
            raise refund.RetryableFailure("unavailable")

        with self.assertRaises(refund.RetryableFailure):
            refund.refund_customer(
                "ORD-10",
                25,
                "damaged",
                "operation-123",
                issuer=always_fail,
                sleep=lambda _delay: None,
            )

        stored = refund.refund_customer(
            "ORD-10",
            25,
            "damaged",
            "operation-123",
            sleep=lambda _delay: None,
        )
        self.assertEqual(stored["status"], "approved")

    def test_handler_returns_503_when_retries_are_exhausted(self):
        def always_fail(*_args):
            raise refund.RetryableFailure("unavailable")

        original = refund._issue_refund
        refund._issue_refund = always_fail
        try:
            result = refund.handler(
                {
                    "amount": 25,
                    "order_id": "ORD-10",
                    "reason": "damaged",
                    "idempotency_key": "operation-123",
                },
                None,
            )
        finally:
            refund._issue_refund = original

        self.assertEqual(result["statusCode"], 503)
        body = json.loads(result["body"])
        self.assertEqual(body["status"], "unavailable")
        self.assertEqual(body["idempotency_key"], "operation-123")
