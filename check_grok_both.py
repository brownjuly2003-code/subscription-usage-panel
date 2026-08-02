#!/usr/bin/env python3
"""Check BOTH Grok panel profiles (personal + work). Exit 1 if any need login."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from panel.providers import grok as g

PROFILES = [
    {
        "label": "GROK/personal",
        "home": Path.home() / ".grok",
        "expect_email": "uedomskikh@gmail.com",
    },
    {
        "label": "GROK/work",
        "home": Path.home() / ".grok-work",
        "expect_email": "russelllovedirty@juniorr.us",
    },
]


def main() -> int:
    os.environ.pop("PANEL_GROK_OIDC_REFRESH", None)
    print()
    print("GROK x2 — BOTH panel profiles")
    print("=" * 72)
    bad: list[str] = []
    with httpx.Client(timeout=20.0) as client:
        for p in PROFILES:
            home: Path = p["home"]
            label = p["label"]
            expect = p["expect_email"]
            auth = home / "auth.json"
            k, e, exp, team, rt = g._read_auth(home)
            print(f"\n{label}")
            print(f"  home:          {home}")
            print(f"  auth.json:     {'YES' if auth.is_file() else 'MISSING'}")
            print(f"  email:         {e or '(none)'}  (expect {expect})")
            print(f"  access token:  {'yes' if k else 'NO'}")
            print(f"  refresh_token: {'yes' if rt else 'NO'}")
            if exp:
                print(f"  token left:    {round((exp - time.time()) / 60, 1)} min")
            else:
                print("  token left:    n/a")

            if auth.is_file() and rt:
                ok, detail = g._refresh_oidc(home, client, 12.0)
                print(f"  refresh:       {'OK' if ok else 'FAIL'} ({detail})")
                refresh_ok = ok
            else:
                print("  refresh:       N/A (no auth)")
                refresh_ok = False

            res = g.fetch_grok(label, label, home, client, 15.0)
            rem = [round(w.rem_pct, 1) for w in res.windows]
            print(f"  panel:         {res.status.value}  rem%={rem}  {res.reason or ''}")

            email_ok = (not e) or e.lower() == expect.lower() or res.status.value == "live"
            good = (
                res.status.value == "live"
                and bool(k)
                and bool(rt)
                and refresh_ok
            )
            # work/personal email match soft: warn only
            if e and e.lower() != expect.lower():
                print(f"  WARN: email mismatch (got {e})")
            print(f"  RESULT:        {'OK' if good else 'NEED LOGIN'}")
            if not good:
                bad.append(label)

    print()
    print("=" * 72)
    if not bad:
        print("BOTH OK — nothing to do.")
        return 0
    print("NEED LOGIN: " + ", ".join(bad))
    print("Run: Heal-Grok-Both.bat  (logs in only broken homes)")
    print("  personal home = %USERPROFILE%\\.grok")
    print("  work home     = %USERPROFILE%\\.grok-work")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
