#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
summary: Generate scenario JSON and cmocka auto test templates from C header files
function: Parse C header prototypes, emit editable scenario files, and generate test_<module>_stub_auto.c using TEST_TOOLS_H-based stub knobs
file: gen_test_stub_templates.py
tags: [test, generator, cmocka, stub, scenario, c, cortex]
inputs:
  - header file or directory
  - output directory
  - include root
  - scenario directory
  - stub header suffix
returns:
  - scenario JSON files
  - generated auto test C files
errors:
  - skips variadic functions
  - skips function-pointer parameters
  - falls back to conservative defaults for unsupported return types
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple


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
# Common helpers
# =========================================================


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


def list_header_files(path: str) -> List[str]:
    if os.path.isfile(path):
        return [path] if path.endswith(".h") else []

    out = []
    for root, _, files in os.walk(path):
        for fn in files:
            if fn.endswith(".h"):
                out.append(os.path.join(root, fn))
    out.sort()
    return out


# =========================================================
# C prototype parsing
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

    # Skip function pointer parameters conservatively.
    if re.search(r"\(\s*\*\s*[A-Za-z_]\w*\s*\)", s):
        return Param(raw=s, type_str="FUNC_PTR", name="FUNC_PTR")

    m = re.match(r"^(?P<type>.+?)(?P<name>[A-Za-z_]\w*)$", s)
    if not m:
        return Param(raw=s, type_str=s, name="")

    type_part = m.group("type").rstrip()
    name = m.group("name").strip()

    return Param(raw=s, type_str=collapse_ws(type_part), name=name)


def parse_prototypes(text: str, header_path: str) -> List[FunctionProto]:
    text = strip_comments(text)
    text = remove_preprocessor_lines(text)
    text = text.replace('extern "C" {', "")
    text = text.replace('extern \\"C\\" {', "")

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

    out: List[FunctionProto] = []

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
            chunk,
        )
        if not m:
            continue

        ret_type = collapse_ws(m.group("ret"))
        fn_name = m.group("name").strip()
        params_raw = m.group("params").strip()

        params: List[Param] = []
        if params_raw and params_raw != "void":
            raw_parts = split_top_level_params(params_raw)
            parsed = [parse_param(p) for p in raw_parts]
            if any(x and x.type_str in ("...", "FUNC_PTR") for x in parsed):
                continue
            params = [x for x in parsed if x is not None]

        out.append(
            FunctionProto(
                ret_type=ret_type,
                name=fn_name,
                params=params,
                header_path=header_path,
            )
        )

    return out


# =========================================================
# Type helpers
# =========================================================


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
        "int",
        "unsigned",
        "unsigned int",
        "long",
        "unsigned long",
        "short",
        "unsigned short",
        "char",
        "signed char",
        "unsigned char",
        "size_t",
        "uint32_t",
        "uint64_t",
        "uintptr_t",
    }


# =========================================================
# Stub tag classification
# =========================================================


def is_out_param_candidate(p: Param) -> bool:
    if not is_ptr_to_ptr(p):
        return False

    lname = p.name.lower()
    if (
        lname.startswith("out")
        or lname.endswith("_out")
        or "_out_" in lname
        or lname in ("result", "value", "dst", "pp")
    ):
        return True

    return True


def classify_stub_tag(fn: FunctionProto) -> Tuple[str, List[str]]:
    ret = normalize_type(fn.ret_type)
    out_names = [p.name for p in fn.params if is_out_param_candidate(p)]

    if is_status_type(ret):
        if len(out_names) >= 2:
            return "STUB_RET_STATUS_OUT2", out_names[:2]
        if len(out_names) == 1:
            return "STUB_RET_STATUS_OUT1", out_names[:1]
        return "STUB_RET_STATUS", []

    if is_void_type(ret):
        return "STUB_RET_VOID", []

    if is_const_char_ptr(ret):
        return "STUB_RET_CSTR", []

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

    return "UNSUPPORTED", []


# =========================================================
# Scenario generation
# =========================================================


def default_value_for_param(p: Param) -> str:
    t = normalize_type(p.type_str)

    if is_ptr_to_ptr(p):
        return f"&{p.name}_var"

    if is_plain_ptr(p):
        if is_const_char_ptr(t):
            return '"sample"'
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
            return f"char {name}_var[16] = {{0}};"
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


