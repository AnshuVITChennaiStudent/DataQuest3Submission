from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from inventory_store import append_product, load_products, normalize_product

HOST = "127.0.0.1"
PORT = 8001


class InventoryHandler(BaseHTTPRequestHandler):
    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # pragma: no cover
        self._send_json({"ok": True}, status=200)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json({"ok": True, "service": "dqps-inventory"})
            return
        if self.path == "/api/products":
            self._send_json(load_products())
            return

        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        if self.path != "/api/products":
            self._send_json({"error": "not found"}, status=404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")

        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON payload"}, status=400)
            return

        if isinstance(payload, list):
            items = [normalize_product(item) for item in payload]
            self._send_json({"saved": len(items), "products": items})
            return

        product = normalize_product(payload)
        updated = append_product(product)
        self._send_json({"saved": True, "products": updated})


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), InventoryHandler)
    print(f"Inventory backend running at http://{HOST}:{PORT}")
    server.serve_forever()
