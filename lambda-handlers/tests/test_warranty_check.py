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


warranty = _load_handler("warranty_check")


class WarrantyCheckTests(unittest.TestCase):
    def test_known_product(self):
        result = warranty.handler({"product_id": "PROD-001"}, None)

        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertEqual(body["product"], "Wireless Headphones")
        self.assertEqual(body["status"], "active")

    def test_product_id_is_normalized(self):
        result = warranty.handler({"product_id": "prod-003"}, None)

        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertEqual(body["status"], "expired")

    def test_unknown_product(self):
        result = warranty.handler({"product_id": "PROD-999"}, None)

        self.assertEqual(result["statusCode"], 404)
        body = json.loads(result["body"])
        self.assertEqual(body["error"], "No warranty found for PROD-999")

    def test_missing_product_id(self):
        result = warranty.handler({}, None)

        self.assertEqual(result["statusCode"], 404)
        body = json.loads(result["body"])
        self.assertEqual(body["error"], "No warranty found for ")
