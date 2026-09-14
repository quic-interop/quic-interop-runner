/* Copyright (c) 2026, Alibaba Group Holding Limited. */

#include <string.h>
#include "xqc_wt_interop_protocol.h"

static int xqc_wt_interop_string(const char **cursor, const char *end,
    char *output, size_t capacity);
static int xqc_wt_interop_parameters(const char **cursor, const char *end);
static int xqc_wt_interop_key_char(unsigned char ch, int first);
static int xqc_wt_interop_bare_item(const char *start, const char *end);
static int xqc_wt_interop_valid_utf8(const unsigned char *data, size_t length);
static int xqc_wt_interop_display_string(const char **cursor,
    const char *end);

int
xqc_wt_interop_valid_path(const char *path)
{
    const char *start = path;
    size_t length = strlen(path);

    if (!length || length > XQC_WT_INTEROP_PATH_MAX) {
        return 0;
    }
    for (const char *p = path; ; p++) {
        unsigned char ch = *p;
        if (ch == '/' || ch == '\0') {
            size_t part = p - start;
            if (!part || part > 255 || (part == 1 && start[0] == '.')
                || (part == 2 && start[0] == '.' && start[1] == '.'))
            {
                return 0;
            }
            if (!ch) {
                return 1;
            }
            start = p + 1;

        } else if (!((ch >= 'a' && ch <= 'z')
                     || (ch >= 'A' && ch <= 'Z')
                     || (ch >= '0' && ch <= '9')
                     || ch == '.' || ch == '_' || ch == '-'))
        {
            return 0;
        }
    }
}

int
xqc_wt_interop_header_feed(xqc_wt_interop_header_t *header,
    const void *data, size_t length, int fin, int push, size_t *consumed)
{
    const unsigned char *bytes = data;
    const char *prefix = push ? "PUSH " : "GET ";
    size_t prefix_length = strlen(prefix);

    *consumed = 0;
    if (header->complete) {
        return 1;
    }
    while (*consumed < length) {
        unsigned char ch = bytes[(*consumed)++];
        if (push && ch == '\n') {
            header->complete = 1;
            break;
        }
        if (ch < 0x20 || ch > 0x7e
            || header->length == sizeof(header->line) - 1)
        {
            return -1;
        }
        header->line[header->length++] = ch;
    }
    header->line[header->length] = '\0';
    if (!push && fin) {
        header->complete = 1;
    }
    if (!header->complete) {
        return fin ? -1 : 0;
    }
    if (header->length <= prefix_length
        || memcmp(header->line, prefix, prefix_length)
        || !xqc_wt_interop_valid_path(header->line + prefix_length))
    {
        return -1;
    }
    return 1;
}

static int
xqc_wt_interop_string(const char **cursor, const char *end,
    char *output, size_t capacity)
{
    const char *p = *cursor;
    size_t used = 0;

    if (p == end || *p++ != '"') {
        return -1;
    }
    while (p != end) {
        unsigned char ch = *p++;
        if (ch == '"') {
            if (output) {
                output[used] = '\0';
            }
            *cursor = p;
            return 0;
        }
        if (ch == '\\') {
            if (p == end || (*p != '"' && *p != '\\')) {
                return -1;
            }
            ch = *p++;
        }
        if (ch < 0x20 || ch > 0x7e || (output && used + 1 >= capacity)) {
            return -1;
        }
        if (output) {
            output[used++] = ch;
        }
    }
    return -1;
}

static int
xqc_wt_interop_key_char(unsigned char ch, int first)
{
    return (ch >= 'a' && ch <= 'z') || ch == '*'
        || (!first && ((ch >= '0' && ch <= '9')
                      || ch == '_' || ch == '-' || ch == '.'));
}

