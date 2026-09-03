#!/usr/bin/env python3
"""Shared function-stripping helpers for permuter base construction."""
import re


def find_fn_defs(lines):
    """Yield (header_start, header_end_line, brace_line, brace_col, name) for
    each function definition; header_end_line is the line ending in ')'."""
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if ("(" in stripped and "=" not in stripped
                and not stripped.startswith("#")
                and not stripped.startswith("/")
                and not stripped.startswith("*")):
            depth = 0
            j = i
            last_paren_line = None
            while j < n:
                for ch in lines[j]:
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                if depth == 0:
                    last_paren_line = j
                    break
                j += 1
            if last_paren_line is not None:
                if lines[last_paren_line].rstrip().endswith("{"):
                    brace_line, brace_col = last_paren_line, \
                        lines[last_paren_line].rindex("{")
                elif last_paren_line + 1 < n and \
                        lines[last_paren_line + 1].strip() == "{":
                    brace_line, brace_col = last_paren_line + 1, 0
                else:
                    brace_line = None
                if brace_line is not None:
                    header = "".join(lines[i:last_paren_line + 1])
                    m = re.search(r"(\w+)\s*\(", header)
                    name = m.group(1) if m else None
                    if name and not name.startswith(("if", "for", "while",
                                                     "switch", "return")):
                        yield i, last_paren_line, brace_line, brace_col, name
                        i = brace_line
        i += 1


def brace_end(lines, brace_line, brace_col):
    """Find the line where the function body's braces balance.

    Braces inside string/char literals are ignored, and Shift-JIS lead
    bytes consume their trail byte (which may be an ASCII brace or quote).
    """
    def is_sjis_lead(ch):
        return 0x81 <= ord(ch) <= 0x9F or 0xE0 <= ord(ch) <= 0xEF

    level = 0
    started = False
    in_str = False
    in_chr = False
    escape = False
    prev_lead = False
    for j in range(brace_line, len(lines)):
        row = lines[j]
        k = brace_col if j == brace_line else 0
        while k < len(row):
            ch = row[k]
            if prev_lead:
                prev_lead = False
            elif escape:
                escape = False
            elif in_str:
                if ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                elif is_sjis_lead(ch):
                    prev_lead = True
            elif in_chr:
                if ch == "\\":
                    escape = True
                elif ch == "'":
                    in_chr = False
            elif ch == '"':
                in_str = True
            elif ch == "'":
                in_chr = True
            elif is_sjis_lead(ch):
                prev_lead = True
            elif ch == "{":
                level += 1
                started = True
            elif ch == "}":
                level -= 1
                if started and level == 0:
                    return j
            k += 1
    return None
