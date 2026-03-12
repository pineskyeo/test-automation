#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
summary: Generate dependency-aware real implementation cmocka test templates from C headers/sources
function: Parse public API prototypes, analyze C source bodies for dependency calls, inspect generated stub headers for exported symbols, and emit scenario JSON, auto test C, runner C, and per-module Makefile
file: gen_test_real_templates.py
tags: [test, generator, cmocka, real-unit-test, scenario, c, cortex]
inputs:
  - header file path or directory
  - source file path (optional, single-file mode)
  - source root directory (optional, directory mode)
  - include root
  - scenario directory
  - output directory
  - generated stub directory
returns:
  - <module>.real.scenario.json
  - test_<module>_real_auto.c
  - runner_<module>_real.c
  - Makefile.<module>.real
errors:
  - skips variadic functions
  - skips function-pointer parameters
  - uses best-effort C parsing for function bodies and dependencies
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple, Set


# =========================================================
# Models
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
    "if", "for", "while", "switch", "return", "sizeof", "do",
    "case", "break", "continue", "goto"
}

COMMON_NON_DEP_CALLS = {
    "assert", "memset", "memcpy", "memcmp", "strlen", "strcmp", "strncmp",
    "malloc", "calloc", "realloc", "free", "printf", "snprintf", "sprintf",
    "fprintf", "puts", "putchar", "abort", "exit",
    "strchr", "strrchr", "strstr", "strtol", "strtoul", "atoi", "atol",
    "isdigit", "isalpha", "isalnum", "isspace", "tolower", "toupper"
}

COMMON_NON_DEP_PREFIXES = {
    "DBG", "ERR", "WRN", "INF", "TRACE", "LOG", "ENSURE", "ASSERT"
}


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, obj: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*?$", "", text, flags=re.M)
    return text


