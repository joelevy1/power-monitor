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

from cellular import CellularError, one_line, parse_http_action, parse_http_read  # noqa: E402


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

    print()
    if failures:
        print("FAILED: %d check(s): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
