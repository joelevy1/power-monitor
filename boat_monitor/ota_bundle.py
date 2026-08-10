"""
Single-file OTA payload: BMOTA v1 archive (length-prefixed UTF-8 paths + raw bytes).

Built on the PC by build_ota_bundle.py; extracted on the Pico after one HTTP GET.
Avoids ~30 separate SIM7600 HTTP sessions per upgrade on cellular.
"""

import struct

MAGIC = b"BMOTA\x01"
_END = struct.pack("<H", 0)


class OtaBundleError(Exception):
    pass


def _pack_record(path, data):
    if isinstance(path, str):
        path_b = path.encode("utf-8")
    else:
        path_b = path
    if len(path_b) > 65535:
        raise OtaBundleError("path too long: %s" % path)
    if isinstance(data, str):
        data = data.encode("utf-8")
    return struct.pack("<H", len(path_b)) + path_b + struct.pack("<I", len(data)) + data


def build_bytes(file_items):
    """file_items: iterable of (path, data_bytes)."""
    out = bytearray(MAGIC)
    for path, data in file_items:
        out += _pack_record(path, data)
    out += _END
    return bytes(out)


def iter_records(blob):
    if not blob.startswith(MAGIC):
        raise OtaBundleError("bad magic")
    pos = len(MAGIC)
    n = len(blob)
    while pos + 2 <= n:
        (path_len,) = struct.unpack_from("<H", blob, pos)
        pos += 2
        if path_len == 0:
            return
        if pos + path_len + 4 > n:
            raise OtaBundleError("truncated path")
        path = blob[pos : pos + path_len].decode("utf-8")
        pos += path_len
        (data_len,) = struct.unpack_from("<I", blob, pos)
        pos += 4
        if pos + data_len > n:
            raise OtaBundleError("truncated data for %s" % path)
        data = blob[pos : pos + data_len]
        pos += data_len
        yield path, data
    raise OtaBundleError("missing end marker")


def extract_to_files(blob, write_fn):
    """write_fn(path, text) called for each member (same contract as ota.write_file)."""
    count = 0
    for path, data in iter_records(blob):
        try:
            text = data.decode("utf-8")
        except Exception as exc:
            raise OtaBundleError("utf-8 decode failed for %s: %s" % (path, exc))
        write_fn(path, text)
        count += 1
    if count == 0:
        raise OtaBundleError("empty bundle")
    return count


def _read_exact(f, n):
    buf = b""
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            raise OtaBundleError("unexpected EOF")
        buf += chunk
    return buf


def extract_from_file(bundle_path, write_fn):
    """Extract one member at a time from disk (no full-bundle RAM buffer)."""
    count = 0
    with open(bundle_path, "rb") as f:
        magic = f.read(len(MAGIC))
        if magic != MAGIC:
            raise OtaBundleError("bad magic")
        while True:
            plen = _read_exact(f, 2)
            (path_len,) = struct.unpack("<H", plen)
            if path_len == 0:
                if count == 0:
                    raise OtaBundleError("empty bundle")
                return count
            path = _read_exact(f, path_len).decode("utf-8")
            (data_len,) = struct.unpack("<I", _read_exact(f, 4))
            data = _read_exact(f, data_len)
            try:
                text = data.decode("utf-8")
            except Exception as exc:
                raise OtaBundleError("utf-8 decode failed for %s: %s" % (path, exc))
            write_fn(path, text)
            count += 1
            data = None
            try:
                import gc

                gc.collect()
            except Exception:
                pass