def remove_preprocessor_lines(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def sanitize_basename(path: str) -> str:
    base = os.path.basename(path)
    return os.path.splitext(base)[0]


def rel_include(path: str, include_root: Optional[str]) -> str:
    if include_root:
        try:
            rel = os.path.relpath(path, include_root)
            return rel.replace("\\", "/")
        except ValueError:
            pass
    return os.path.basename(path)


def list_files_with_ext(path: str, ext: str) -> List[str]:
    if os.path.isfile(path):
        return [path] if path.endswith(ext) else []

    out = []
    for root, _, files in os.walk(path):
        for fn in files:
            if fn.endswith(ext):
                out.append(os.path.join(root, fn))
    out.sort()
    return out


def list_header_files(path: str) -> List[str]:
    return list_files_with_ext(path, ".h")


def list_source_files(path: str) -> List[str]:
    return list_files_with_ext(path, ".c")


def resolve_header_source_pairs(input_path: str, source_root: Optional[str]) -> List[Tuple[str, str]]:
    headers = list_header_files(input_path)
    if not headers:
        return []

    scan_root = source_root or input_path
    sources = list_source_files(scan_root)
    if not sources:
        return []

    src_map: Dict[str, List[str]] = {}
    for src in sources:
        key = sanitize_basename(src)
        src_map.setdefault(key, []).append(src)

    pairs: List[Tuple[str, str]] = []
    for hdr in headers:
        key = sanitize_basename(hdr)
        candidates = src_map.get(key, [])
        if not candidates:
            continue

        if len(candidates) == 1:
            chosen = candidates[0]
        else:
            chosen = sorted(candidates, key=lambda p: (len(p), p))[0]
            eprint(f"[warn] multiple sources for {hdr}; using {chosen}")
        pairs.append((hdr, chosen))

    return pairs


def normalize_type(t: str) -> str:
    t = collapse_ws(t)
    t = t.replace(" *", "*").replace("* ", "*")
    return t


def pointer_depth(type_str: str) -> int:
    return normalize_type(type_str).count("*")


def is_pointer_type(type_str: str) -> bool:
    return "*" in normalize_type(type_str)


def is_void_type(type_str: str) -> bool:
    return normalize_type(type_str) == "void"


def is_status_type(type_str: str) -> bool:
    return normalize_type(type_str) == "status_t"


def is_const_char_ptr(type_str: str) -> bool:
    return normalize_type(type_str) in ("const char*", "char const*")


def is_u32_type(type_str: str) -> bool:
    return normalize_type(type_str) in ("uint32_t", "u_int32_t")


def is_u64_type(type_str: str) -> bool:
    return normalize_type(type_str) in ("uint64_t", "u_int64_t")


def is_size_type(type_str: str) -> bool:
    return normalize_type(type_str) == "size_t"


def is_uptr_type(type_str: str) -> bool:
    return normalize_type(type_str) == "uintptr_t"


def is_ptr_to_ptr(p: Param) -> bool:
    return pointer_depth(p.type_str) >= 2


def is_plain_ptr(p: Param) -> bool:
    return pointer_depth(p.type_str) == 1


def is_integral_like_type(type_str: str) -> bool:
    t = normalize_type(type_str)
    return t in {
        "int", "unsigned", "unsigned int", "long", "unsigned long",
        "short", "unsigned short", "char", "signed char", "unsigned char",
        "size_t", "uint32_t", "uint64_t", "uintptr_t"
    }


def module_prefix_from_symbol(name: str) -> str:
    return name.split("_", 1)[0] if "_" in name else name


def guess_stub_reset_name(dep_name: str) -> str:
    return f"{module_prefix_from_symbol(dep_name)}_stub_reset_all"


def unique_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _is_within_dir(path: str, root_dir: str) -> bool:
    path_real = os.path.realpath(path)
    root_real = os.path.realpath(root_dir)
    try:
        return os.path.commonpath([path_real, root_real]) == root_real
    except ValueError:
        return False


def build_recursive_filename_index(root_dir: str) -> Dict[str, List[str]]:
    index: Dict[str, List[str]] = {}

    if not root_dir or not os.path.isdir(root_dir):
        return index

    for walk_root, _, files in os.walk(root_dir):
        if not _is_within_dir(walk_root, root_dir):
            continue

        for filename in files:
            abs_path = os.path.join(walk_root, filename)
            if not _is_within_dir(abs_path, root_dir):
                continue
            rel_path = os.path.relpath(abs_path, root_dir).replace("\\", "/")
            index.setdefault(filename, []).append(rel_path)

    return index


def find_relative_file_recursive(
    root_dir: str,
    target_filename: str,
    file_index: Optional[Dict[str, List[str]]] = None,
) -> Optional[str]:
    index = file_index if file_index is not None else build_recursive_filename_index(root_dir)
    matches = index.get(target_filename, [])
    if not matches:
        return None

    return sorted(matches, key=lambda p: (p.count("/"), len(p), p))[0]


# =========================================================
# Header parsing
# =========================================================

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
            p = "".join(buf).strip()
            if p:
                parts.append(p)
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

    if re.search(r"\(\s*\*\s*[A-Za-z_]\w*\s*\)", s):
        return Param(raw=s, type_str="FUNC_PTR", name="FUNC_PTR")

    m = re.match(r"^(?P<type>.+?)(?P<name>[A-Za-z_]\w*)$", s)
    if not m:
        return Param(raw=s, type_str=s, name="")

    return Param(
        raw=s,
        type_str=collapse_ws(m.group("type").rstrip()),
        name=m.group("name").strip()
    )


def proto_key(fn: FunctionProto) -> Tuple[str, str, Tuple[str, ...]]:
    return (
        collapse_ws(fn.ret_type),
        fn.name,
        tuple(collapse_ws(p.raw) for p in fn.params),
    )


def dedup_protos(protos: List[FunctionProto]) -> List[FunctionProto]:
    out = []
    seen = set()
    for fn in protos:
        k = proto_key(fn)
        if k in seen:
            continue
        seen.add(k)
        out.append(fn)
    return out


def parse_prototypes(header_text: str, header_path: str) -> List[FunctionProto]:
    text = strip_comments(header_text)
    text = remove_preprocessor_lines(text)
    text = text.replace('extern "C" {', "")
    text = text.replace('extern \"C\" {', "")

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

    out = []

    for chunk in chunks:
        chunk = collapse_ws(chunk)

        if "(" not in chunk or ")" not in chunk or not chunk.endswith(";"):
            continue
        if chunk.startswith("typedef "):
            continue
        if re.search(r"\btypedef\b", chunk):
            continue

        m = re.match(
            r"^(?P<ret>.+?)\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<params>.*)\)\s*;$",
            chunk
        )
        if not m:
            continue

        ret_type = collapse_ws(m.group("ret"))
        fn_name = m.group("name").strip()
        params_raw = m.group("params").strip()

        params = []
        if params_raw and params_raw != "void":
            raw_parts = split_top_level_params(params_raw)
            parsed = [parse_param(p) for p in raw_parts]
            if any(x and x.type_str in ("...", "FUNC_PTR") for x in parsed):
                continue
            params = [x for x in parsed if x is not None]

        out.append(FunctionProto(
            ret_type=ret_type,
            name=fn_name,
            params=params,
            header_path=header_path
        ))

    return dedup_protos(out)


# =========================================================
# Source analysis
# =========================================================

def find_function_body(source_text: str, fn_name: str) -> Optional[str]:
    text = strip_comments(source_text)
    pattern = re.compile(r"\b" + re.escape(fn_name) + r"\s*\(")
    m = pattern.search(text)
    if not m:
        return None

    pos = m.end() - 1
    depth = 0
    found_open = False

    while pos < len(text):
        ch = text[pos]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                pos += 1
                while pos < len(text) and text[pos].isspace():
                    pos += 1
                while pos < len(text) and text[pos] != "{":
                    pos += 1
                if pos >= len(text) or text[pos] != "{":
                    return None
                found_open = True
                break
        pos += 1

    if not found_open:
        return None

    start = pos
    brace_depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
            if brace_depth == 0:
                return text[start + 1:i]
        i += 1

    return None


def extract_called_functions(body: str, self_name: str) -> List[str]:
    if not body:
        return []

    candidates = re.findall(r"\b([A-Za-z_]\w*)\s*\(", body)
    out = []
    seen = set()

    for name in candidates:
        if name in C_KEYWORDS:
            continue
        if name in COMMON_NON_DEP_CALLS:
            continue

        matched_prefix = next((p for p in COMMON_NON_DEP_PREFIXES if name.startswith(p)), None)
        if matched_prefix:
            print("skip by prefix:", name, matched_prefix)
            continue

        if name.isupper():
            continue
        if re.match(r"^[A-Z][A-Z0-9_]*$", name):
            continue
        if name == self_name:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name)

    return out


