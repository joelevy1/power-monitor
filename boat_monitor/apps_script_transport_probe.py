#!/usr/bin/env python3
"""Report whether Apps Script returns direct JSON or its required redirect."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from sheets_log import DEFAULT_APPS_SCRIPT_URL


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe(url, timeout_s=30):
    separator = "&" if "?" in url else "?"
    probe_url = "%s%stransport_probe=%d" % (url, separator, int(time.time()))
    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(probe_url, method="GET")
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
    direct_json = status == 200 and not location and isinstance(body, dict)
    followed_body = body
    followed_status = status
    if location:
        followed_response = urllib.request.urlopen(probe_url, timeout=timeout_s)
        followed_status = int(followed_response.getcode())
        try:
            followed_body = json.loads(
                followed_response.read().decode("utf-8", "replace")
            )
        except ValueError:
            followed_body = None
    receiver_version = (
        followed_body.get("receiver_version")
        if isinstance(followed_body, dict)
        else None
    )
    trusted_redirect = (
        status in (301, 302, 303)
        and urllib.parse.urlsplit(location).hostname == "script.googleusercontent.com"
    )
    usable = (
        (direct_json or trusted_redirect)
        and followed_status == 200
        and isinstance(followed_body, dict)
        and int(receiver_version or 0) >= 6
    )
    result = {
        "ok": usable,
        "direct_json": direct_json,
        "status": status,
        "redirect_host": urllib.parse.urlsplit(location).hostname or "",
        "content_type": response.headers.get("Content-Type", ""),
        "followed_status": followed_status,
        "receiver_version": receiver_version,
        "json_body": isinstance(followed_body, dict),
    }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--require-direct", action="store_true")
    args = parser.parse_args(argv)
    url = args.url or DEFAULT_APPS_SCRIPT_URL
    result = probe(url, args.timeout)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] and (result["direct_json"] or not args.require_direct) else 1


if __name__ == "__main__":
    raise SystemExit(main())
