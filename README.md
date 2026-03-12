# test-automation

C 헤더 파일에서 [cmocka](https://cmocka.org/) 기반 테스트 코드와 스텁(stub)을 자동 생성하는 Python 툴체인입니다.

---

## 개요

헤더 파일을 입력받아 아래 두 가지 테스트 경로를 완전히 자동 생성합니다.

```
.h 헤더
  │
  ├─▶ [Path A] gen_test_stubs.py
  │       └─▶ *_stub.h / *_stub.c         (의존성 목(mock) 구현체)
  │
  ├─▶ [Path B-1] gen_test_stub_templates.py
  │       └─▶ test_<module>_stub_auto.c   (스텁 기반 API 호출자 테스트)
  │           <module>.scenario.json      (편집 가능한 시나리오)
  │
  └─▶ [Path C] gen_test_real_templates.py
          └─▶ test_<module>_real_auto.c   (실제 구현 단위 테스트)
              <module>.real.scenario.json
              runner_<module>_real.c
              Makefile.<module>.real
```

---

## 파일 구조

```
test-automation/
├── generators/
│   ├── c_proto_parser.py           # C 헤더 프로토타입 파서 (공유 라이브러리)
│   ├── gen_test_stubs.py           # *_stub.h / *_stub.c 생성기
│   ├── gen_test_stub_templates.py  # 스텁 기반 cmocka 테스트 템플릿 생성기
│   └── gen_test_real_templates.py  # 실제 구현 cmocka 테스트 템플릿 생성기
├── tests/
│   └── test_prototype_parser_regression.py  # 파서 회귀 테스트
├── include/
│   └── test_tools.h                # C 스텁 매크로 인프라
└── README.md
```

---

## 핵심 컴포넌트

### `generators/c_proto_parser.py`

C 헤더를 파싱하는 공유 라이브러리입니다. `gen_test_stubs.py`와 `gen_test_real_templates.py`가 의존합니다.

**동작 방식:**
1. 주석(`/* */`, `//`) 제거
2. 전처리기 지시자(`#define`, `#ifdef` 등) 제거
3. `extern "C" {}` 블록 정규화
4. `static inline` 함수 정의 제거 (선언이 아닌 정의이므로 스킵)
5. `;` 기준으로 최상위 선언 청크 분리 (중괄호 내부 스킵)
6. 각 청크를 `ParsedPrototype(ret_type, name, params)` 로 변환

**스킵 대상:** `typedef`, `struct/enum/union`, 가변인자(`...`), 함수 포인터 파라미터, 제어문 키워드

---

### `generators/gen_test_stubs.py`

헤더의 모든 함수 프로토타입에 대해 `test_tools.h` 매크로 기반의 스텁 파일을 생성합니다.

**반환 타입별 스텁 태그 분류:**

| 반환 타입 | 태그 |
|---|---|
| `status_t` | `STUB_RET_STATUS` |
| `status_t` + `T**` out 파라미터 1개 | `STUB_RET_STATUS_OUT1` |
| `status_t` + `T**` out 파라미터 2개 | `STUB_RET_STATUS_OUT2` |
| `void` | `STUB_RET_VOID` |
| `const char*` | `STUB_RET_CSTR` |
| `int` | `STUB_RET_INT` |
| `uint32_t` | `STUB_RET_U32` |
| `uint64_t` | `STUB_RET_U64` |
| `size_t` | `STUB_RET_SIZE` |
| `uintptr_t` | `STUB_RET_UPTR` |
| 기타 포인터 | `STUB_RET_PTR` |

**생성 파일 예시** (`foo.h` → `foo_stub.h` + `foo_stub.c`):
```c
// foo_stub.h
STUB_DECL_COUNTER(STUB_RET_STATUS, foo_init)
STUB_DECL_RET(STUB_RET_STATUS, foo_init, status_t)
STUB_DECL_OUT(STUB_RET_STATUS, foo_init)

void foo_stub_reset_all(void);

// foo_stub.c
STUB_DEF_COUNTER(STUB_RET_STATUS, foo_init)
STUB_DEF_RET(STUB_RET_STATUS, foo_init, status_t)
STUB_IMPL(STUB_RET_STATUS, status_t, foo_init, (void), (), 0)
```

**사용법:**
```bash
python -m generators.gen_test_stubs <헤더파일_또는_디렉토리> \
    --out-dir generated_stubs \
    --include-root src/include \
    --test-tools-header include/test_tools.h \
    --emit-summary
```

---

### `generators/gen_test_stub_templates.py`

스텁 노브(knob)를 조작하는 cmocka 테스트 함수를 자동 생성합니다.
**시나리오 JSON** 을 중간 편집 레이어로 두어, 재생성 시 수동 편집 내용이 보존됩니다.

**생성 흐름:**
```
헤더 파싱
  → 기본 시나리오 생성 (default_success / default_fail)
  → 기존 .scenario.json 이 있으면 병합 (수동 편집 보존)
  → test_<module>_stub_auto.c 생성
```

**생성되는 테스트 함수 구조:**
```c
void test_foo_init__default_success(void **state)
{
    /* This is the editable default scenario. */
    (void)state;

    foo_stub_reset_all();
    g_foo_init_ret = OK;

    status_t st = foo_init();

    assert_int_equal(st, OK);
    assert_int_equal(g_foo_init_call_cnt, 1);
    return;
}
```

**시나리오 JSON 구조 (`<module>.scenario.json`):**
```json
{
  "module": "foo",
  "stub_header": "foo_stub.h",
  "functions": [{
    "name": "foo_init",
    "enabled": true,
    "scenarios": [{
      "name": "default_success",
      "enabled": true,
      "locals": [],
      "stub": { "g_foo_init_ret": "OK" },
      "call_args": [],
      "expect": { "status_eq": "OK", "call_cnt": 1 }
    }]
  }]
}
```

**사용법:**
```bash
python -m generators.gen_test_stub_templates <헤더파일_또는_디렉토리> \
    --scenario-dir tests/scenarios \
    --out-dir tests/auto \
    --include-root src/include \
    --stub-include-prefix generated_stubs \
    --test-tools-header include/test_tools.h \
    --emit-summary
```

---

### `generators/gen_test_real_templates.py`

실제 `.c` 구현 파일을 분석하여 **실제 구현 단위 테스트**를 생성합니다.
소스 파일 내에서 호출하는 외부 함수를 정적 분석하고, 해당 의존성에 대한 스텁을 자동으로 링크합니다.

**추가 기능 (stub_templates 대비):**
- `.c` 소스 바디 분석 → 호출되는 의존 함수 자동 탐지
- 생성된 `*_stub.h` 인덱스 탐색 → 의존성 스텁 헤더/소스 자동 매핑
- `#include` 추이 분석으로 누락된 스텁 보완
- `runner_<module>_real.c` (cmocka main 러너) 생성
- `Makefile.<module>.real` 생성 (컴파일 커맨드 포함)

**생성 파일:**

| 파일 | 설명 |
|---|---|
| `<module>.real.scenario.json` | 편집 가능한 시나리오 (병합 안전) |
| `test_<module>_real_auto.c` | cmocka 테스트 함수 |
| `runner_<module>_real.c` | cmocka main 진입점 |
| `Makefile.<module>.real` | 빌드 규칙 |

**사용법:**
```bash
python -m generators.gen_test_real_templates <헤더파일_또는_디렉토리> \
    --source-root src \
    --scenario-dir tests/scenarios \
    --out-dir tests/auto \
    --include-root src/include \
    --stub-generated-dir generated_stubs \
    --test-tools-header include/test_tools.h \
    --emit-summary
```

---

### `include/test_tools.h`

Python 생성기가 의존하는 C 매크로 인프라입니다. 각 스텁 함수에 아래 세 가지 "노브(knob)"를 제공합니다.

| 노브 | 전역 변수 | 역할 |
|---|---|---|
| Counter | `g_<fn>_call_cnt` | 호출 횟수 추적 |
| Ret | `g_<fn>_ret` | 반환값 제어 |
| Out | `g_<fn>_out1`, `g_<fn>_out2` | `T**` 출력 파라미터 제어 |

**매크로 흐름:**
```
STUB_IMPL(TAG, ret_type, fn, args, names, n)
  └─▶ STUB_IMPL_<TAG>(...)
        ├─▶ g_fn_call_cnt++
        ├─▶ STUB_VOIDIFY_N(n, names)   // unused-param 경고 억제
        ├─▶ [OUT 태그] *(void**)out = g_fn_out1
        └─▶ return g_fn_ret
```

---

## 전체 워크플로 예시

```bash
# 1. 의존성 스텁 생성
python -m generators.gen_test_stubs src/include/ \
    --out-dir generated_stubs \
    --include-root src/include \
    --test-tools-header include/test_tools.h

# 2-A. 스텁 기반 테스트 생성 (API 호출자 테스트)
python -m generators.gen_test_stub_templates src/include/foo.h \
    --scenario-dir tests/scenarios \
    --out-dir tests/auto \
    --stub-include-prefix generated_stubs \
    --test-tools-header include/test_tools.h

# 2-B. 실제 구현 단위 테스트 생성
python -m generators.gen_test_real_templates src/include/foo.h \
    --source-root src \
    --scenario-dir tests/scenarios \
    --out-dir tests/auto \
    --stub-generated-dir generated_stubs \
    --test-tools-header include/test_tools.h

# 3. 시나리오 JSON 편집 (선택) → 재생성해도 편집 내용 보존됨
vim tests/scenarios/foo.scenario.json

# 4. 재생성 (편집 내용 병합)
python -m generators.gen_test_stub_templates src/include/foo.h ...
```

---

## 파서 회귀 테스트 실행

```bash
python tests/test_prototype_parser_regression.py
# → regression parser checks passed
```

---

## 지원 반환 타입 / 스킵 대상

**지원:**
`void`, `status_t`, `int`, `uint32_t`, `uint64_t`, `size_t`, `uintptr_t`, `const char*`, 포인터 반환형

**자동 스킵:**
- 가변인자 함수 (`...`)
- 함수 포인터 파라미터
- `static inline` 함수 정의
- `typedef` / `struct` / `enum` / `union` 선언
- 기타 스칼라 반환 타입 (예: `double`, 커스텀 enum 등)