# =========================================================
# Generated stub header inspection
# =========================================================

def parse_stub_header_symbols(stub_header_path: str) -> dict:
    info = {
        "reset": None,
        "counter": None,
        "ret": None,
        "symbols": []
    }

    if not os.path.exists(stub_header_path):
        return info

    text = read_file(stub_header_path)

    m = re.search(r"\bvoid\s+([A-Za-z_]\w*_stub_reset_all)\s*\(\s*void\s*\)\s*;", text)
    if m:
        info["reset"] = m.group(1)

    define_resets = re.findall(r"^\s*#\s*define\s+([A-Za-z_]\w*_stub_reset_all)\s*\(", text, flags=re.M)
    if define_resets and not info["reset"]:
        info["reset"] = define_resets[0]

    symbols: Set[str] = set()
    extern_symbols = re.findall(r"\bextern\s+[A-Za-z_][A-Za-z0-9_ *]*\s+([A-Za-z_]\w*)\s*;", text)
    symbols.update(extern_symbols)

    define_symbols = re.findall(r"^\s*#\s*define\s+([A-Za-z_]\w*)\b", text, flags=re.M)
    symbols.update(x for x in define_symbols if x.startswith("g_"))

    info["symbols"] = sorted(symbols)
    return info


def resolve_stub_knobs(dep_name: str, stub_header_path: str) -> dict:
    info = parse_stub_header_symbols(stub_header_path)
    symbols = set(info["symbols"])

    prefix = module_prefix_from_symbol(dep_name)

    counter = None
    ret = None

    candidates_counter = [
        f"g_{dep_name}_call_cnt",
        f"g_{dep_name}_calls",
        f"g_{prefix}_call_cnt",
        f"g_{prefix}_calls",
    ]

    candidates_ret = [
        f"g_{dep_name}_ret",
        f"g_{prefix}_ret",
    ]

    for c in candidates_counter:
        if c in symbols:
            counter = c
            break

    for c in candidates_ret:
        if c in symbols:
            ret = c
            break

    return {
        "reset": info["reset"],
        "counter": counter,
        "ret": ret,
        "symbols": list(symbols),
    }


# =========================================================
# Scenario generation
# =========================================================

def function_kind(fn_name: str) -> str:
    name = fn_name.lower()
    if "_create" in name or name.startswith("create_") or name.endswith("_create"):
        return "create"
    if "_init" in name or name.startswith("init_") or name.endswith("_init"):
        return "init"
    if "_open" in name or name.startswith("open_") or name.endswith("_open"):
        return "open"
    if "_destroy" in name or name.startswith("destroy_") or name.endswith("_destroy"):
        return "destroy"
    if "_free" in name or name.startswith("free_") or name.endswith("_free"):
        return "free"
    if "_close" in name or name.startswith("close_") or name.endswith("_close"):
        return "close"
    if "_get" in name or name.startswith("get_") or name.endswith("_get"):
        return "get"
    if "_find" in name or name.startswith("find_") or name.endswith("_find"):
        return "find"
    if "_set" in name or name.startswith("set_") or name.endswith("_set"):
        return "set"
    if "_update" in name or name.startswith("update_") or name.endswith("_update"):
        return "update"
    if "_load" in name or name.startswith("load_") or name.endswith("_load"):
        return "load"
    if "_save" in name or name.startswith("save_") or name.endswith("_save"):
        return "save"
    return "generic"


def default_value_for_param(p: Param) -> str:
    t = normalize_type(p.type_str)

    if is_ptr_to_ptr(p):
        return f"&{p.name}_var"

    if is_plain_ptr(p):
        if is_const_char_ptr(t):
            return '"sample"'
        if t in ("void*", "const void*", "void const*"):
            return f"{p.name}_var"
        return f"{p.name}_var"

    if is_integral_like_type(t):
        return "0"

    if p.name:
        return f"{p.name}_var"

    return "0"


def local_decl_for_param(p: Param) -> Optional[str]:
    t = normalize_type(p.type_str)
    name = p.name

    if not name:
        return None

    if is_ptr_to_ptr(p):
        base = collapse_ws(t.replace("*", ""))
        return f"{base}* {name}_var = NULL;"

    if is_plain_ptr(p):
        if t in ("const char*", "char const*"):
            return None
        if t in ("void*", "const void*", "void const*"):
            return f"void* {name}_var = NULL;"
        return f"{t} {name}_var = ({t})1;"

    if is_integral_like_type(t):
        return None

    return f"{t} {name}_var;"


def make_call_args(fn: FunctionProto) -> List[str]:
    return [default_value_for_param(p) for p in fn.params]


