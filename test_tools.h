#ifndef TEST_TOOLS_H
#define TEST_TOOLS_H

#include "cortex/port/status.h"
#include <stddef.h>
#include <stdint.h>


void test_alloc_fail_after(int n);
void test_alloc_reset(void);


/* =========================================================
 * TAG TOKENS (do NOT assign numbers)
 * - Use these tokens directly in LIST_ALL.
 * ========================================================= */
#define STUB_RET_STATUS  STUB_RET_STATUS   /* status_t */
#define STUB_RET_VOID    STUB_RET_VOID     /* void */
#define STUB_RET_CSTR    STUB_RET_CSTR     /* const char* */
#define STUB_RET_PTR     STUB_RET_PTR      /* any pointer return */
#define STUB_RET_INT     STUB_RET_INT
#define STUB_RET_U32     STUB_RET_U32
#define STUB_RET_U64     STUB_RET_U64
#define STUB_RET_SIZE    STUB_RET_SIZE
#define STUB_RET_UPTR    STUB_RET_UPTR
/* status_t + set *out1 / *out2 */
#define STUB_RET_STATUS_OUT1 STUB_RET_STATUS_OUT1
#define STUB_RET_STATUS_OUT2 STUB_RET_STATUS_OUT2

/* =========================================================
 * Counters
 * ========================================================= */
#define STUB_DECL_COUNTER(TAG, fn) extern int g_##fn##_call_cnt;
#define STUB_DEF_COUNTER(TAG, fn)  int g_##fn##_call_cnt = 0;
#define STUB_RESET_COUNTER(TAG, fn) do { g_##fn##_call_cnt = 0; } while (0)

/* =========================================================
 * Ret knob declarations/definitions/resets by TAG
 * NOTE: VOID has no ret knob.
 * ========================================================= */
#define STUB_DECL_RET(TAG, fn, ret_type) STUB_DECL_RET_##TAG(fn, ret_type)
#define STUB_DEF_RET(TAG, fn, ret_type)  STUB_DEF_RET_##TAG(fn, ret_type)
#define STUB_RESET_RET(TAG, fn, ret_type) STUB_RESET_RET_##TAG(fn, ret_type)

/* STATUS */
#define STUB_DECL_RET_STUB_RET_STATUS(fn, ret_type) extern status_t g_##fn##_ret;
#define STUB_DEF_RET_STUB_RET_STATUS(fn, ret_type)  status_t g_##fn##_ret = OK;
#define STUB_RESET_RET_STUB_RET_STATUS(fn, ret_type) do { g_##fn##_ret = OK; } while (0)

/* VOID */
#define STUB_DECL_RET_STUB_RET_VOID(fn, ret_type)   /* none */
#define STUB_DEF_RET_STUB_RET_VOID(fn, ret_type)    /* none */
#define STUB_RESET_RET_STUB_RET_VOID(fn, ret_type)   do { } while (0)

/* const char* */
#define STUB_DECL_RET_STUB_RET_CSTR(fn, ret_type) extern const char* g_##fn##_ret;
#define STUB_DEF_RET_STUB_RET_CSTR(fn, ret_type)  const char* g_##fn##_ret = NULL;
#define STUB_RESET_RET_STUB_RET_CSTR(fn, ret_type)   do { g_##fn##_ret = NULL; } while (0)

/* pointer returns */
#define STUB_DECL_RET_STUB_RET_PTR(fn, ret_type)  extern void* g_##fn##_ret;
#define STUB_DEF_RET_STUB_RET_PTR(fn, ret_type)   void* g_##fn##_ret = NULL;
#define STUB_RESET_RET_STUB_RET_PTR(fn, ret_type)    do { g_##fn##_ret = NULL; } while (0)

/* integers */
#define STUB_DECL_RET_STUB_RET_INT(fn, ret_type) extern int g_##fn##_ret;
#define STUB_DEF_RET_STUB_RET_INT(fn, ret_type)  int g_##fn##_ret = 0;
#define STUB_RESET_RET_STUB_RET_INT(fn, ret_type)    do { g_##fn##_ret = 0; } while (0)