def make_default_scenarios(fn: FunctionProto, stub_tag: str, out_names: List[str]) -> List[dict]:
    fn_name = fn.name
    locals_list = make_locals(fn)
    call_args = make_call_args(fn)
    scenarios: List[dict] = []

    success_stub: Dict[str, str] = {}
    success_expect: Dict[str, object] = {}

    if is_status_type(fn.ret_type):
        success_stub[f"g_{fn_name}_ret"] = "OK"
        success_expect["status_eq"] = "OK"

        if stub_tag == "STUB_RET_STATUS_OUT1" and len(out_names) >= 1:
            success_stub[f"g_{fn_name}_out1"] = "(void*)0x1000"
            success_expect["ptr_eq"] = [f"{out_names[0]}_var", "(void*)0x1000"]

        if stub_tag == "STUB_RET_STATUS_OUT2" and len(out_names) >= 2:
            success_stub[f"g_{fn_name}_out1"] = "(void*)0x1000"
            success_stub[f"g_{fn_name}_out2"] = "(void*)0x2000"
            success_expect["ptr_eq_multi"] = [
                [f"{out_names[0]}_var", "(void*)0x1000"],
                [f"{out_names[1]}_var", "(void*)0x2000"],
            ]

    elif is_void_type(fn.ret_type):
        success_expect["call_cnt"] = 1

    elif is_const_char_ptr(fn.ret_type) or is_pointer_type(fn.ret_type):
        success_stub[f"g_{fn_name}_ret"] = "(void*)0x1000" if is_pointer_type(fn.ret_type) else '"sample"'
        if is_const_char_ptr(fn.ret_type):
            success_expect["ptr_ne"] = ["ret", "NULL"]
        else:
            success_expect["ptr_eq"] = ["ret", "(void*)0x1000"]

    elif is_u32_type(fn.ret_type):
        success_stub[f"g_{fn_name}_ret"] = "123U"
        success_expect["int_eq"] = ["ret", "123U"]

    elif is_u64_type(fn.ret_type):
        success_stub[f"g_{fn_name}_ret"] = "123ULL"
        success_expect["int_eq"] = ["ret", "123ULL"]

    elif is_size_type(fn.ret_type):
        success_stub[f"g_{fn_name}_ret"] = "123U"
        success_expect["int_eq"] = ["ret", "123U"]

    elif is_uptr_type(fn.ret_type):
        success_stub[f"g_{fn_name}_ret"] = "(uintptr_t)0x1000"
        success_expect["int_eq"] = ["ret", "(uintptr_t)0x1000"]

    success_expect["call_cnt"] = 1

    scenarios.append(
        {
            "name": "default_success",
            "enabled": True,
            "locals": locals_list,
            "stub": success_stub,
            "call_args": call_args,
            "expect": success_expect,
            "notes": "This is the editable default scenario.",
        }
    )

    if is_status_type(fn.ret_type):
        scenarios.append(
            {
                "name": "default_fail",
                "enabled": True,
                "locals": locals_list,
                "stub": {f"g_{fn_name}_ret": "ERR_UNSUPPORTED"},
                "call_args": call_args,
                "expect": {"status_eq": "ERR_UNSUPPORTED", "call_cnt": 1},
                "notes": "Change ERR_UNSUPPORTED to another code if needed.",
            }
        )

    return scenarios


def build_default_scenario_doc(header_path: str, funcs: List[FunctionProto], stub_header_suffix: str) -> dict:
    module = sanitize_basename(header_path)
    stub_header = f"{module}{stub_header_suffix}"
    stub_reset = f"{module}_stub_reset_all"

    functions = []
    for fn in funcs:
        tag, out_names = classify_stub_tag(fn)
        if tag == "UNSUPPORTED":
            continue

        functions.append(
            {
                "name": fn.name,
                "ret_type": fn.ret_type,
                "stub_tag": tag,
                "out_names": out_names,
                "params": [asdict(p) for p in fn.params],
                "enabled": True,
                "scenarios": make_default_scenarios(fn, tag, out_names),
            }
        )

    return {
        "module": module,
        "header": header_path.replace("\\", "/"),
        "stub_header": stub_header,
        "stub_reset": stub_reset,
        "functions": functions,
    }


def merge_scenarios(default_doc: dict, existing_doc: Optional[dict]) -> dict:
    if not existing_doc:
        return default_doc

    existing_map = {f.get("name"): f for f in existing_doc.get("functions", [])}
    merged_functions = []

    for new_f in default_doc.get("functions", []):
        name = new_f["name"]
        old_f = existing_map.get(name)
        if not old_f:
            merged_functions.append(new_f)
            continue

        merged_f = dict(new_f)
        merged_f["enabled"] = old_f.get("enabled", new_f.get("enabled", True))

        old_scen_map = {sc.get("name"): sc for sc in old_f.get("scenarios", [])}

        new_scenarios = []
        for new_sc in new_f.get("scenarios", []):
            old_sc = old_scen_map.get(new_sc["name"])
            if old_sc:
                merged_sc = dict(new_sc)
                for k, v in old_sc.items():
                    if k in {
                        "enabled",
                        "locals",
                        "stub",
                        "call_args",
                        "expect",
                        "notes",
                        "custom_lines",
                        "pre_call_lines",
                        "post_call_lines",
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
        "stub_header": existing_doc.get("stub_header", default_doc.get("stub_header")),
        "stub_reset": existing_doc.get("stub_reset", default_doc.get("stub_reset")),
        "functions": merged_functions,
    }