def make_locals(fn: FunctionProto) -> List[str]:
    locals_list = []
    for p in fn.params:
        line = local_decl_for_param(p)
        if not line:
            continue
        locals_list.append(line)
    return locals_list


def find_all_pointer_params(fn: FunctionProto) -> List[Param]:
    return [p for p in fn.params if is_pointer_type(p.type_str)]


def default_expect_for_ret_type(ret_type: str, success: bool, fn_name: str = "") -> Dict[str, object]:
    ret_type = normalize_type(ret_type)
    kind = function_kind(fn_name)

    if is_void_type(ret_type):
        return {}

    if is_status_type(ret_type):
        return {"status_eq": "OK"} if success else {"status_ne": "OK"}

    if is_pointer_type(ret_type) or is_const_char_ptr(ret_type):
        if success:
            if kind in ("create", "open", "get", "find", "load"):
                return {"ptr_ne": ["ret", "NULL"]}
            return {"ptr_ne": ["ret", "NULL"]}
        return {"ptr_eq": ["ret", "NULL"]}

    if is_u32_type(ret_type):
        return {"int_ne": ["ret", "0U"]} if success else {"int_eq": ["ret", "0U"]}

    if is_u64_type(ret_type):
        return {"int_ne": ["ret", "0ULL"]} if success else {"int_eq": ["ret", "0ULL"]}

    if is_size_type(ret_type):
        return {"int_ne": ["ret", "0U"]} if success else {"int_eq": ["ret", "0U"]}

    if is_uptr_type(ret_type):
        return {"int_ne": ["ret", "(uintptr_t)0"]} if success else {"int_eq": ["ret", "(uintptr_t)0"]}

    return {}


def default_success_stub(ret_type: str) -> Dict[str, str]:
    _ = ret_type
    return {}


def guess_failure_knob(dep_meta: dict, fn_ret_type: str) -> Dict[str, str]:
    ret_symbol = dep_meta.get("ret_symbol")
    if not ret_symbol:
        return {}

    if is_status_type(fn_ret_type):
        return {ret_symbol: "ERR_UNSUPPORTED"}

    # pointer return stubs often still expose status knobs in this project.
    return {ret_symbol: "ERR_UNSUPPORTED"}


def infer_dependency_metadata(deps: List[str], stub_generated_dir: str) -> List[dict]:
    def build_stub_module_index(root_dir: str) -> Dict[str, List[str]]:
        module_index: Dict[str, List[str]] = {}
        if not root_dir or not os.path.isdir(root_dir):
            return module_index

        for walk_root, _, files in os.walk(root_dir):
            for filename in files:
                if not filename.endswith("_stub.h"):
                    continue
                rel_path = os.path.relpath(os.path.join(walk_root, filename), root_dir).replace("\\", "/")
                module_name = filename[:-len("_stub.h")]
                module_index.setdefault(module_name, []).append(rel_path)

        for module_name in list(module_index.keys()):
            module_index[module_name] = sorted(
                module_index[module_name],
                key=lambda p: (p.count("/"), len(p), p)
            )
        return module_index

    def resolve_stub_header_from_dep(dep_name: str, module_index: Dict[str, List[str]]) -> Optional[Tuple[str, str]]:
        tokens = dep_name.split("_")
        if not tokens:
            return None

        best_module = None
        for i in range(len(tokens), 0, -1):
            candidate = "_".join(tokens[:i])
            if candidate in module_index:
                best_module = candidate
                break

        if not best_module:
            return None

        return best_module, module_index[best_module][0]

    meta = []
    seen = set()
    stub_module_index = build_stub_module_index(stub_generated_dir)

    for dep in deps:
        if dep in seen:
            continue
        seen.add(dep)

        resolved = resolve_stub_header_from_dep(dep, stub_module_index)
        if not resolved:
            continue

        prefix, stub_header = resolved
        if not stub_header:
            # Only keep dependencies that resolve to an actual generated stub header.
            continue

        stub_source = stub_header.replace("_stub.h", "_stub.c")
        stub_header_path = os.path.join(stub_generated_dir, stub_header).replace("\\", "/")
        stub_source_path = os.path.join(stub_generated_dir, stub_source).replace("\\", "/")

        knobs = resolve_stub_knobs(dep, stub_header_path)

        meta.append({
            "name": dep,
            "prefix": prefix,
            "stub_header": stub_header,
            "stub_source": stub_source,
            "stub_header_path": stub_header_path,
            "stub_source_path": stub_source_path,
            "stub_reset": knobs["reset"] or guess_stub_reset_name(dep),
            "counter_symbol": knobs["counter"],
            "ret_symbol": knobs["ret"],
        })

    return meta