#define STUB_DECL_RET_STUB_RET_U32(fn, ret_type) extern uint32_t g_##fn##_ret;
#define STUB_DEF_RET_STUB_RET_U32(fn, ret_type)  uint32_t g_##fn##_ret = 0U;
#define STUB_RESET_RET_STUB_RET_U32(fn, ret_type)    do { g_##fn##_ret = 0U; } while (0)

#define STUB_DECL_RET_STUB_RET_U64(fn, ret_type) extern uint64_t g_##fn##_ret;
#define STUB_DEF_RET_STUB_RET_U64(fn, ret_type)  uint64_t g_##fn##_ret = 0ULL;
#define STUB_RESET_RET_STUB_RET_U64(fn, ret_type)    do { g_##fn##_ret = 0ULL; } while (0)

#define STUB_DECL_RET_STUB_RET_UPTR(fn, ret_type) extern uintptr_t g_##fn##_ret;
#define STUB_DEF_RET_STUB_RET_UPTR(fn, ret_type)  uintptr_t g_##fn##_ret = (uintptr_t)0;
#define STUB_RESET_RET_STUB_RET_UPTR(fn, ret_type) do { g_##fn##_ret = (uintptr_t)0; } while (0)

#define STUB_DECL_RET_STUB_RET_SIZE(fn, ret_type) extern size_t g_##fn##_ret;
#define STUB_DEF_RET_STUB_RET_SIZE(fn, ret_type)  size_t g_##fn##_ret = 0U;
#define STUB_RESET_RET_STUB_RET_SIZE(fn, ret_type)   do { g_##fn##_ret = 0U; } while (0)

/* For OUT tags we need extra knobs:
 *  - g_<fn>_out1 (void*)
 *  - g_<fn>_out2 (void*)
 */
#define STUB_DECL_OUT(TAG, fn) STUB_DECL_OUT_##TAG(fn)
#define STUB_DEF_OUT(TAG, fn)  STUB_DEF_OUT_##TAG(fn)
#define STUB_RESET_OUT(TAG, fn) STUB_RESET_OUT_##TAG(fn)

/* default: no out knobs */
#define STUB_DECL_OUT_STUB_RET_STATUS(fn)       /* none */
#define STUB_DEF_OUT_STUB_RET_STATUS(fn)        /* none */
#define STUB_RESET_OUT_STUB_RET_STATUS(fn)      ((void)0)

#define STUB_DECL_OUT_STUB_RET_VOID(fn)         /* none */
#define STUB_DEF_OUT_STUB_RET_VOID(fn)          /* none */
#define STUB_RESET_OUT_STUB_RET_VOID(fn)        ((void)0)

#define STUB_DECL_OUT_STUB_RET_CSTR(fn)         /* none */
#define STUB_DEF_OUT_STUB_RET_CSTR(fn)          /* none */
#define STUB_RESET_OUT_STUB_RET_CSTR(fn)        ((void)0)

#define STUB_DECL_OUT_STUB_RET_PTR(fn)          /* none */
#define STUB_DEF_OUT_STUB_RET_PTR(fn)           /* none */
#define STUB_RESET_OUT_STUB_RET_PTR(fn)         ((void)0)

#define STUB_DECL_OUT_STUB_RET_INT(fn)          /* none */
#define STUB_DEF_OUT_STUB_RET_INT(fn)           /* none */
#define STUB_RESET_OUT_STUB_RET_INT(fn)         ((void)0)

#define STUB_DECL_OUT_STUB_RET_U32(fn)          /* none */
#define STUB_DEF_OUT_STUB_RET_U32(fn)           /* none */
#define STUB_RESET_OUT_STUB_RET_U32(fn)         ((void)0)

#define STUB_DECL_OUT_STUB_RET_U64(fn)          /* none */
#define STUB_DEF_OUT_STUB_RET_U64(fn)           /* none */
#define STUB_RESET_OUT_STUB_RET_U64(fn)         ((void)0)

