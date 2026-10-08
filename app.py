"""Local app entry for the Vite + React prototype.

This project is served by Vite/React. The Python side now provides the shared
inventory JSON and a small HTTP backend that the React form can call.

Typical local run sequence:
    cd project+ui/project
    npm install
    npm run dev -- --host 0.0.0.0
    python3 inventory_backend.py
"""

from __future__ import annotations

from inventory_store import load_products


def main() -> None:
    products = load_products()
    print(f"Inventory sync is active with {len(products)} products loaded.")
    print("Use 'npm run dev -- --host 0.0.0.0' for the frontend and 'python3 inventory_backend.py' for the local API.")


if __name__ == "__main__":
    main()