def make_real_scenarios(fn: FunctionProto, dep_meta: List[dict]) -> List[dict]:
    scenarios = []
    locals_list = make_locals(fn)
    call_args = make_call_args(fn)
    pointer_params = find_all_pointer_params(fn)
    dep_resets = unique_keep_order([d["stub_reset"] for d in dep_meta if d.get("stub_reset")])

    # 1) one NULL case per pointer parameter
    for ptr in pointer_params:
        null_args = make_call_args(fn)
        idx = [p.name for p in fn.params].index(ptr.name)
        null_args[idx] = "NULL"

        expect = default_expect_for_ret_type(fn.ret_type, success=False, fn_name=fn.name)

        scenarios.append({
            "name": f"null_{ptr.name}",
            "enabled": True,
            "locals": locals_list,
            "stub_resets": dep_resets,
            "stub": {},
            "call_args": null_args,
            "expect": expect,
            "notes": f"Generated NULL defensive case for pointer parameter '{ptr.name}'. Edit if NULL is valid."
        })

    # 2) default success
    success_expect = default_expect_for_ret_type(fn.ret_type, success=True, fn_name=fn.name)
    scenarios.append({
        "name": "default_success",
        "enabled": True,
        "locals": locals_list,
        "stub_resets": dep_resets,
        "stub": default_success_stub(fn.ret_type),
        "call_args": call_args,
        "expect": success_expect,
        "notes": "Conservative success skeleton. Replace expectations with real behavior."
    })

    # 3) dependency-specific fail cases
    for dep in dep_meta:
        fail_expect = default_expect_for_ret_type(fn.ret_type, success=False, fn_name=fn.name)
        counter_symbol = dep.get("counter_symbol")
        if counter_symbol:
            fail_expect["dep_call_cnt"] = [counter_symbol, 1]

        scenarios.append({
            "name": f"{dep['name']}_fail",
            "enabled": True,
            "locals": locals_list,
            "stub_resets": dep_resets,
            "stub": guess_failure_knob(dep, fn.ret_type),
            "call_args": call_args,
            "expect": fail_expect,
            "notes": f"Auto-generated dependency failure skeleton for '{dep['name']}'. Tune knob names and expectations."
        })

    return scenarios


def build_default_scenario_doc(
    header_path: str,
    source_path: str,
    protos: List[FunctionProto],
    source_text: str,
    stub_generated_dir: str
) -> dict:
    module = sanitize_basename(header_path)
    functions = []
    all_stub_headers = []
    all_stub_sources = []

    for fn in protos:
        body = find_function_body(source_text, fn.name)
        deps = extract_called_functions(body or "", fn.name)
        dep_meta = infer_dependency_metadata(deps, stub_generated_dir)

        all_stub_headers.extend([d["stub_header"] for d in dep_meta])
        all_stub_sources.extend([d["stub_source_path"] for d in dep_meta if os.path.exists(d["stub_source_path"])])

        functions.append({
            "name": fn.name,
            "ret_type": fn.ret_type,
            "params": [asdict(p) for p in fn.params],
            "dependencies": deps,
            "dependency_meta": dep_meta,
            "enabled": True,
            "scenarios": make_real_scenarios(fn, dep_meta)
        })

    return {
        "module": module,
        "header": header_path.replace("\\", "/"),
        "source": source_path.replace("\\", "/"),
        "stub_headers": unique_keep_order(all_stub_headers),
        "stub_sources": unique_keep_order(all_stub_sources),
        "functions": functions
    }


def merge_scenarios(default_doc: dict, existing_doc: Optional[dict]) -> dict:
    if not existing_doc:
        return default_doc

    existing_map = {}
    for f in existing_doc.get("functions", []):
        existing_map[f.get("name")] = f

    merged_functions = []

    for new_f in default_doc.get("functions", []):
        name = new_f["name"]
        old_f = existing_map.get(name)
        if not old_f:
            merged_functions.append(new_f)
            continue

        merged_f = dict(new_f)
        merged_f["enabled"] = old_f.get("enabled", new_f.get("enabled", True))
        merged_f["dependencies"] = old_f.get("dependencies", new_f.get("dependencies", []))
        merged_f["dependency_meta"] = old_f.get("dependency_meta", new_f.get("dependency_meta", []))

        old_scen_map = {}
        for sc in old_f.get("scenarios", []):
            old_scen_map[sc.get("name")] = sc

        new_scenarios = []
        for new_sc in new_f.get("scenarios", []):
            old_sc = old_scen_map.get(new_sc["name"])
            if old_sc:
                merged_sc = dict(new_sc)
                for k, v in old_sc.items():
                    if k in {
                        "enabled", "locals", "stub_resets", "stub", "call_args", "expect",
                        "notes", "custom_lines", "pre_call_lines", "post_call_lines"
                    }:
                        merged_sc[k] = v
                new_scenarios.append(merged_sc)
            else:
                new_scenarios.append(new_sc)

        new_names = {x["name"] for x in new_scenarios}
        for old_sc in old_f.get("scenarios", []):
            if old_sc.get("name") not in new_names:
                new_scenarios.append(old_sc)

        merged_f["scenarios"] = new_scenarios
        merged_functions.append(merged_f)

    return {
        "module": default_doc.get("module"),
        "header": default_doc.get("header"),
        "source": default_doc.get("source"),
        "stub_headers": default_doc.get("stub_headers", []),
        "stub_sources": default_doc.get("stub_sources", []),
        "functions": merged_functions
    }