# =========================================================
# C code generation
# =========================================================


def c_escape_comment(s: str) -> str:
    return s.replace("*/", "* /")


def make_test_fn_name(fn_name: str, scen_name: str) -> str:
    return f"test_{fn_name}__{scen_name}"


def render_locals(locals_list: List[str]) -> List[str]:
    lines = []
    for item in locals_list:
        if not item.endswith(";"):
            item = item + ";"
        lines.append(f"    {item}")
    return lines


def render_stub_assignments(stub_dict: Dict[str, str]) -> List[str]:
    return [f"    {k} = {v};" for k, v in stub_dict.items()]


def render_asserts(expect: Dict[str, object], fn_name: str) -> List[str]:
    lines: List[str] = []

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
    if "ptr_eq_multi" in expect:
        for lhs, rhs in expect["ptr_eq_multi"]:
            lines.append(f"    assert_ptr_equal({lhs}, {rhs});")

    if "int_eq" in expect:
        lhs, rhs = expect["int_eq"]
        lines.append(f"    assert_int_equal({lhs}, {rhs});")
    if "int_ne" in expect:
        lhs, rhs = expect["int_ne"]
        lines.append(f"    assert_int_not_equal({lhs}, {rhs});")

    if "call_cnt" in expect:
        lines.append(f"    assert_int_equal(g_{fn_name}_call_cnt, {expect['call_cnt']});")

    return lines


def render_call(fn: dict) -> str:
    ret_type = fn["ret_type"]
    fn_name = fn["name"]
    args = fn.get("_current_call_args", [])

    call = f"{fn_name}({', '.join(args)})"
    if normalize_type(ret_type) == "void":
        return f"    {call};"

    if is_status_type(ret_type):
        return f"    status_t st = {call};"

    return f"    {ret_type} ret = {call};"


def emit_test_function(fn: dict, scenario: dict, stub_reset: str) -> str:
    fn_name = fn["name"]
    scen_name = scenario["name"]
    test_name = make_test_fn_name(fn_name, scen_name)
    notes = scenario.get("notes", "")
    locals_list = scenario.get("locals", [])
    stub_dict = scenario.get("stub", {})
    call_args = scenario.get("call_args", [])
    expect = scenario.get("expect", {})
    pre_call_lines = scenario.get("pre_call_lines", [])
    post_call_lines = scenario.get("post_call_lines", [])
    custom_lines = scenario.get("custom_lines", [])

    fn_copy = dict(fn)
    fn_copy["_current_call_args"] = call_args

    lines = []
    lines.append(f"void {test_name}(void **state)")
    lines.append("{")
    if notes:
        lines.append(f"    /* {c_escape_comment(notes)} */")
    lines.append("    (void)state;")

    if locals_list:
        lines.extend(render_locals(locals_list))
        lines.append("")

    lines.append(f"    {stub_reset}();")

    if stub_dict:
        lines.extend(render_stub_assignments(stub_dict))

    for line in pre_call_lines:
        lines.append(f"    {line.rstrip(';')};")

    if stub_dict or pre_call_lines:
        lines.append("")

    lines.append(render_call(fn_copy))

    for line in post_call_lines:
        lines.append(f"    {line.rstrip(';')};")

    assert_lines = render_asserts(expect, fn_name)
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
    reg_name = f"register_test_{module}_stub_auto"
    lines.append(f"void {reg_name}(struct CMUnitTest* out, size_t* io, size_t cap)")
    lines.append("{")
    lines.append("    size_t i = *io;")
    lines.append("    (void)cap;")
    lines.append("")

    for fn in scenario_doc.get("functions", []):
        if not fn.get("enabled", True):
            continue
        for sc in fn.get("scenarios", []):
            if not sc.get("enabled", True):
                continue
            tname = make_test_fn_name(fn["name"], sc["name"])
            lines.append(
                f'    if (i < cap) out[i++] = (struct CMUnitTest){{ "{tname}", {tname}, NULL, NULL, NULL }};'
            )

    lines.append("")
    lines.append("    *io = i;")
    lines.append("    return;")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def emit_test_c(
    scenario_doc: dict,
    include_root: Optional[str],
    test_tools_header: str,
    stub_include_prefix: str,
) -> str:
    module = scenario_doc["module"]
    header_inc = rel_include(scenario_doc["header"], include_root)
    stub_header = scenario_doc["stub_header"]
    stub_reset = scenario_doc["stub_reset"]

    lines = []
    lines.append("#include <stdarg.h>")
    lines.append("#include <stddef.h>")
    lines.append("#include <setjmp.h>")
    lines.append("#include <cmocka.h>")
    lines.append("")
    lines.append(f'#include "{test_tools_header}"')
    lines.append(f'#include "{header_inc}"')
    if stub_include_prefix:
        lines.append(f'#include "{stub_include_prefix.rstrip("/")}/{stub_header}"')
    else:
        lines.append(f'#include "{stub_header}"')
    lines.append("")
    lines.append("/*")
    lines.append(" * Auto-generated file.")
    lines.append(" * Edit the scenario JSON, then regenerate this file.")
    lines.append(" * Avoid manual edits here unless you accept regeneration overwrite.")
    lines.append(" */")
    lines.append("")

    for fn in scenario_doc.get("functions", []):
        if not fn.get("enabled", True):
            continue
        for sc in fn.get("scenarios", []):
            if not sc.get("enabled", True):
                continue
            lines.append(emit_test_function(fn, sc, stub_reset))

    lines.append(emit_register_function(module, scenario_doc))
    return "\n".join(lines)


