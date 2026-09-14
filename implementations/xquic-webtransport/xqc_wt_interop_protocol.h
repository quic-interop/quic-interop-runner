/* Copyright (c) 2026, Alibaba Group Holding Limited. */

#ifndef XQC_WT_INTEROP_PROTOCOL_H
#define XQC_WT_INTEROP_PROTOCOL_H

#include <stddef.h>

#define XQC_WT_INTEROP_PATH_MAX 1024
#define XQC_WT_INTEROP_PROTOCOL_MAX 1024

typedef struct {
    char    line[XQC_WT_INTEROP_PATH_MAX + 6];
    size_t  length;
    int     complete;
} xqc_wt_interop_header_t;

int xqc_wt_interop_valid_path(const char *path);
int xqc_wt_interop_header_feed(xqc_wt_interop_header_t *header,
    const void *data, size_t length, int fin, int push, size_t *consumed);
int xqc_wt_interop_select_protocol(const char *value, size_t length,
    const char *const *protocols, size_t count, char *selected,
    size_t capacity);

#endif
