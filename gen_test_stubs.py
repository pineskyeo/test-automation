#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
summary: Generate C stub files from header prototypes using TEST_TOOLS_H macros
function: Scan header files, parse function prototypes, classify stub tags, and emit *_stub.h / *_stub.c
file: gen_test_stubs.py
tags: [stub, generator, test, cmocka, c, headers, cortex]
inputs:
  - header file or directory path
  - output directory
  - include root
  - test tools header path
returns:
  - generated *_stub.h and *_stub.c files
errors:
  - skips unsupported/variadic/function-pointer prototypes
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple


# =========================================================
# Data models
# =========================================================

@dataclass
class Param:
    raw: str
    type_str: str
    name: str


@dataclass
class FunctionProto:
    ret_type: str
    name: str
    params: List[Param]
    header_path: str


# =========================================================
# Helpers
# =========================================================

C_KEYWORDS = {
    "const", "volatile", "restrict", "signed", "unsigned", "short", "long",
    "struct", "enum", "union", "register", "static", "extern", "inline"
}

SKIP_NAMES = {
    "__attribute__", "__declspec"
}


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*?$", "", text, flags=re.M)
    return text


def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def sanitize_basename(path: str) -> str:
    base = os.path.basename(path)
    base = os.path.splitext(base)[0]
    return base


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def write_file(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def list_header_files(path: str) -> List[str]:
    out = []
    if os.path.isfile(path):
        if path.endswith(".h"):
            out.append(path)
        return out

    for root, _, files in os.walk(path):
        for fn in files:
            if fn.endswith(".h"):
                out.append(os.path.join(root, fn))
    out.sort()
    return out


# =========================================================
# Prototype parsing
# =========================================================

def remove_preprocessor_lines(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def split_top_level_params(param_text: str) -> List[str]:
    parts = []
    buf = []
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


def parse_param(param_raw: str) -> Optional[Param]:
    s = collapse_ws(param_raw)
    if not s or s == "void":
        return None

    if "..." in s:
        return Param(raw=s, type_str="...", name="...")

    # Skip function-pointer parameters
    if re.search(r"\(\s*\*\s*[A-Za-z_]\w*\s*\)", s):
        return Param(raw=s, type_str="FUNC_PTR", name="FUNC_PTR")

    # Common normal case:
    #   "const char *name"
    #   "foo_t** out"
    #   "size_t n"
    m = re.match(r"^(?P<type>.+?)(?P<name>[A-Za-z_]\w*)$", s)
    if not m:
        return Param(raw=s, type_str=s, name="")

    type_part = m.group("type").rstrip()
    name = m.group("name").strip()

    return Param(raw=s, type_str=collapse_ws(type_part), name=name)


def parse_prototypes(text: str, header_path: str) -> List[FunctionProto]:
    text = strip_comments(text)
    text = remove_preprocessor_lines(text)

    # Normalize extern "C" blocks if present
    text = text.replace('extern "C" {', "")
    text = text.replace("extern \"C\" {", "")
    text = text.replace("}", "}\n")

    # Collect statement-like chunks ending with ';'
    chunks = []
    buf = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        buf.append(stripped)
        if ";" in stripped:
            chunks.append(" ".join(buf))
            buf = []

    protos: List[FunctionProto] = []

    for chunk in chunks:
        chunk = collapse_ws(chunk)

        if "(" not in chunk or ")" not in chunk or not chunk.endswith(";"):
            continue

        # Skip typedefs and variables
        if chunk.startswith("typedef "):
            continue
        if re.search(r"\btypedef\b", chunk):
            continue
        if re.search(r"\bextern\b.+\b[A-Za-z_]\w*\s*;", chunk) and "(" not in chunk:
            continue

        # Skip macros disguised as declarations
        if any(name in chunk for name in SKIP_NAMES):
            continue

        # Match: return_type name(args);
        m = re.match(
            r"^(?P<ret>.+?)\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<params>.*)\)\s*;$",
            chunk
        )
        if not m:
            continue

        ret_type = collapse_ws(m.group("ret"))
        name = m.group("name").strip()
        params_raw = m.group("params").strip()

        if name in SKIP_NAMES:
            continue

        params: List[Param] = []
        if params_raw and params_raw != "void":
            raw_parts = split_top_level_params(params_raw)
            parsed_params = [parse_param(p) for p in raw_parts]
            if any(p and (p.type_str in ("...", "FUNC_PTR")) for p in parsed_params):
                continue
            params = [p for p in parsed_params if p is not None]

        protos.append(FunctionProto(
            ret_type=ret_type,
            name=name,
            params=params,
            header_path=header_path
        ))

    return protos


# =========================================================
# Classification
# =========================================================

def normalize_type(t: str) -> str:
    t = collapse_ws(t)
    t = t.replace(" *", "*").replace("* ", "*")
    return t


def is_pointer_type(type_str: str) -> bool:
    return "*" in normalize_type(type_str)


def pointer_depth(type_str: str) -> int:
    return normalize_type(type_str).count("*")


def is_const_char_ptr(type_str: str) -> bool:
    t = normalize_type(type_str)
    return t in ("const char*", "char const*")


def is_status_type(type_str: str) -> bool:
    return normalize_type(type_str) == "status_t"


def is_void_type(type_str: str) -> bool:
    return normalize_type(type_str) == "void"


def is_int_type(type_str: str) -> bool:
    return normalize_type(type_str) == "int"


def is_u32_type(type_str: str) -> bool:
    t = normalize_type(type_str)
    return t in ("uint32_t", "u_int32_t")


def is_u64_type(type_str: str) -> bool:
    t = normalize_type(type_str)
    return t in ("uint64_t", "u_int64_t")


def is_size_type(type_str: str) -> bool:
    return normalize_type(type_str) == "size_t"


def is_uptr_type(type_str: str) -> bool:
    return normalize_type(type_str) == "uintptr_t"


def is_out_param_candidate(p: Param) -> bool:
    # Current TEST_TOOLS_H OUT handling does:
    #   *(void**)out = g_fn_out1;
    # so safe auto-use is only pointer-to-pointer outputs.
    if pointer_depth(p.type_str) < 2:
        return False

    lname = p.name.lower()
    if (
        lname.startswith("out") or
        lname.endswith("_out") or
        "_out_" in lname or
        lname in ("result", "value", "pp", "dst")
    ):
        return True

    # Also allow very common T** patterns even if name is not explicit.
    return True


def classify_tag(fn: FunctionProto) -> Tuple[str, List[str]]:
    ret = normalize_type(fn.ret_type)
    out_candidates = [p.name for p in fn.params if is_out_param_candidate(p)]

    if is_status_type(ret):
        if len(out_candidates) >= 2:
            return "STUB_RET_STATUS_OUT2", out_candidates[:2]
        if len(out_candidates) == 1:
            return "STUB_RET_STATUS_OUT1", out_candidates[:1]
        return "STUB_RET_STATUS", []

    if is_void_type(ret):
        return "STUB_RET_VOID", []

    if is_const_char_ptr(ret):
        return "STUB_RET_CSTR", []

    if is_int_type(ret):
        return "STUB_RET_INT", []

    if is_u32_type(ret):
        return "STUB_RET_U32", []

    if is_u64_type(ret):
        return "STUB_RET_U64", []

    if is_size_type(ret):
        return "STUB_RET_SIZE", []

    if is_uptr_type(ret):
        return "STUB_RET_UPTR", []

    if is_pointer_type(ret):
        return "STUB_RET_PTR", []

    # Fallback: unsupported scalar return type
    return "UNSUPPORTED", []


# =========================================================
# Code emission
# =========================================================

def make_header_guard(stub_header_name: str) -> str:
    g = re.sub(r"[^A-Za-z0-9]", "_", stub_header_name).upper()
    return f"{g}_INCLUDED"


def rel_include(path: str, include_root: Optional[str]) -> str:
    if include_root:
        try:
            rel = os.path.relpath(path, include_root)
            return rel.replace("\\", "/")
        except ValueError:
            pass
    return os.path.basename(path)


def params_decl_string(params: List[Param]) -> str:
    if not params:
        return "(void)"
    return "(" + ", ".join(p.raw for p in params) + ")"


def arg_names_all(params: List[Param]) -> List[str]:
    names = []
    for p in params:
        if p.name:
            names.append(p.name)
    return names


def arg_names_for_impl(tag: str, fn: FunctionProto, out_names: List[str]) -> Tuple[List[str], int]:
    if tag == "STUB_RET_STATUS_OUT1":
        return out_names[:1], 1
    if tag == "STUB_RET_STATUS_OUT2":
        return out_names[:2], 2

    names = arg_names_all(fn.params)
    return names, len(names)


def emit_stub_header(
    header_path: str,
    funcs: List[Tuple[FunctionProto, str, List[str]]],
    include_root: Optional[str],
    test_tools_header: str,
    stub_header_name: str
) -> str:
    guard = make_header_guard(stub_header_name)
    orig_include = rel_include(header_path, include_root)

    out = []
    out.append(f"#ifndef {guard}")
    out.append(f"#define {guard}")
    out.append("")
    out.append(f'#include "{orig_include}"')
    out.append(f'#include "{test_tools_header}"')
    out.append("")
    out.append("#ifdef __cplusplus")
    out.append('extern "C" {')
    out.append("#endif")
    out.append("")

    for fn, tag, _out_names in funcs:
        out.append(f"/* {fn.name} */")
        out.append(f"STUB_DECL_COUNTER({tag}, {fn.name})")
        out.append(f"STUB_DECL_RET({tag}, {fn.name}, {fn.ret_type})")
        out.append(f"STUB_DECL_OUT({tag}, {fn.name})")
        out.append("")

    base = sanitize_basename(header_path)
    out.append(f"void {base}_stub_reset_all(void);")
    out.append("")

    out.append("#ifdef __cplusplus")
    out.append("}")
    out.append("#endif")
    out.append("")
    out.append(f"#endif /* {guard} */")
    out.append("")

    return "\n".join(out)


def emit_stub_source(
    header_path: str,
    funcs: List[Tuple[FunctionProto, str, List[str]]],
    stub_header_name: str
) -> str:
    out = []
    out.append(f'#include "{stub_header_name}"')
    out.append("")

    for fn, tag, _out_names in funcs:
        out.append(f"/* {fn.name} */")
        out.append(f"STUB_DEF_COUNTER({tag}, {fn.name})")
        out.append(f"STUB_DEF_RET({tag}, {fn.name}, {fn.ret_type})")
        out.append(f"STUB_DEF_OUT({tag}, {fn.name})")
        out.append("")

    for fn, tag, out_names in funcs:
        names, count = arg_names_for_impl(tag, fn, out_names)
        names_tuple = "(" + ", ".join(names) + ")" if count > 0 else "()"
        out.append(
            f"STUB_IMPL({tag}, {fn.ret_type}, {fn.name}, "
            f"{params_decl_string(fn.params)}, {names_tuple}, {count})"
        )
        out.append("")

    base = sanitize_basename(header_path)
    out.append(f"void {base}_stub_reset_all(void)")
    out.append("{")
    for fn, tag, _out_names in funcs:
        out.append(f"    STUB_RESET_COUNTER({tag}, {fn.name});")
        out.append(f"    STUB_RESET_RET({tag}, {fn.name}, {fn.ret_type});")
        out.append(f"    STUB_RESET_OUT({tag}, {fn.name});")
    out.append("    return;")
    out.append("}")
    out.append("")

    return "\n".join(out)


# =========================================================
# Main generation flow
# =========================================================

def generate_for_header(
    header_path: str,
    out_dir: str,
    include_root: Optional[str],
    test_tools_header: str,
    emit_summary: bool = False
) -> Tuple[int, int]:
    text = read_file(header_path)
    protos = parse_prototypes(text, header_path)

    accepted: List[Tuple[FunctionProto, str, List[str]]] = []
    skipped = 0

    for fn in protos:
        tag, out_names = classify_tag(fn)
        if tag == "UNSUPPORTED":
            skipped += 1
            continue
        accepted.append((fn, tag, out_names))

    if not accepted:
        if emit_summary:
            eprint(f"[skip] {header_path}: no supported function prototypes")
        return 0, skipped

    base = sanitize_basename(header_path)
    stub_header_name = f"{base}_stub.h"
    stub_source_name = f"{base}_stub.c"

    header_code = emit_stub_header(
        header_path=header_path,
        funcs=accepted,
        include_root=include_root,
        test_tools_header=test_tools_header,
        stub_header_name=stub_header_name
    )
    source_code = emit_stub_source(
        header_path=header_path,
        funcs=accepted,
        stub_header_name=stub_header_name
    )

    ensure_dir(out_dir)
    write_file(os.path.join(out_dir, stub_header_name), header_code)
    write_file(os.path.join(out_dir, stub_source_name), source_code)

    if emit_summary:
        eprint(
            f"[ok] {header_path}: generated {stub_header_name}, {stub_source_name} "
            f"({len(accepted)} funcs, {skipped} skipped)"
        )

    return len(accepted), skipped


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Generate C test stubs from headers using TEST_TOOLS_H macros."
    )
    ap.add_argument(
        "input_path",
        help="Header file or directory containing .h files"
    )
    ap.add_argument(
        "--out-dir",
        default="generated_stubs",
        help="Output directory for generated *_stub.h and *_stub.c"
    )
    ap.add_argument(
        "--include-root",
        default=None,
        help="Base include root used to emit original header include paths"
    )
    ap.add_argument(
        "--test-tools-header",
        default="test_tools.h",
        help='Header path to include for TEST_TOOLS_H macros, e.g. "tests/test_tools.h"'
    )
    ap.add_argument(
        "--emit-summary",
        action="store_true",
        help="Print summary logs to stderr"
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()

    headers = list_header_files(args.input_path)
    if not headers:
        eprint(f"No header files found: {args.input_path}")
        return 1

    total_generated = 0
    total_skipped = 0
    file_count = 0

    for header in headers:
        gen_count, skipped = generate_for_header(
            header_path=header,
            out_dir=args.out_dir,
            include_root=args.include_root,
            test_tools_header=args.test_tools_header,
            emit_summary=args.emit_summary
        )
        if gen_count > 0:
            file_count += 1
            total_generated += gen_count
        total_skipped += skipped

    if args.emit_summary:
        eprint("")
        eprint("==== Summary ====")
        eprint(f"Generated files for headers : {file_count}")
        eprint(f"Generated stub functions    : {total_generated}")
        eprint(f"Skipped prototypes          : {total_skipped}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