#define STUB_DECL_OUT_STUB_RET_SIZE(fn)         /* none */
#define STUB_DEF_OUT_STUB_RET_SIZE(fn)          /* none */
#define STUB_RESET_OUT_STUB_RET_SIZE(fn)        ((void)0)

#define STUB_DECL_OUT_STUB_RET_UPTR(fn)   /* none */
#define STUB_DEF_OUT_STUB_RET_UPTR(fn)    /* none */
#define STUB_RESET_OUT_STUB_RET_UPTR(fn)  ((void)0)

/* Treat OUT tags as status_t return knobs */
#define STUB_DECL_RET_STUB_RET_STATUS_OUT1(fn, ret_type) extern status_t g_##fn##_ret;
#define STUB_DEF_RET_STUB_RET_STATUS_OUT1(fn, ret_type)  status_t g_##fn##_ret = OK;
#define STUB_RESET_RET_STUB_RET_STATUS_OUT1(fn, ret_type) do { g_##fn##_ret = OK; } while (0)

#define STUB_DECL_RET_STUB_RET_STATUS_OUT2(fn, ret_type) extern status_t g_##fn##_ret;
#define STUB_DEF_RET_STUB_RET_STATUS_OUT2(fn, ret_type)  status_t g_##fn##_ret = OK;
#define STUB_RESET_RET_STUB_RET_STATUS_OUT2(fn, ret_type) do { g_##fn##_ret = OK; } while (0)

/* OUT1/OUT2 tags */
#define STUB_DECL_OUT_STUB_RET_STATUS_OUT1(fn)  extern void* g_##fn##_out1;
#define STUB_DEF_OUT_STUB_RET_STATUS_OUT1(fn)   void* g_##fn##_out1 = NULL;
#define STUB_RESET_OUT_STUB_RET_STATUS_OUT1(fn)      do { g_##fn##_out1 = NULL; } while (0)

#define STUB_DECL_OUT_STUB_RET_STATUS_OUT2(fn)  extern void* g_##fn##_out1; extern void* g_##fn##_out2;
#define STUB_DEF_OUT_STUB_RET_STATUS_OUT2(fn)   void* g_##fn##_out1 = NULL; void* g_##fn##_out2 = NULL;
#define STUB_RESET_OUT_STUB_RET_STATUS_OUT2(fn) do { g_##fn##_out1 = NULL; g_##fn##_out2 = NULL; } while (0)

/* =========================================================
 * Implementations by TAG
 * ========================================================= */
#define STUB_IMPL(TAG, ret_type, fn, args, names, names_n) \
    STUB_IMPL_##TAG(ret_type, fn, args, names, names_n)

