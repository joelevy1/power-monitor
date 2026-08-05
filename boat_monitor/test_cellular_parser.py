"""
Pure-Python unit test for cellular.py's parsing functions -- no
MicroPython/hardware dependency (cellular.py defers its machine/config
imports into Sim7600Modem.__init__ specifically so this stays importable
here). Run directly with:

    python3 boat_monitor/test_cellular_parser.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cellular import (  # noqa: E402
    CellularError,
    extract_location,
    one_line,
    parse_http_action,
    parse_http_read,
)


def run():
    failures = []

    def check(name, condition):
        status = "PASS" if condition else "FAIL"
        print("[%s] %s" % (status, name))
        if not condition:
            failures.append(name)

    # one_line(): collapse a multi-line AT response into one diagnostic line.
    check("one_line strips OK", one_line("\r\nOK\r\n") == "(none)")
    check(
        "one_line keeps real content",
        one_line("\r\n+CREG: 0,1\r\n\r\nOK\r\n") == "+CREG: 0,1",
    )
    check(
        "one_line joins multiple real lines",
        one_line("+CSQ: 15,99\r\nOK\r\n\r\n+CREG: 0,5\r\n") == "+CSQ: 15,99 | +CREG: 0,5",
    )
    check("one_line handles empty", one_line("") == "(none)")

    # parse_http_action(): "+HTTPACTION: <method>,<status>,<datalen>"
    status, length = parse_http_action("\r\n+HTTPACTION: 0,200,1234\r\n\r\nOK\r\n")
    check("http_action GET 200 status", status == 200)
    check("http_action GET 200 length", length == 1234)

    status2, length2 = parse_http_action("+HTTPACTION: 1,404,9\r\n")
    check("http_action POST 404 status", status2 == 404)
    check("http_action POST 404 length", length2 == 9)

    try:
        parse_http_action("garbage, no marker here")
        check("http_action missing marker raises", False)
    except CellularError:
        check("http_action missing marker raises", True)

    try:
        parse_http_action("+HTTPACTION: 0,200")  # missing datalen field
        check("http_action too few fields raises", False)
    except CellularError:
        check("http_action too few fields raises", True)

    # parse_http_read(): "+HTTPREAD: DATA,<n>\r\n<n bytes>" -- observed
    # on-device format, one chunk per ~1024 bytes for large responses.

    # Single chunk (small response, fits in one).
    small_body = '{"ok": true}'
    body = parse_http_read("OK\r\n\r\n+HTTPREAD: DATA,%d\r\n%s\r\nOK\r\n" % (len(small_body), small_body))
    check("http_read single chunk extracts body", body == small_body)

    # Multiple chunks, boundary falling in the middle of a word -- this is
    # exactly the shape that corrupted real data the first time this ran:
    # a naive parser that only strips the FIRST marker leaves the SECOND
    # chunk's "+HTTPREAD: DATA,15" header embedded as literal garbage
    # instead of stripping it too.
    chunk1 = '{"device": "boat-p2", "mode": "dock'
    chunk2 = 'ed_off", "fw": "0.6.0"}'
    raw = (
        "OK\r\n\r\n+HTTPREAD: DATA,%d\r\n%s+HTTPREAD: DATA,%d\r\n%s\r\nOK\r\n"
        % (len(chunk1), chunk1, len(chunk2), chunk2)
    )
    body2 = parse_http_read(raw)
    check("http_read multi-chunk reassembles losslessly", body2 == chunk1 + chunk2)
    check("http_read multi-chunk is valid JSON", body2.startswith('{"device"'))

    # Three chunks, for good measure -- not just the two-chunk case.
    parts = ["abc", "defgh", "ij"]
    raw3 = "".join("+HTTPREAD: DATA,%d\r\n%s" % (len(p), p) for p in parts) + "\r\nOK\r\n"
    body3 = parse_http_read(raw3)
    check("http_read three chunks reassembles", body3 == "".join(parts))

    try:
        parse_http_read("no marker at all")
        check("http_read missing marker raises", False)
    except CellularError:
        check("http_read missing marker raises", True)

    # expected_length validation: catches a dropped/short chunk instead of
    # silently returning truncated data -- this is what happened on real
    # hardware the second time (AT+HTTPACTION declared 3393 bytes, only
    # 2369 came back, with no error at all before this check existed).
    raw_two_chunks = "".join("+HTTPREAD: DATA,%d\r\n%s" % (len(p), p) for p in parts) + "\r\nOK\r\n"
    try:
        parse_http_read(raw_two_chunks, expected_length=999, debug=False)
        check("http_read length mismatch raises", False)
    except CellularError as exc:
        check("http_read length mismatch raises", "999" in str(exc))

    ok_body = parse_http_read(raw_two_chunks, expected_length=len("".join(parts)), debug=False)
    check("http_read correct expected_length passes", ok_body == "".join(parts))

    # Multi-byte UTF-8 character straddling a chunk boundary -- this is
    # the REAL bug found on real hardware fetching config.py: its header
    # comment contains an em dash ("\u2014", 3 bytes/1 character), which
    # shrinks the decoded string 2 characters shorter than its declared
    # byte count. Slicing an already-decoded string by byte-length
    # offsets (the previous implementation) corrupted every subsequent
    # chunk boundary the moment such a character appeared before one.
    # parse_http_read() now operates on bytes throughout and decodes only
    # once at the end, specifically to avoid this.
    em_dash_chunk1 = ("x" * 20 + "\u2014" + "y" * 5).encode("utf-8")  # 3-byte char mid-chunk
    em_dash_chunk2 = b"tail content after the boundary"
    raw_utf8 = (
        b"OK\r\n\r\n+HTTPREAD: DATA,%d\r\n%s+HTTPREAD: DATA,%d\r\n%s\r\n+HTTPREAD: 0\r\n\r\nOK\r\n"
        % (len(em_dash_chunk1), em_dash_chunk1, len(em_dash_chunk2), em_dash_chunk2)
    )
    expected_text = (em_dash_chunk1 + em_dash_chunk2).decode("utf-8")
    body_utf8 = parse_http_read(
        raw_utf8, expected_length=len(em_dash_chunk1) + len(em_dash_chunk2), debug=False
    )
    check("http_read handles multi-byte UTF-8 straddling a chunk boundary", body_utf8 == expected_text)

    # And the actual real file that triggered this on hardware, split the
    # same way (1024/426 bytes) it actually arrived.
    config_path = Path(__file__).resolve().parent / "config.py"
    if config_path.is_file():
        with open(config_path, "rb") as f:
            real_config_bytes = f.read()
        real_chunks = [real_config_bytes[i : i + 1024] for i in range(0, len(real_config_bytes), 1024)]
        real_raw = b"OK\r\n\r\n"
        for c in real_chunks:
            real_raw += b"+HTTPREAD: DATA,%d\r\n" % len(c) + c
        real_raw += b"\r\n+HTTPREAD: 0\r\n\r\nOK\r\n"
        real_recovered = parse_http_read(
            real_raw, expected_length=len(real_config_bytes), debug=False
        )
        check(
            "http_read reassembles the real config.py byte-for-byte",
            real_recovered == real_config_bytes.decode("utf-8"),
        )

    # extract_location(): pulls "Location:" out of AT+HTTPHEAD's raw header
    # block. This is the mechanism that made Google Apps Script POSTs work
    # over cellular -- script.google.com/.../exec always answers with a
    # 302 to a script.googleusercontent.com URL carrying the real
    # response, confirmed on real hardware (AT+HTTPACTION returned
    # "1,302,0" -- zero-length body, nothing for AT+HTTPREAD to read).
    head = (
        "HTTP/1.1 302 Found\r\n"
        "Location: https://script.googleusercontent.com/macros/echo?user_content_key=abc\r\n"
        "Content-Length: 0\r\n"
    )
    check(
        "extract_location finds Location header",
        extract_location(head)
        == "https://script.googleusercontent.com/macros/echo?user_content_key=abc",
    )
    check(
        "extract_location is case-insensitive",
        extract_location(head.replace("Location:", "location:")) is not None,
    )
    check("extract_location returns None with no Location header", extract_location("HTTP/1.1 200 OK\r\n") is None)
    check(
        "extract_location works on bytes input",
        extract_location(head.encode("utf-8"))
        == "https://script.googleusercontent.com/macros/echo?user_content_key=abc",
    )

    print()
    if failures:
        print("FAILED: %d check(s): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
