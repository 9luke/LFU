#!/usr/bin/env python3
"""
Goes through every .txt file in the same directory as this script and removes
`add_core_of = WST`, unless `owner = WST` is in the SAME { } block as it.

Example (the core IS removed, because owner = WST is in a different block):

    history = {
        owner = CHI
        add_core_of = WST        <- removed
        1936.1.1 = {
            owner = WST          <- different block, doesn't protect it
        }
    }

- If the statement is alone on its line, the whole line is removed.
- If it shares a line with other statements, only that statement is removed.
- # comments (and "quoted strings") are ignored when matching.

Files are handled as bytes (no decoding), so encodings, BOMs and line endings
(LF / CRLF / CR) are preserved. Files are only rewritten if something changed,
and writes are atomic (temp file + replace).
"""

import os
import re
import shutil
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BOM = b"\xef\xbb\xbf"

TOKENS = re.compile(
    rb"(?P<comment>\#[^\r\n]*)"
    rb'|(?P<string>"[^"\r\n]*")'
    rb"|(?P<open>\{)"
    rb"|(?P<close>\})"
    rb"|(?P<owner>(?<![A-Za-z0-9_])owner[ \t]*=[ \t]*WST(?![A-Za-z0-9_]))"
    rb"|(?P<core>(?<![A-Za-z0-9_])add_core_of[ \t]*=[ \t]*WST(?![A-Za-z0-9_])[ \t]*)"
)
EOL = re.compile(rb"(\r\n|\n|\r)$")


def find_spans_to_remove(data):
    """Return list of (start, end) byte spans of add_core_of = WST to remove."""
    next_id = 1
    stack = [0]            # block ids; 0 = top level
    owner_blocks = set()   # blocks containing owner = WST
    cores = []             # (start, end, block_id)

    for m in TOKENS.finditer(data):
        kind = m.lastgroup
        if kind == "open":
            stack.append(next_id)
            next_id += 1
        elif kind == "close":
            if len(stack) > 1:
                stack.pop()
        elif kind == "owner":
            owner_blocks.add(stack[-1])
        elif kind == "core":
            cores.append((m.start(), m.end(), stack[-1]))

    return [(s, e) for s, e, b in cores if b not in owner_blocks]


def clean_data(data):
    spans = find_spans_to_remove(data)
    if not spans:
        return data, 0

    out = []
    pos = 0
    for line in data.splitlines(keepends=True):
        start, end = pos, pos + len(line)
        pos = end
        mine = [(s - start, e - start) for s, e in spans if start <= s < end]
        if not mine:
            out.append(line)
            continue

        m = EOL.search(line)
        eol = m.group(1) if m else b""
        body = line[: len(line) - len(eol)]

        # Cut the spans out (right to left so offsets stay valid).
        for s, e in sorted(mine, reverse=True):
            body = body[:s] + body[e:]

        # Is anything left besides whitespace / BOM / a comment?
        ci = body.find(b"#")
        code, comment = (body, b"") if ci == -1 else (body[:ci], body[ci:])
        if not code.replace(BOM, b"").strip():
            # Statement was alone on its line -> drop the line.
            # (A trailing comment on that line goes with it.)
            if code.startswith(BOM) and not out:
                out.append(BOM)
            continue

        if comment:
            out.append(code.rstrip(b" \t") + b" " + comment + eol)
        else:
            out.append(code.rstrip(b" \t") + eol)

    return b"".join(out), len(spans)


def process_file(path):
    with open(path, "rb") as f:
        data = f.read()

    new_data, count = clean_data(data)
    if count == 0 or new_data == data:
        return "unchanged", 0

    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(new_data)
        try:
            shutil.copymode(path, tmp_path)
        except OSError:
            pass
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    return "modified", count


def main():
    txt_files = sorted(
        n for n in os.listdir(SCRIPT_DIR)
        if n.lower().endswith(".txt") and os.path.isfile(os.path.join(SCRIPT_DIR, n))
    )
    if not txt_files:
        print("No .txt files found in", SCRIPT_DIR)
        return 0

    total = 0
    for name in txt_files:
        try:
            status, count = process_file(os.path.join(SCRIPT_DIR, name))
        except OSError as e:
            print(f"[error]   {name}: {e}", file=sys.stderr)
            continue
        total += count
        if status == "modified":
            print(f"[removed] {name}: {count} occurrence(s)")

    print(f"Done. Scanned {len(txt_files)} file(s), removed {total} occurrence(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
