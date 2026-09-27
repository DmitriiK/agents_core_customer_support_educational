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
