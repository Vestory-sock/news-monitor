"""Bounded persistence of seen news IDs across runs (file-based, committed to repo)."""
import json
import os
from pathlib import Path

STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
MAX_ENTRIES = 5000  # bounded to avoid unbounded file growth


def load_seen() -> set[str]:
    if not STATE_FILE.exists():
        return set()
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        return set(data.get("seen", []))
    except Exception as e:
        print(f"[state] load error: {e}, starting fresh")
        return set()


def save_seen(seen: set[str]) -> None:
    seen_list = list(seen)
    if len(seen_list) > MAX_ENTRIES:
        # Keep the tail (most recent additions). Sets aren't ordered, so this is approximate
        # but good enough since we just need to bound the file.
        seen_list = seen_list[-MAX_ENTRIES:]
    with open(STATE_FILE, "w") as f:
        json.dump({"seen": seen_list}, f)