# =========================================================
# C rendering
# =========================================================

def c_escape_comment(s: str) -> str:
    return s.replace("*/", "* /")


def make_test_fn_name(fn_name: str, scen_name: str) -> str:
    return f"test_{fn_name}__{scen_name}"


def render_locals(locals_list: List[str]) -> List[str]:
    lines = []
    for item in locals_list:
        if not item.endswith(";"):
            item += ";"
        lines.append(f"    {item}")
    return lines


def render_resets(reset_names: List[str]) -> List[str]:
    return [f"    {name}();" for name in unique_keep_order(reset_names)]


def render_stub_assignments(stub_dict: Dict[str, str]) -> List[str]:
    return [f"    {k} = {v};" for k, v in stub_dict.items()]


def render_call(fn: dict, call_args: List[str]) -> str:
    call = f"{fn['name']}({', '.join(call_args)})"
    ret_type = fn["ret_type"]

    if is_void_type(ret_type):
        return f"    {call};"

    if is_status_type(ret_type):
        return f"    status_t st = {call};"

    return f"    {ret_type} ret = {call};"


def render_asserts(expect: Dict[str, object]) -> List[str]:
    lines = []

    if "status_eq" in expect:
        lines.append(f"    assert_int_equal(st, {expect['status_eq']});")
    if "status_ne" in expect:
        lines.append(f"    assert_int_not_equal(st, {expect['status_ne']});")

    if "ptr_eq" in expect:
        lhs, rhs = expect["ptr_eq"]
        lines.append(f"    assert_ptr_equal({lhs}, {rhs});")
    if "ptr_ne" in expect:
        lhs, rhs = expect["ptr_ne"]
        lines.append(f"    assert_ptr_not_equal({lhs}, {rhs});")

    if "int_eq" in expect:
        lhs, rhs = expect["int_eq"]
        lines.append(f"    assert_int_equal({lhs}, {rhs});")
    if "int_ne" in expect:
        lhs, rhs = expect["int_ne"]
        lines.append(f"    assert_int_not_equal({lhs}, {rhs});")

    if "dep_call_cnt" in expect:
        lhs, rhs = expect["dep_call_cnt"]
        lines.append(f"    assert_int_equal({lhs}, {rhs});")

    return lines


def emit_test_function(fn: dict, scenario: dict) -> str:
    lines = []
    test_name = make_test_fn_name(fn["name"], scenario["name"])
    notes = scenario.get("notes", "")
    locals_list = scenario.get("locals", [])
    resets = scenario.get("stub_resets", [])
    stub = scenario.get("stub", {})
    call_args = scenario.get("call_args", [])
    expect = scenario.get("expect", {})
    pre_call_lines = scenario.get("pre_call_lines", [])
    post_call_lines = scenario.get("post_call_lines", [])
    custom_lines = scenario.get("custom_lines", [])

    lines.append(f"void {test_name}(void **state)")
    lines.append("{")
    if notes:
        lines.append(f"    /* {c_escape_comment(notes)} */")
    lines.append("    (void)state;")

    if locals_list:
        lines.extend(render_locals(locals_list))
        lines.append("")

    if resets:
        lines.extend(render_resets(resets))
    if stub:
        lines.extend(render_stub_assignments(stub))
    if resets or stub:
        lines.append("")

    for line in pre_call_lines:
        lines.append(f"    {line.rstrip(';')};")
    if pre_call_lines:
        lines.append("")

    lines.append(render_call(fn, call_args))

    for line in post_call_lines:
        lines.append(f"    {line.rstrip(';')};")

    assert_lines = render_asserts(expect)
    if assert_lines:
        lines.append("")
        lines.extend(assert_lines)

    if custom_lines:
        lines.append("")
        for line in custom_lines:
            lines.append(f"    {line.rstrip(';')};")

    lines.append("    return;")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def emit_register_function(module: str, scenario_doc: dict) -> str:
    lines = []
    reg_name = f"register_test_{module}_real_auto"
    lines.append(f"void {reg_name}(struct CMUnitTest* out, size_t* io, size_t cap)")
    lines.append("{")
    lines.append("    size_t i = *io;")
    lines.append("")

    for fn in scenario_doc.get("functions", []):
        if not fn.get("enabled", True):
            continue
        for sc in fn.get("scenarios", []):
            if not sc.get("enabled", True):
                continue
            tname = make_test_fn_name(fn["name"], sc["name"])
            lines.append(f'    if (i < cap) out[i++] = (struct CMUnitTest){{ "{tname}", {tname}, NULL, NULL, NULL }};')

    lines.append("")
    lines.append("    *io = i;")
    lines.append("    return;")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def collect_stub_headers(scenario_doc: dict) -> List[str]:
    return unique_keep_order(scenario_doc.get("stub_headers", []))


