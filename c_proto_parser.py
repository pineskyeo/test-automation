#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ParsedParam:
    raw: str
    type_str: str
    name: str


@dataclass
class ParsedPrototype:
    ret_type: str
    name: str
    params: List[ParsedParam]


_CONTROL_KEYWORDS = {"if", "for", "while", "switch", "return", "do", "sizeof"}
_DECL_PREFIX_SKIP = ("typedef", "struct", "enum", "union")


def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*?$", "", text, flags=re.M)
    return text


def strip_preprocessor_blocks(text: str) -> str:
    lines: List[str] = []
    skipping = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if skipping:
            if stripped.endswith("\\"):
                continue
            skipping = False
            continue

        if stripped.startswith("#"):
            skipping = stripped.endswith("\\")
            continue

        lines.append(line)
    return "\n".join(lines)


def _find_matching(text: str, start: int, open_ch: str, close_ch: str) -> int:
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return -1


def _split_top_level_params(param_text: str) -> List[str]:
    parts: List[str] = []
    buf: List[str] = []
    depth = 0
    for ch in param_text:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
        else:
            buf.append(ch)

    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _split_top_level_declarations(text: str) -> List[str]:
    chunks: List[str] = []
    buf: List[str] = []
    paren_depth = 0
    brace_depth = 0

    for ch in text:
        if ch == "{":
            if brace_depth == 0:
                buf = []
            brace_depth += 1
            continue
        if ch == "}":
            if brace_depth > 0:
                brace_depth -= 1
            if brace_depth == 0:
                buf = []
            continue

        if brace_depth > 0:
            continue

        if ch == "(":
            paren_depth += 1
        elif ch == ")" and paren_depth > 0:
            paren_depth -= 1

        buf.append(ch)

        if ch == ";" and paren_depth == 0:
            chunk = collapse_ws("".join(buf))
            if chunk:
                chunks.append(chunk)
            buf = []

    return chunks


def _parse_param(raw_param: str) -> Optional[ParsedParam]:
    s = collapse_ws(raw_param)
    if not s or s == "void":
        return None

    if "..." in s:
        return ParsedParam(raw=s, type_str="...", name="...")

    if re.search(r"\(\s*\*\s*[A-Za-z_]\w*\s*\)", s):
        return ParsedParam(raw=s, type_str="FUNC_PTR", name="FUNC_PTR")

    m = re.match(r"^(?P<type>.+?)(?P<name>[A-Za-z_]\w*)$", s)
    if not m:
        return ParsedParam(raw=s, type_str=s, name="")

    return ParsedParam(
        raw=s,
        type_str=collapse_ws(m.group("type").rstrip()),
        name=m.group("name").strip(),
    )


def _normalize_for_parse(header_text: str) -> str:
    text = strip_comments(header_text)
    text = strip_preprocessor_blocks(text)
    text = text.replace('extern "C" {', "")
    text = text.replace('extern \"C\" {', "")
    text = text.replace('extern "C"', "")
    return text


def _is_non_function_decl(chunk: str) -> bool:
    lowered = chunk.lstrip().lower()
    return any(lowered.startswith(prefix + " ") for prefix in _DECL_PREFIX_SKIP)


def _parse_prototype_from_chunk(chunk: str) -> Optional[ParsedPrototype]:
    if not chunk.endswith(";"):
        return None
    if _is_non_function_decl(chunk):
        return None
    if "(" not in chunk or ")" not in chunk:
        return None

    lpar = chunk.find("(")
    rpar = _find_matching(chunk, lpar, "(", ")")
    if rpar < 0:
        return None

    prefix = collapse_ws(chunk[:lpar])
    if not prefix or "=" in prefix:
        return None

    # Skip function-pointer declarations like: int (*fp)(void);
    if re.search(r"\(\s*\*", prefix):
        return None

    name_match = re.search(r"([A-Za-z_]\w*)$", prefix)
    if not name_match:
        return None

    fn_name = name_match.group(1)
    if fn_name in _CONTROL_KEYWORDS:
        return None

    ret_type = collapse_ws(prefix[:name_match.start()])
    if not ret_type:
        return None

    suffix = collapse_ws(chunk[rpar + 1:-1])
    if "{" in suffix or "}" in suffix or "=" in suffix:
        return None

    params_raw = collapse_ws(chunk[lpar + 1:rpar])
    params: List[ParsedParam] = []
    if params_raw and params_raw != "void":
        parsed = [_parse_param(p) for p in _split_top_level_params(params_raw)]
        if any(p and p.type_str in ("...", "FUNC_PTR") for p in parsed):
            return None
        params = [p for p in parsed if p is not None]

    return ParsedPrototype(ret_type=ret_type, name=fn_name, params=params)


def parse_header_prototypes(header_text: str) -> List[ParsedPrototype]:
    text = _normalize_for_parse(header_text)
    chunks = _split_top_level_declarations(text)

    out: List[ParsedPrototype] = []
    seen = set()
    for chunk in chunks:
        proto = _parse_prototype_from_chunk(chunk)
        if not proto:
            continue
        key = (collapse_ws(proto.ret_type), proto.name, tuple(collapse_ws(p.raw) for p in proto.params))
        if key in seen:
            continue
        seen.add(key)
        out.append(proto)

    return out