/* STATUS */
#define STUB_IMPL_STUB_RET_STATUS(ret_type, fn, args, names, names_n) \
    ret_type fn args { g_##fn##_call_cnt++; STUB_VOIDIFY_N(names_n, names); return g_##fn##_ret; }

/* VOID */
#define STUB_IMPL_STUB_RET_VOID(ret_type, fn, args, names, names_n) \
    ret_type fn args { g_##fn##_call_cnt++; STUB_VOIDIFY_N(names_n, names); return; }
/* const char* */
#define STUB_IMPL_STUB_RET_CSTR(ret_type, fn, args, names, names_n) \
    ret_type fn args { g_##fn##_call_cnt++; STUB_VOIDIFY_N(names_n, names); return g_##fn##_ret; }

/* pointers */
#define STUB_IMPL_STUB_RET_PTR(ret_type, fn, args, names, names_n) \
    ret_type fn args { g_##fn##_call_cnt++; STUB_VOIDIFY_N(names_n, names); return (ret_type)g_##fn##_ret; }

/* ints */
#define STUB_IMPL_STUB_RET_INT(ret_type, fn, args, names, names_n) \
    ret_type fn args { g_##fn##_call_cnt++; STUB_VOIDIFY_N(names_n, names); return (ret_type)g_##fn##_ret; }

#define STUB_IMPL_STUB_RET_U32(ret_type, fn, args, names, names_n) \
    ret_type fn args { g_##fn##_call_cnt++; STUB_VOIDIFY_N(names_n, names); return (ret_type)g_##fn##_ret; }

#define STUB_IMPL_STUB_RET_U64(ret_type, fn, args, names, names_n) \
    ret_type fn args { g_##fn##_call_cnt++; STUB_VOIDIFY_N(names_n, names); return (ret_type)g_##fn##_ret; }

#define STUB_IMPL_STUB_RET_UPTR(ret_type, fn, args, names, names_n) \
    ret_type fn args { g_##fn##_call_cnt++; STUB_VOIDIFY_N(names_n, names); return (ret_type)g_##fn##_ret; }

#define STUB_IMPL_STUB_RET_SIZE(ret_type, fn, args, names, names_n) \
    ret_type fn args { g_##fn##_call_cnt++; STUB_VOIDIFY_N(names_n, names); return (ret_type)g_##fn##_ret; }

#define STUB_IMPL_STUB_RET_STATUS_OUT1(ret_type, fn, args, names, names_n) \
    ret_type fn args { \
        g_##fn##_call_cnt++; \
        STUB_VOIDIFY_N(names_n, names); \
        do { \
            void* _p = (void*)STUB_FIRST(names); \
            if (_p) { *(void**)_p = g_##fn##_out1; } \
        } while (0); \
        return g_##fn##_ret; \
    }

#define STUB_IMPL_STUB_RET_STATUS_OUT2(ret_type, fn, args, names, names_n) \
    ret_type fn args { \
        g_##fn##_call_cnt++; \
        STUB_VOIDIFY_N(names_n, names); \
        do { \
            void* _p1 = (void*)STUB_FIRST(names); \
            void* _p2 = (void*)STUB_SECOND(names); \
            if (_p1) { *(void**)_p1 = g_##fn##_out1; } \
            if (_p2) { *(void**)_p2 = g_##fn##_out2; } \
        } while (0); \
        return g_##fn##_ret; \
    }

/* Extract 1st / 2nd name from (a,b,c) tuple */
#define STUB_FIRST_(a, ...) a
#define STUB_SECOND_(a, b, ...) b
#define STUB_FIRST(names_tuple)  STUB_FIRST_ names_tuple
#define STUB_SECOND(names_tuple) STUB_SECOND_ names_tuple

/* token paste with expansion */
#define STUB_CAT(a,b)  STUB_CAT_I(a,b)
#define STUB_CAT_I(a,b) a##b

#define STUB_VOIDIFY_N(N, names_tuple) STUB_CAT(STUB_VOIDIFY_N_, N) names_tuple

#define STUB_VOIDIFY_N_0()              do { } while (0)
#define STUB_VOIDIFY_N_1(a)             do { (void)(a); } while (0)
#define STUB_VOIDIFY_N_2(a,b)           do { (void)(a); (void)(b); } while (0)
#define STUB_VOIDIFY_N_3(a,b,c)         do { (void)(a); (void)(b); (void)(c); } while (0)
#define STUB_VOIDIFY_N_4(a,b,c,d)       do { (void)(a); (void)(b); (void)(c); (void)(d); } while (0)
#define STUB_VOIDIFY_N_5(a,b,c,d,e)     do { (void)(a); (void)(b); (void)(c); (void)(d); (void)(e); } while (0)
#define STUB_VOIDIFY_N_6(a,b,c,d,e,f)   do { (void)(a); (void)(b); (void)(c); (void)(d); (void)(e); (void)(f); } while (0)
#define STUB_VOIDIFY_N_7(a,b,c,d,e,f,g) do { (void)(a); (void)(b); (void)(c); (void)(d); (void)(e); (void)(f); (void)(g); } while (0)


#endif /* TEST_TOOLS_H */
