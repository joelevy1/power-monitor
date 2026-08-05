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

    # parse_http_read(): "+HTTPREAD: <len>\r\n<data>\r\nOK\r\n"
    body = parse_http_read('+HTTPREAD: 13\r\n{"ok": true}\n\r\nOK\r\n')
    check("http_read extracts body", body.strip() == '{"ok": true}')

    body2 = parse_http_read("+HTTPREAD: 9\r\nNot Found\r\nOK\r\n")
    check("http_read extracts non-JSON body", body2.strip() == "Not Found")

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