# =========================================================
# Main flow
# =========================================================


def build_default_docs_for_header(header_path: str, stub_header_suffix: str) -> dict:
    text = read_file(header_path)
    protos = parse_prototypes(text, header_path)
    return build_default_scenario_doc(
        header_path=header_path,
        funcs=protos,
        stub_header_suffix=stub_header_suffix,
    )


def generate_for_header(
    header_path: str,
    scenario_dir: str,
    test_out_dir: str,
    include_root: Optional[str],
    stub_include_prefix: str,
    stub_header_suffix: str,
    test_tools_header: str,
    emit_summary: bool = False,
) -> Tuple[bool, int]:
    default_doc = build_default_docs_for_header(header_path, stub_header_suffix)
    module = default_doc["module"]

    if not default_doc["functions"]:
        if emit_summary:
            eprint(f"[skip] {header_path}: no supported prototypes")
        return False, 0

    scenario_path = os.path.join(scenario_dir, f"{module}.scenario.json")
    existing_doc = read_json(scenario_path) if os.path.exists(scenario_path) else None
    merged_doc = merge_scenarios(default_doc, existing_doc)

    write_json(scenario_path, merged_doc)

    test_c = emit_test_c(merged_doc, include_root, test_tools_header, stub_include_prefix)
    test_path = os.path.join(test_out_dir, f"test_{module}_stub_auto.c")
    write_file(test_path, test_c)

    enabled_test_count = 0
    for fn in merged_doc.get("functions", []):
        if not fn.get("enabled", True):
            continue
        for sc in fn.get("scenarios", []):
            if sc.get("enabled", True):
                enabled_test_count += 1

    if emit_summary:
        eprint(f"[ok] {header_path}")
        eprint(f"     scenario : {scenario_path}")
        eprint(f"     test     : {test_path}")
        eprint(f"     tests    : {enabled_test_count}")

    return True, enabled_test_count


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Generate editable scenario JSON and cmocka auto test templates from C headers."
    )
    ap.add_argument("input_path", help="Header file or directory containing .h files")
    ap.add_argument("--scenario-dir", default="tests/scenarios", help="Directory for editable scenario JSON files")
    ap.add_argument("--out-dir", default="tests/auto", help="Directory for generated test_<module>_stub_auto.c files")
    ap.add_argument("--include-root", default=None, help="Include root for original header include paths")
    ap.add_argument(
        "--stub-include-prefix",
        default="",
        help='Prefix for generated stub header include, e.g. "stub/generated"',
    )
    ap.add_argument(
        "--stub-header-suffix",
        default="_stub.h",
        help='Suffix for generated stub header include, default: "_stub.h"',
    )
    ap.add_argument(
        "--test-tools-header",
        default="test_tools.h",
        help='Header path to include for TEST_TOOLS_H macros, e.g. "tests/test_tools.h"',
    )
    ap.add_argument("--emit-summary", action="store_true", help="Print summary logs to stderr")
    return ap.parse_args()


def main() -> int:
    args = parse_args()

    headers = list_header_files(args.input_path)
    if not headers:
        eprint(f"No header files found: {args.input_path}")
        return 1

    total_headers = 0
    total_tests = 0

    for header in headers:
        ok, count = generate_for_header(
            header_path=header,
            scenario_dir=args.scenario_dir,
            test_out_dir=args.out_dir,
            include_root=args.include_root,
            stub_include_prefix=args.stub_include_prefix,
            stub_header_suffix=args.stub_header_suffix,
            test_tools_header=args.test_tools_header,
            emit_summary=args.emit_summary,
        )
        if ok:
            total_headers += 1
            total_tests += count

    if args.emit_summary:
        eprint("")
        eprint("==== Summary ====")
        eprint(f"Headers generated : {total_headers}")
        eprint(f"Tests generated   : {total_tests}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
