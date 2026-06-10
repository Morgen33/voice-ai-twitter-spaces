#!/usr/bin/env python3
"""
Configure and verify an X account for Convo AI Spaces roaming.

Usage:
  python scripts/setup_x_spaces.py check
  python scripts/setup_x_spaces.py login
  python scripts/setup_x_spaces.py join --space https://x.com/i/spaces/SPACE_ID
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE = ROOT / "env.example"

REQUIRED_FOR_ROAMING = ["X_USERNAME", "X_PASSWORD"]
OPTIONAL_FOR_SEARCH = ["X_BEARER_TOKEN", "X_API_BEARER_TOKEN"]
OPTIONAL_API = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]


def ensure_env_file() -> None:
    if ENV_PATH.exists():
        return
    if not ENV_EXAMPLE.exists():
        raise FileNotFoundError(f"Missing {ENV_EXAMPLE}")
    shutil.copy(ENV_EXAMPLE, ENV_PATH)
    print(f"Created {ENV_PATH} from env.example. Fill in your credentials and rerun.")


def load_env() -> None:
    ensure_env_file()
    load_dotenv(ENV_PATH, override=True)


def mask(value: str | None) -> str:
    if not value:
        return "(missing)"
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}...{value[-3:]}"


def check_env() -> int:
    load_env()
    print("Convo X Spaces setup check")
    print(f"Env file: {ENV_PATH}")
    print()

    missing = []
    for key in REQUIRED_FOR_ROAMING:
        value = os.getenv(key)
        status = "ok" if value and "your_" not in value else "missing"
        print(f"  {key}: {status} ({mask(value)})")
        if status == "missing":
            missing.append(key)

    bearer = os.getenv("X_API_BEARER_TOKEN") or os.getenv("X_BEARER_TOKEN")
    bearer_status = "ok" if bearer and "your_" not in bearer else "optional"
    print(f"  X bearer token: {bearer_status} ({mask(bearer)})")
    if bearer_status == "optional":
        print("    Needed for automatic space discovery via the X API.")

    for key in OPTIONAL_API:
        value = os.getenv(key)
        status = "ok" if value and "your_" not in value else "optional"
        label = key
        if key == "X_API_KEY":
            label = "X_API_KEY (OAuth 1.0 Consumer Key)"
        elif key == "X_API_SECRET":
            label = "X_API_SECRET (OAuth 1.0 Consumer Secret)"
        elif key == "X_ACCESS_TOKEN":
            label = "X_ACCESS_TOKEN (OAuth 1.0 Access Token)"
        elif key == "X_ACCESS_TOKEN_SECRET":
            label = "X_ACCESS_TOKEN_SECRET (OAuth 1.0 Access Token Secret)"
        print(f"  {label}: {status} ({mask(value)})")

    print()
    print("OAuth 1.0 note: Consumer Key/Secret are optional for Convo today.")
    print("Joining Spaces still uses browser login: X_USERNAME + X_PASSWORD.")
    if missing:
        print("Missing required X login credentials:")
        for key in missing:
            print(f"  - {key}")
        print()
        print("Create an X account at https://x.com/signup, then add:")
        print("  X_USERNAME=your_handle_or_email")
        print("  X_PASSWORD=your_password")
        print()
        print("For roaming into Spaces automatically, also add an X developer bearer token.")
        return 1

    print("X login credentials look configured.")
    print("Next steps:")
    print("  python scripts/setup_x_spaces.py login")
    print("  python -m src.convo_backend.app --device default --roam")
    return 0


async def test_login(headless: bool) -> int:
    load_env()
    for key in REQUIRED_FOR_ROAMING:
        value = os.getenv(key)
        if not value or "your_" in value:
            print(f"Set {key} in .env before testing login.")
            return 1

    from convo_backend.services.x_roaming import ConvoRoamer

    roamer = ConvoRoamer()
    try:
        if headless:
            print("Starting headless Chrome session...")
        else:
            print("Starting Chrome session (non-headless)...")
        await roamer.start()
        await roamer.login_to_x()
        print("Login succeeded. Your X account is ready for Spaces roaming.")
        return 0
    except Exception as exc:
        print(f"Login failed: {exc}")
        print()
        print("Common fixes:")
        print("  - Use your email/phone in X_USERNAME if your handle fails")
        print("  - Disable 2FA temporarily or complete verification manually in the browser")
        print("  - Confirm Chrome is installed")
        return 1
    finally:
        await roamer.stop()


async def join_space(space: str, headless: bool, ask_to_speak: bool) -> int:
    load_env()
    for key in REQUIRED_FOR_ROAMING:
        value = os.getenv(key)
        if not value or "your_" in value:
            print(f"Set {key} in .env before joining a Space.")
            return 1

    space_id = space.rstrip("/").split("/")[-1]
    from convo_backend.services.x_roaming import ConvoRoamer

    roamer = ConvoRoamer(desired_spaces=[space_id])
    try:
        await roamer.start()
        await roamer.login_to_x()
        joined = await roamer.join_space(space_id, auto_ask_to_speak=ask_to_speak)
        if joined:
            print(f"Joined Space {space_id} successfully.")
            if ask_to_speak:
                print("Requested speaker access. Host approval may be required.")
            print("Press Enter to leave the Space and close the browser...")
            await asyncio.to_thread(input)
            await roamer.leave_space()
            return 0
        print("Joined Space but could not get speaker access.")
        return 1
    except Exception as exc:
        print(f"Failed to join Space: {exc}")
        return 1
    finally:
        await roamer.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Configure X account for Convo Spaces")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="Validate .env X credentials")

    login_parser = sub.add_parser("login", help="Test X login in Chrome")
    login_parser.add_argument("--headless", action="store_true")

    join_parser = sub.add_parser("join", help="Log in and join a specific Space")
    join_parser.add_argument(
        "--space",
        required=True,
        help="Space URL or ID, e.g. https://x.com/i/spaces/1YqKDqXqXqXGX",
    )
    join_parser.add_argument("--headless", action="store_true")
    join_parser.add_argument(
        "--listen-only",
        action="store_true",
        help="Join as listener only (do not request to speak)",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sys.path.insert(0, str(ROOT / "src"))

    if args.command == "check":
        return check_env()
    if args.command == "login":
        return asyncio.run(test_login(headless=args.headless))
    if args.command == "join":
        return asyncio.run(
            join_space(
                space=args.space,
                headless=args.headless,
                ask_to_speak=not args.listen_only,
            )
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