def emit_test_c(
    scenario_doc: dict,
    include_root: Optional[str],
    stub_generated_dir: str,
    test_tools_header: str,
) -> str:
    module = scenario_doc["module"]
    header_inc = rel_include(scenario_doc["header"], include_root)
    stub_headers = collect_stub_headers(scenario_doc)

    lines = []
    lines.append("#include <stdarg.h>")
    lines.append("#include <stddef.h>")
    lines.append("#include <setjmp.h>")
    lines.append("#include <cmocka.h>")
    lines.append("")
    lines.append(f'#include "{test_tools_header}"')
    lines.append(f'#include "{header_inc}"')

    include_prefix = stub_generated_dir.rstrip("/")
    for hdr in stub_headers:
        lines.append(f'#include "{include_prefix}/{hdr}"')

    lines.append("")
    lines.append("/*")
    lines.append(" * Auto-generated REAL implementation test file.")
    lines.append(" * Edit the scenario JSON, then regenerate this file.")
    lines.append(" * This file calls the real module implementation and uses lower-level stubs.")
    lines.append(" */")
    lines.append("")

    for fn in scenario_doc.get("functions", []):
        if not fn.get("enabled", True):
            continue
        for sc in fn.get("scenarios", []):
            if not sc.get("enabled", True):
                continue
            lines.append(emit_test_function(fn, sc))

    lines.append(emit_register_function(module, scenario_doc))
    return "\n".join(lines)


def emit_runner_c(module: str) -> str:
    return f"""#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>
#include <stdlib.h>
#include <cmocka.h>

void register_test_{module}_real_auto(struct CMUnitTest* out, size_t* io, size_t cap);

int main(void) {{
    size_t cap = 256;
    size_t n = 0;
    struct CMUnitTest* tests = NULL;
    int rc = 0;

    tests = (struct CMUnitTest*)calloc(cap, sizeof(*tests));
    if (!tests) return 1;

    register_test_{module}_real_auto(tests, &n, cap);
    rc = _cmocka_run_group_tests("{module}_real_auto", tests, n, NULL, NULL);

    free(tests);
    return rc;
}}
"""


def emit_makefile(
    module: str,
    source_path: str,
    out_dir: str,
    tests_dir: str,
    include_dir: str,
    stub_generated_dir: str,
    dependency_stub_sources: List[str],
    extra_real_srcs: List[str],
    extra_cflags: str,
    extra_ldflags: str,
    cmocka_lib: str
) -> str:
    test_c = os.path.join(out_dir, f"test_{module}_real_auto.c").replace("\\", "/")
    runner_c = os.path.join(out_dir, f"runner_{module}_real.c").replace("\\", "/")
    target = os.path.join("bin", f"test_{module}_real_auto").replace("\\", "/")

    real_srcs = [source_path.replace("\\", "/")]
    real_srcs.extend([x.replace("\\", "/") for x in extra_real_srcs])
    real_srcs = unique_keep_order(real_srcs)
    real_srcs_make = " ".join(real_srcs)

    stub_srcs = [x.replace("\\", "/") for x in dependency_stub_sources]
    stub_srcs = unique_keep_order(stub_srcs)
    stub_srcs_make = " ".join(stub_srcs)

    return f"""# Auto-generated REAL test Makefile
# Module: {module}

CC = cc
CSTD = -std=c99
WARN = -Wall -Wextra
CFLAGS = $(CSTD) $(WARN) -I{include_dir} -I{tests_dir} -I{stub_generated_dir} -I{out_dir} {extra_cflags}
LDFLAGS = {extra_ldflags} {cmocka_lib}

BUILD_DIR = build
BIN_DIR = bin
TARGET = {target}

REAL_SRCS = {real_srcs_make}
STUB_SRCS = {stub_srcs_make}
TEST_C = {test_c}
RUNNER_C = {runner_c}

all: $(TARGET)

$(BUILD_DIR):
\tmkdir -p $@

$(BIN_DIR):
\tmkdir -p $@

$(TARGET): $(REAL_SRCS) $(STUB_SRCS) $(TEST_C) $(RUNNER_C) | $(BUILD_DIR) $(BIN_DIR)
\t$(CC) $(CFLAGS) $(REAL_SRCS) $(STUB_SRCS) $(TEST_C) $(RUNNER_C) -o $@ $(LDFLAGS)

run: $(TARGET)
\t./$(TARGET)

check-src:
\t@test -f "{source_path}" || (echo "Missing: {source_path}" && exit 1)
\t@test -f "$(TEST_C)" || (echo "Missing: $(TEST_C)" && exit 1)
\t@test -f "$(RUNNER_C)" || (echo "Missing: $(RUNNER_C)" && exit 1)

clean:
\trm -rf $(BUILD_DIR) $(BIN_DIR)

re: clean all

print:
\t@echo "TARGET     = $(TARGET)"
\t@echo "REAL_SRCS  = $(REAL_SRCS)"
\t@echo "STUB_SRCS  = $(STUB_SRCS)"
\t@echo "TEST_C     = $(TEST_C)"
\t@echo "RUNNER_C   = $(RUNNER_C)"
\t@echo "CFLAGS     = $(CFLAGS)"
\t@echo "LDFLAGS    = $(LDFLAGS)"

.PHONY: all run clean re check-src print
"""


