from __future__ import annotations

import argparse
from pathlib import Path

from property_workflow.collectors.aplus_desktop import load_aplus_cookies


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe Beike A+ desktop session cookies")
    parser.add_argument(
        "--cookie-db",
        default=str(Path.home() / "AppData/Roaming/A+/Cookies"),
        help="Path to A+ Chromium cookie DB",
    )
    parser.add_argument(
        "--local-state",
        default=str(Path.home() / "AppData/Roaming/A+/Local State"),
        help="Path to A+ Local State file",
    )
    parser.add_argument(
        "--domains",
        nargs="*",
        default=[".ke.com", ".lianjia.com", "app.a.ke.com", "saas.a.ke.com"],
        help="Cookie domain suffix filters",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    cookies = load_aplus_cookies(
        cookie_db_path=Path(args.cookie_db),
        local_state_path=Path(args.local_state),
        cookie_domains=args.domains,
    )
    names = sorted(cookies.keys())
    print(f"[aplus-probe] valid cookies: {len(names)}")
    for name in names:
        print(f"- {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
