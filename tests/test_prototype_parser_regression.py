#!/usr/bin/env python3

from generators.gen_test_real_templates import parse_prototypes as parse_real
from generators.gen_test_stubs import parse_prototypes as parse_stubs

HEADER = r'''
#ifndef LOGGER_H
#define LOGGER_H

#include <stdint.h>

typedef enum {
    LOG_ROLE_A = 0,
    LOG_ROLE_B,
} log_role_t;

#define LOG_WRAP(fmt, ...) \
    do { \
        log_impl((fmt), ##__VA_ARGS__); \
    } while (0)

#define LOG_SIMPLE(msg) do { log_impl((msg)); } while (0)

static inline unsigned long logctx_tid_ul(void) {
    return 0ul;
}

extern int global_value;
typedef int (*cb_t)(int);

void logctx_set(log_role_t role, int worker_id);
const char* logctx_role_str(void);
int logctx_worker_id(void);
status_t base_logger_init(const char* zlog_conf, const char* category);

#endif
'''

EXPECTED = {
    'logctx_set',
    'logctx_role_str',
    'logctx_worker_id',
    'base_logger_init',
}


def check(parse_fn, label: str):
    out = parse_fn(HEADER, 'logger.h')
    names = {p.name for p in out}

    assert names == EXPECTED, f"{label}: expected {EXPECTED}, got {names}"
    assert 'while' not in names, f"{label}: macro fragment parsed as function"
    assert 'logctx_tid_ul' not in names, f"{label}: static inline definition parsed as prototype"


if __name__ == '__main__':
    check(parse_stubs, 'stubs')
    check(parse_real, 'real_templates')
    print('regression parser checks passed')
