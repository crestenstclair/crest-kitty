#!/usr/bin/env python3
"""Interaction driver fixture (port of runtime-interaction-driver.mjs).

Reads exactly one JSON request document on stdin and replies with one JSON
evidence document on stdout. ``request.payload.mode`` selects the behavior:
``pass`` (default), ``wrong-session``, ``assertion-failed``, ``miss-seam``,
``not-attempted``, ``before-window``.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def main() -> int:
    request = json.loads(sys.stdin.read())
    payload = request.get("request") or {}
    mode = payload.get("mode", "pass")
    delivered = 0 if mode == "before-window" else int(time.time() * 1000) - request["sessionStartedAtEpochMs"]
    if mode != "miss-seam" and payload.get("seamPath"):
        Path(payload["seamPath"]).write_text(
            json.dumps({"action": payload.get("action", "mapped-input")}), encoding="utf-8"
        )
    evidence = {
        "sessionId": "another-session" if mode == "wrong-session" else request["sessionId"],
        "actionId": request["actionId"],
        "attempted": mode != "not-attempted",
        "reachedSeam": mode != "miss-seam",
        "deliveredAtMs": max(0, delivered),
        "assertions": [
            {
                "id": "isolation-preserved",
                "passed": mode != "assertion-failed",
                "expected": "autonomous-flow-continues",
                "observed": "state-overwritten" if mode == "assertion-failed" else "autonomous-flow-continues",
            }
        ],
        "details": {"kind": "fixture-production-seam", "mode": mode},
    }
    print(json.dumps(evidence), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
