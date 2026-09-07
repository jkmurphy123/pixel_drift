#!/usr/bin/env python3
"""
Refresh data/llm_pricing.json from public pricing sources.

This is a best-effort updater. Pricing pages change often and many are
JavaScript-heavy, so the script tries a few stable API endpoints first and
falls back to keeping the existing values when a source cannot be reached or
parsed. Always review the diff before committing updated prices.

Suggested cron entry (weekly; review prices periodically, OpenRouter includes markup):
    0 3 * * 1 cd /home/ubuntu/ai_projects/pixel_drift && .venv/bin/python scripts/refresh_llm_pricing.py --apply
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_FILE = ROOT / "data" / "llm_pricing.json"

# Map provider slug -> (OpenRouter provider prefix, [canonical model ids]).
# Prices are stored per 1M tokens; APIs usually give per-token prices.
PROVIDER_MODEL_MAP = {
    "openai": ("openai", ["gpt-4o-mini", "gpt-4o", "gpt-4.1", "o3", "o4-mini"]),
    "google-gemini": (
        "google",
        ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
    ),
    "anthropic": ("anthropic", ["claude-4-opus", "claude-4-sonnet", "claude-4-haiku"]),
    "deepseek": ("deepseek", ["deepseek-chat", "deepseek-reasoner"]),
    "xai": ("x-ai", ["grok-3", "grok-3-mini"]),
}

# Canonical model id in our file -> OpenRouter model id we want to query.
# This lets us use stable ids in the data file even when the API names differ.
CANONICAL_TO_API_ID = {
    "deepseek-v3": "deepseek-chat",
    "deepseek-r1": "deepseek-reasoner",
}


def load_json(path: Path) -> dict:
    if not path.exists():
        return {"meta": {}, "providers": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict, apply: bool = False):
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if not apply:
        print(f"[dry-run] would write {path}")
        print(text[:2000])
        if len(text) > 2000:
            print("... (truncated)")
        print("\nPass --apply to write these changes to disk.")
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[refresh] wrote {path}")


def http_get_json(url: str, timeout: int = 25) -> dict | None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"[refresh] fetch failed for {url}: {exc}")
        return None


def fetch_openrouter_prices() -> dict[str, dict[str, dict[str, float | None]]]:
    """
    Fetch per-token pricing from OpenRouter and convert to per-1M-token prices.
    Returns {provider_slug: {canonical_model_id: {"input": ..., "output": ...}}}
    """
    data = http_get_json("https://openrouter.ai/api/v1/models")
    if not data or "data" not in data:
        return {}

    # Index models by full id for quick lookup.
    by_id: dict[str, dict] = {}
    for model in data.get("data", []):
        mid = model.get("id", "")
        if mid:
            by_id[mid] = model

    result: dict[str, dict[str, dict[str, float | None]]] = {}

    for provider_slug, (prefix, api_ids) in PROVIDER_MODEL_MAP.items():
        for api_id in api_ids:
            # Map any canonical alias back to the API id.
            canonical_id = None
            for can_id, mapped_api_id in CANONICAL_TO_API_ID.items():
                if mapped_api_id == api_id:
                    canonical_id = can_id
                    break
            if canonical_id is None:
                canonical_id = api_id

            full_id = f"{prefix}/{api_id}"
            model = by_id.get(full_id)

            # Fallback to a dated variant if the plain id is missing.
            if model is None:
                for mid in by_id:
                    if mid.startswith(f"{full_id}-20") and re.match(
                        rf"^{re.escape(full_id)}-\d{{4}}-\d{{2}}-\d{{2}}$", mid
                    ):
                        model = by_id[mid]
                        break

            if model is None:
                continue

            pricing = model.get("pricing", {})
            try:
                input_price = float(pricing.get("prompt", 0) or 0) * 1_000_000
                output_price = float(pricing.get("completion", 0) or 0) * 1_000_000
            except (TypeError, ValueError):
                continue

            result.setdefault(provider_slug, {})[canonical_id] = {
                "input": input_price if input_price > 0 else None,
                "output": output_price if output_price > 0 else None,
            }

    return result


def update_providers(data: dict, fetched: dict) -> bool:
    changed = False
    for provider in data.get("providers", []):
        slug = provider.get("slug", "")
        updates = fetched.get(slug, {})
        if not updates:
            continue
        for model in provider.get("models", []):
            canonical = model.get("id", "")
            new_prices = updates.get(canonical)
            if not new_prices:
                continue
            for key in ("input", "output"):
                new_val = new_prices.get(key)
                old_val = model.get(key)
                if new_val is not None and new_val != old_val:
                    model[key] = round(new_val, 4)
                    changed = True
                    print(
                        f"[refresh] updated {slug}/{canonical} {key}: "
                        f"{old_val} -> {model[key]}"
                    )
    return changed


def main():
    parser = argparse.ArgumentParser(description="Refresh LLM pricing data file.")
    parser.add_argument(
        "--data-file",
        type=Path,
        default=DEFAULT_DATA_FILE,
        help="Path to llm_pricing.json",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply fetched prices to the data file (default is dry-run)",
    )
    args = parser.parse_args()

    data_file = Path(args.data_file).expanduser()
    data = load_json(data_file)

    if "meta" not in data:
        data["meta"] = {}
    if "providers" not in data:
        data["providers"] = []

    print("[refresh] fetching OpenRouter prices...")
    fetched = fetch_openrouter_prices()
    if fetched:
        print(f"[refresh] matched prices for {list(fetched.keys())}")
    else:
        print("[refresh] no fetchable prices this run; keeping existing values")

    changed = update_providers(data, fetched)

    if changed or not data["meta"].get("last_updated"):
        data["meta"]["last_updated"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        changed = True

    if changed:
        data["meta"]["source_note"] = (
            "OpenRouter-routed prices; verify against provider direct pricing before use"
        )
        save_json(data_file, data, apply=args.apply)
    else:
        print("[refresh] no price changes; file not modified")


if __name__ == "__main__":
    main()