static int
xqc_wt_interop_bare_item(const char *start, const char *end)
{
    const char *p = start;
    int date = *p == '@';

    if (*p == '?') {
        return end - p == 2 && (p[1] == '0' || p[1] == '1');
    }
    if (date) {
        p++;
    }
    if (p != end && (*p == '-' || (*p >= '0' && *p <= '9'))) {
        if (*p == '-') {
            p++;
        }
        const char *digits = p;
        while (p != end && *p >= '0' && *p <= '9') {
            p++;
        }
        size_t integral = p - digits;
        if (!integral || integral > 15) {
            return 0;
        }
        if (p == end) {
            return 1;
        }
        if (date || *p++ != '.' || integral > 12) {
            return 0;
        }
        digits = p;
        while (p != end && *p >= '0' && *p <= '9') {
            p++;
        }
        return p == end && p - digits >= 1 && p - digits <= 3;
    }
    if (date || p == end
        || !((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z')
             || *p == '*'))
    {
        return 0;
    }
    for (; p != end; p++) {
        if (!((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z')
              || (*p >= '0' && *p <= '9')
              || strchr("!#$%&'*+-.^_`|~:/", *p)))
        {
            return 0;
        }
    }
    return 1;
}

static int
xqc_wt_interop_valid_utf8(const unsigned char *data, size_t length)
{
    for (size_t i = 0; i < length;) {
        unsigned code = data[i++];
        unsigned count, minimum;
        if (code < 0x80) {
            continue;
        }
        if (code >= 0xc2 && code <= 0xdf) {
            count = 1;
            minimum = 0x80;
            code &= 0x1f;
        } else if (code >= 0xe0 && code <= 0xef) {
            count = 2;
            minimum = 0x800;
            code &= 0x0f;
        } else if (code >= 0xf0 && code <= 0xf4) {
            count = 3;
            minimum = 0x10000;
            code &= 0x07;
        } else {
            return 0;
        }
        if (length - i < count) {
            return 0;
        }
        while (count--) {
            unsigned byte = data[i++];
            if ((byte & 0xc0) != 0x80) {
                return 0;
            }
            code = (code << 6) | (byte & 0x3f);
        }
        if (code < minimum || code > 0x10ffff
            || (code >= 0xd800 && code <= 0xdfff))
        {
            return 0;
        }
    }
    return 1;
}

static int
xqc_wt_interop_display_string(const char **cursor, const char *end)
{
    const char *p = *cursor;
    unsigned char decoded[4096];
    size_t length = 0;

    if (++p == end || *p++ != '"') {
        return -1;
    }
    while (p != end && *p != '"') {
        unsigned char ch = *p++;
        if (ch < 0x20 || ch > 0x7e) {
            return -1;
        }
        if (ch == '%') {
            unsigned value = 0;
            for (unsigned i = 0; i < 2; i++) {
                if (p == end || !((*p >= '0' && *p <= '9')
                    || (*p >= 'a' && *p <= 'f')))
                {
                    return -1;
                }
                value = value * 16 + (*p <= '9'
                    ? *p - '0' : *p - 'a' + 10);
                p++;
            }
            ch = value;
        }
        if (length == sizeof(decoded)) {
            return -1;
        }
        decoded[length++] = ch;
    }
    if (p == end || !xqc_wt_interop_valid_utf8(decoded, length)) {
        return -1;
    }
    *cursor = p + 1;
    return 0;
}

static int
xqc_wt_interop_parameters(const char **cursor, const char *end)
{
    const char *p = *cursor;

    /* draft-ietf-webtrans-http3-16 Section 3.3 ignores SF parameters. */
    while (p != end && *p == ';') {
        p++;
        while (p != end && *p == ' ') {
            p++;
        }
        if (p == end || !xqc_wt_interop_key_char(*p++, 1)) {
            return -1;
        }
        while (p != end && xqc_wt_interop_key_char(*p, 0)) {
            p++;
        }
        if (p == end || *p != '=') {
            continue;
        }
        p++;
        if (p == end) {
            return -1;
        }
        if (*p == '"') {
            if (xqc_wt_interop_string(&p, end, NULL, 0)) {
                return -1;
            }

        } else if (*p == '%') {
            if (xqc_wt_interop_display_string(&p, end)) {
                return -1;
            }

        } else if (*p == ':') {
            size_t digits = 0, padding = 0;
            p++;
            while (p != end && *p != ':') {
                unsigned char ch = *p++;
                if (ch == '=') {
                    padding++;
                } else if (!padding && ((ch >= 'a' && ch <= 'z')
                    || (ch >= 'A' && ch <= 'Z')
                    || (ch >= '0' && ch <= '9') || ch == '+' || ch == '/'))
                {
                    digits++;
                } else {
                    return -1;
                }
            }
            if (p == end || digits % 4 == 1 || padding > 2
                || (padding && (digits + padding) % 4 != 0))
            {
                return -1;
            }
            p++;

        } else {
            const char *start = p;
            while (p != end && *p != ';' && *p != ',' && *p != ' '
                   && *p != '\t')
            {
                if ((unsigned char) *p < 0x21
                    || (unsigned char) *p > 0x7e || *p == '"'
                    || *p == '\\' || *p == '(' || *p == ')')
                {
                    return -1;
                }
                p++;
            }
            if (p == start || !xqc_wt_interop_bare_item(start, p)) {
                return -1;
            }
        }
    }
    *cursor = p;
    return 0;
}

int
xqc_wt_interop_select_protocol(const char *value, size_t length,
    const char *const *protocols, size_t count, char *selected,
    size_t capacity)
{
    const char *p = value;
    const char *end = value + length;
    char item[XQC_WT_INTEROP_PROTOCOL_MAX + 1];
    int found = 0;

    if (!capacity || !length || length > 4096) {
        return -1;
    }
    selected[0] = '\0';
    while (p != end && *p == ' ') {
        p++;
    }
    for (;;) {
        if (xqc_wt_interop_string(&p, end, item, sizeof(item))) {
            return -1;
        }
        for (size_t i = 0; !found && i < count; i++) {
            if (!strcmp(item, protocols[i])) {
                if (strlen(item) >= capacity) {
                    return -1;
                }
                strcpy(selected, item);
                found = 1;
            }
        }
        if (xqc_wt_interop_parameters(&p, end)) {
            return -1;
        }
        while (p != end && (*p == ' ' || *p == '\t')) {
            p++;
        }
        if (p == end) {
            return found;
        }
        if (*p++ != ',' || p == end) {
            return -1;
        }
        while (p != end && (*p == ' ' || *p == '\t')) {
            p++;
        }
    }
}
