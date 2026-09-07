"""Keep file encounter order when recognition reuses existing library items."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runtime = tempfile.TemporaryDirectory(prefix="hwpmake_recognition_order_", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = runtime.name

from app import importers, storage


def main() -> None:
    storage.init_db()
    existing = importers.import_csv("order.csv", b"number,stem\n27,Alpha\n12,Gamma\n", {})
    assert len(existing["created"]) == 2
    full = importers.import_csv("order.csv", b"number,stem\n27,Alpha\n5,Beta\n12,Gamma\n", {})
    assert len(full["created"]) == 1 and len(full["existing"]) == 2
    by_id = {p["id"]: p for p in full["created"] + full["existing"]}
    assert [by_id[i]["number"] for i in full["ordered_ids"]] == ["27", "5", "12"]
    assert full["ordered_ids"] != [p["id"] for p in full["created"] + full["existing"]]
    repeated = importers.import_csv("order.csv", b"number,stem\n27,Alpha\n5,Beta\n12,Gamma\n", {})
    assert not repeated["created"] and repeated["ordered_ids"] == full["ordered_ids"]
    duplicate = importers.import_csv("order.csv", b"number,stem\n27,Alpha\n27,Alpha\n5,Beta\n12,Gamma\n", {})
    assert duplicate["ordered_ids"] == full["ordered_ids"], "same item must not appear twice"
    text = importers.import_text("sample.txt", b"1. First item.\n\n2. Second item.", {})
    assert text["ordered_ids"] == [p["id"] for p in text["created"]]
    text_again = importers.import_text("sample.txt", b"1. First item.\n\n2. Second item.", {})
    assert text_again["ordered_ids"] == text["ordered_ids"] and not text_again["created"]
    print("RECOGNITION_ORDER_OK: mixed existing/new, all existing, intra-file duplicate, text retry")


if __name__ == "__main__":
    main()
