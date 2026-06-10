#!/usr/bin/env python3
"""
Listen-only X Spaces intelligence: discover Spaces, capture transcripts, find pain points and NFT alpha.

Usage:
  python3 scripts/spaces_intel.py scan
  python3 scripts/spaces_intel.py scan --query nft
  python3 scripts/spaces_intel.py analyze
  python3 scripts/spaces_intel.py listen --device default
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
TRANSCRIPTS_PATH = ROOT / "data" / "spaces_intel" / "transcripts.jsonl"
INSIGHTS_PATH = ROOT / "data" / "spaces_intel" / "insights.jsonl"


def load_env() -> None:
    load_dotenv(ENV_PATH, override=True)


def load_config() -> dict:
    with open(ROOT / "config.json") as f:
        return json.load(f)


def ensure_output_dir() -> None:
    TRANSCRIPTS_PATH.parent.mkdir(parents=True, exist_ok=True)


async def scan_spaces(queries: list[str] | None = None) -> int:
    load_env()
    sys.path.insert(0, str(ROOT / "src"))

    from convo_backend.services.x_api import (
        construct_x_api_url,
        get_x_spaces,
        parse_x_spaces,
    )

    config = load_config()
    queries = queries or config.get("intel_keywords") or config.get("spaces_keywords", ["nft"])

    all_spaces = []
    seen_ids: set[str] = set()

    for query in queries:
        try:
            raw = await get_x_spaces(query)
        except KeyError as exc:
            print(f"Missing credential: {exc}")
            print("Set X_BEARER_TOKEN in .env to scan live Spaces.")
            return 1
        except Exception as exc:
            print(f"Search failed for '{query}': {exc}")
            continue

        for space in parse_x_spaces(raw):
            if space["space_id"] in seen_ids:
                continue
            seen_ids.add(space["space_id"])
            hosts = [u.get("username", u.get("name", "?")) for u in space.get("hosts", [])]
            speakers = [u.get("username", u.get("name", "?")) for u in space.get("speakers", [])]
            topics = [t.get("name", t.get("description", "")) for t in space.get("topics", [])]
            all_spaces.append(
                {
                    "space_id": space["space_id"],
                    "url": construct_x_api_url(space["space_id"]),
                    "query": query,
                    "hosts": hosts,
                    "speakers": speakers,
                    "speaker_count": len(speakers),
                    "topics": topics,
                }
            )

    all_spaces.sort(key=lambda s: s["speaker_count"], reverse=True)
    ensure_output_dir()
    out_path = ROOT / "data" / "spaces_intel" / "live_spaces.json"
    out_path.write_text(json.dumps(all_spaces, indent=2))

    print(f"Found {len(all_spaces)} live Spaces")
    for space in all_spaces[:10]:
        hosts = ", ".join(space["hosts"][:2]) or "unknown"
        print(f"  [{space['speaker_count']} speakers] {space['url']} — hosts: {hosts}")

    if len(all_spaces) > 10:
        print(f"  ... and {len(all_spaces) - 10} more")
    print(f"\nSaved to {out_path}")
    return 0


def load_transcripts(limit: int | None = None) -> list[dict]:
    if not TRANSCRIPTS_PATH.exists():
        return []
    lines = TRANSCRIPTS_PATH.read_text().strip().splitlines()
    if limit:
        lines = lines[-limit:]
    return [json.loads(line) for line in lines if line.strip()]


async def analyze_transcripts(limit: int = 50) -> int:
    load_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or "your_" in api_key:
        print("Set OPENAI_API_KEY in .env to analyze transcripts.")
        return 1

    transcripts = load_transcripts(limit=limit)
    if not transcripts:
        print(f"No transcripts found at {TRANSCRIPTS_PATH}")
        print("Run listen mode first to capture Space audio.")
        return 1

    sys.path.insert(0, str(ROOT / "src"))
    from langchain_community.document_loaders import TextLoader
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
    from convo_backend.config import Config

    prompt = TextLoader(Config.INTEL_ANALYSIS_PROMPT_PATH, encoding="utf-8").load()[0].page_content
    llm = ChatOpenAI(model="gpt-4o-mini", api_key=api_key, temperature=0)

    batch_text = json.dumps(transcripts, indent=2)
    response = await llm.ainvoke(
        [
            SystemMessage(content=prompt),
            HumanMessage(content=f"Analyze these Space transcripts:\n\n{batch_text}"),
        ]
    )

    try:
        insights = json.loads(response.content)
    except json.JSONDecodeError:
        insights = {"raw_analysis": response.content}

    ensure_output_dir()
    entry = {
        "analyzed_at": datetime.utcnow().isoformat() + "Z",
        "transcript_count": len(transcripts),
        "insights": insights,
    }
    with INSIGHTS_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")

    print(json.dumps(insights, indent=2))
    print(f"\nSaved to {INSIGHTS_PATH}")
    return 0


def listen_spaces(device: str, desired_spaces: list[str] | None) -> int:
    load_env()
    missing = []
    for key in ["X_USERNAME", "X_PASSWORD", "GOOGLE_APPLICATION_CREDENTIALS"]:
        val = os.getenv(key)
        if not val or "your_" in val:
            missing.append(key)

    if missing:
        print("Listen mode requires these .env values:")
        for key in missing:
            print(f"  - {key}")
        return 1

    cmd = [
        sys.executable,
        "-m",
        "src.convo_backend.app",
        "--device",
        device,
        "--intel",
        "--roam",
    ]
    if desired_spaces:
        cmd.extend(["--desired-spaces", ",".join(desired_spaces)])

    print("Starting listen-only intel mode (no talking, transcripts saved to data/spaces_intel/)")
    print("Press Enter in the terminal to stop.\n")
    os.execv(sys.executable, cmd)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="X Spaces intelligence — find pain points and NFT alpha"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Find live Spaces (needs X_BEARER_TOKEN only)")
    scan.add_argument("--query", action="append", help="Search query (repeatable)")
    scan.add_argument("--all-keywords", action="store_true", help="Scan all intel_keywords from config.json")

    analyze = sub.add_parser("analyze", help="Analyze saved transcripts for pain points and alpha")
    analyze.add_argument("--limit", type=int, default=50, help="Number of recent transcripts to analyze")

    listen = sub.add_parser("listen", help="Join Spaces listen-only and save transcripts")
    listen.add_argument("--device", default="default", choices=["default", "blackhole", "vb-cables"])
    listen.add_argument("--space", action="append", help="Specific Space URL or ID to listen to")

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.command == "scan":
        queries = None
        if args.query:
            queries = args.query
        elif args.all_keywords:
            queries = load_config().get("intel_keywords")
        return asyncio.run(scan_spaces(queries))

    if args.command == "analyze":
        return asyncio.run(analyze_transcripts(limit=args.limit))

    if args.command == "listen":
        return listen_spaces(device=args.device, desired_spaces=args.space)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