# =========================================================
# Main flow
# =========================================================

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Generate REAL implementation cmocka test templates from one header/source pair."
    )
    ap.add_argument(
        "input_path",
        help="Header file or directory containing .h files",
    )
    ap.add_argument(
        "source_path",
        nargs="?",
        default=None,
        help="Optional real source path for single-file mode (legacy)",
    )
    ap.add_argument(
        "--source-root",
        default=None,
        help="Directory to scan for .c files in directory mode (defaults to input_path)",
    )
    ap.add_argument("--scenario-dir", default="tests/scenarios_real", help="Scenario JSON output directory")
    ap.add_argument("--out-dir", default="tests/auto_real", help="Generated C output directory")
    ap.add_argument("--include-root", default=None, help="Include root used for emitted #include paths")
    ap.add_argument("--include-dir", default="include", help="Compiler include directory for Makefile")
    ap.add_argument("--tests-dir", default="tests", help="Tests base directory for Makefile")
    ap.add_argument("--stub-generated-dir", default="tests/stub/generated", help="Generated stub directory")
    ap.add_argument("--stub-include-prefix", default="", help='(deprecated) Unused; stub includes are resolved from --stub-generated-dir')
    ap.add_argument(
        "--test-tools-header",
        default="test_tools.h",
        help='Header path to include for TEST_TOOLS_H macros, e.g. "tests/test_tools.h"',
    )
    ap.add_argument("--extra-real-src", action="append", default=[], help="Additional real source files to compile")
    ap.add_argument("--extra-cflags", default="", help="Extra CFLAGS for Makefile")
    ap.add_argument("--extra-ldflags", default="", help="Extra LDFLAGS for Makefile")
    ap.add_argument("--cmocka-lib", default="-lcmocka", help="cmocka linker flag")
    ap.add_argument("--emit-summary", action="store_true", help="Print summary to stderr")
    return ap.parse_args()


def main() -> int:
    args = parse_args()

    if args.source_path:
        pairs = [(args.input_path, args.source_path)]
    else:
        pairs = resolve_header_source_pairs(args.input_path, args.source_root)

    if not pairs:
        eprint(f"No header/source pairs found from input: {args.input_path}")
        return 1

    gen_count = 0
    total_tests = 0

    for header_path, source_path in pairs:
        header_text = read_file(header_path)
        source_text = read_file(source_path)

        protos = parse_prototypes(header_text, header_path)
        if not protos:
            if args.emit_summary:
                eprint(f"[skip] {header_path}: no supported prototypes")
            continue

        default_doc = build_default_scenario_doc(
            header_path=header_path,
            source_path=source_path,
            protos=protos,
            source_text=source_text,
            stub_generated_dir=args.stub_generated_dir,
        )

        module = default_doc["module"]
        scenario_path = os.path.join(args.scenario_dir, f"{module}.real.scenario.json")
        existing_doc = read_json(scenario_path) if os.path.exists(scenario_path) else None
        merged_doc = merge_scenarios(default_doc, existing_doc)

        write_json(scenario_path, merged_doc)

        test_c_path = os.path.join(args.out_dir, f"test_{module}_real_auto.c")
        runner_c_path = os.path.join(args.out_dir, f"runner_{module}_real.c")
        makefile_path = os.path.join(args.out_dir, f"Makefile.{module}.real")
        dependency_stub_sources = merged_doc.get("stub_sources", [])

        write_file(
            test_c_path,
            emit_test_c(
                merged_doc,
                args.include_root,
                args.stub_generated_dir,
                args.test_tools_header,
            ),
        )
        write_file(runner_c_path, emit_runner_c(module))
        write_file(
            makefile_path,
            emit_makefile(
                module=module,
                source_path=source_path,
                out_dir=args.out_dir,
                tests_dir=args.tests_dir,
                include_dir=args.include_dir,
                stub_generated_dir=args.stub_generated_dir,
                dependency_stub_sources=dependency_stub_sources,
                extra_real_srcs=args.extra_real_src,
                extra_cflags=args.extra_cflags,
                extra_ldflags=args.extra_ldflags,
                cmocka_lib=args.cmocka_lib,
            ),
        )

        enabled_tests = 0
        for fn in merged_doc.get("functions", []):
            if not fn.get("enabled", True):
                continue
            for sc in fn.get("scenarios", []):
                if sc.get("enabled", True):
                    enabled_tests += 1

        gen_count += 1
        total_tests += enabled_tests

        if args.emit_summary:
            eprint(f"[ok] module    : {module}")
            eprint(f"[ok] header    : {header_path}")
            eprint(f"[ok] source    : {source_path}")
            eprint(f"[ok] scenario  : {scenario_path}")
            eprint(f"[ok] test      : {test_c_path}")
            eprint(f"[ok] runner    : {runner_c_path}")
            eprint(f"[ok] makefile  : {makefile_path}")
            eprint(f"[ok] tests     : {enabled_tests}")

    if gen_count == 0:
        eprint("No modules generated (all headers skipped).")
        return 1

    if args.emit_summary:
        eprint("")
        eprint("==== Summary ====")
        eprint(f"Modules generated: {gen_count}")
        eprint(f"Tests generated  : {total_tests}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
