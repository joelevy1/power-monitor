#!/usr/bin/env python3
"""Verify that the deployed Apps Script /exec endpoint returns direct JSON."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request

from sheets_log import DEFAULT_APPS_SCRIPT_URL


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe(url, timeout_s=30):
    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(url, method="GET")
    try:
        response = opener.open(request, timeout=timeout_s)
    except urllib.error.HTTPError as exc:
        response = exc
    body_text = response.read().decode("utf-8", "replace")
    try:
        body = json.loads(body_text)
    except ValueError:
        body = None
    status = int(response.getcode())
    location = response.headers.get("Location", "")
    result = {
        "ok": status == 200
        and not location
        and isinstance(body, dict)
        and int(body.get("receiver_version") or 0) >= 7,
        "status": status,
        "location": location,
        "content_type": response.headers.get("Content-Type", ""),
        "receiver_version": body.get("receiver_version") if isinstance(body, dict) else None,
        "json_body": isinstance(body, dict),
    }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args(argv)
    url = args.url or DEFAULT_APPS_SCRIPT_URL
    result = probe(url, args.timeout)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
