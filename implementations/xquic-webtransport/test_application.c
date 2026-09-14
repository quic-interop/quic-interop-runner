/* Copyright (c) 2026, Alibaba Group Holding Limited. */

/* Keep callback ownership and filesystem tests outside the public library. */
#include "xqc_wt_interop.c"

static void xqc_wt_interop_assert(int condition, const char *name);
static void xqc_wt_interop_test_stream_ownership(void);
static void xqc_wt_interop_test_stream_bound(void);
static void xqc_wt_interop_test_file_confinement(void);

static void
xqc_wt_interop_assert(int condition, const char *name)
{
    if (!condition) {
        fprintf(stderr, "FAIL: %s\n", name);
        exit(1);
    }
}

static void
xqc_wt_interop_test_stream_ownership(void)
{
    unsigned char connection_data[64], before[64];
    int stream_marker, session_marker;
    xqc_wt_unistream_t *stream = (xqc_wt_unistream_t *) &stream_marker;
    xqc_wt_session_t *session = (xqc_wt_session_t *) &session_marker;

    memset(connection_data, 0xa5, sizeof(connection_data));
    memcpy(before, connection_data, sizeof(before));
    memset(&xqc_wt_interop, 0, sizeof(xqc_wt_interop));
    xqc_wt_interop_assert(xqc_wt_interop_stream_create(stream, session,
        connection_data) == XQC_OK, "incoming stream with connection data");
    xqc_wt_interop_stream_t *state = xqc_wt_interop_find(stream);
    xqc_wt_interop_assert(state && state->session == session
        && !state->sending && state->next == NULL,
        "incoming stream allocates owned callback state");
    xqc_wt_interop_assert(!memcmp(connection_data, before, sizeof(before)),
        "incoming stream preserves inherited connection data");
    state->complete = 1;
    xqc_wt_interop_stream_close(stream, session, connection_data);
    xqc_wt_interop_assert(xqc_wt_interop.streams == state && !state->stream,
        "closed state retained across synchronous callback unwinding");
    xqc_wt_interop_free_stream(state);

    state = xqc_wt_interop_allocate(session);
    xqc_wt_interop_assert(state != NULL, "allocate outgoing stream state");
    state->sending = 1;
    xqc_wt_interop_assert(xqc_wt_interop_stream_create(stream, session,
        state) == XQC_OK && xqc_wt_interop_find(stream) == state
        && state->next == NULL && state->sending,
        "outgoing stream reuses registered application state");
    xqc_wt_interop_free_stream(state);
}

static void
xqc_wt_interop_test_stream_bound(void)
{
    int session_marker;
    xqc_wt_session_t *session = (xqc_wt_session_t *) &session_marker;

    memset(&xqc_wt_interop, 0, sizeof(xqc_wt_interop));
    for (size_t i = 0; i < XQC_WT_INTEROP_STREAMS_MAX; i++) {
        xqc_wt_interop_assert(xqc_wt_interop_allocate(session) != NULL,
            "session accepts bounded GET and PUSH stream states");
    }
    xqc_wt_interop_assert(xqc_wt_interop_allocate(session) == NULL
        && xqc_wt_interop.stream_count == XQC_WT_INTEROP_STREAMS_MAX,
        "reject stream beyond session memory bound");
    while (xqc_wt_interop.streams) {
        xqc_wt_interop_free_stream(xqc_wt_interop.streams);
    }
    xqc_wt_interop_assert(xqc_wt_interop.stream_count == 0,
        "session cleanup releases every counted state");
    xqc_wt_interop_stream_t *state = xqc_wt_interop_allocate(session);
    xqc_wt_interop_assert(state != NULL,
        "allocation available after previous session cleanup");
    xqc_wt_interop_free_stream(state);
}

static void
xqc_wt_interop_test_file_confinement(void)
{
    char directory[] = "/tmp/xqc-wt-interop-unit-XXXXXX";
    char *root = mkdtemp(directory);

    xqc_wt_interop_assert(root != NULL, "create isolated fixture directory");
    int parent = open(root, O_RDONLY | O_DIRECTORY);
    xqc_wt_interop_assert(parent >= 0, "open fixture root");
    int file = xqc_wt_interop_open_file(parent, "nested/file.bin", 1);
    xqc_wt_interop_assert(file >= 0 && write(file, "\0\xff", 2) == 2,
        "write confined nested binary file");
    close(file);
    file = xqc_wt_interop_open_file(parent, "nested/file.bin", 0);
    unsigned char bytes[2];
    xqc_wt_interop_assert(file >= 0 && read(file, bytes, 2) == 2
        && bytes[0] == 0 && bytes[1] == 0xff,
        "read exact confined binary file");
    close(file);
    xqc_wt_interop_assert(xqc_wt_interop_open_file(parent,
        "nested/file.bin", 1) < 0, "do not overwrite existing download");
    xqc_wt_interop_assert(xqc_wt_interop_open_file(parent,
        "../escape.bin", 1) < 0, "reject parent traversal");
    xqc_wt_interop_assert(symlinkat("nested", parent, "alias") == 0,
        "create directory symlink fixture");
    xqc_wt_interop_assert(xqc_wt_interop_open_file(parent,
        "alias/file.bin", 0) < 0, "do not follow directory symlink");
    xqc_wt_interop_assert(symlinkat("nested/file.bin", parent, "link") == 0,
        "create leaf symlink fixture");
    xqc_wt_interop_assert(xqc_wt_interop_open_file(parent, "link", 0) < 0,
        "do not follow source file symlink");
    unlinkat(parent, "link", 0);
    unlinkat(parent, "alias", 0);
    unlinkat(parent, "nested/file.bin", 0);
    unlinkat(parent, "nested", AT_REMOVEDIR);
    close(parent);
    rmdir(root);
}

int
main(void)
{
    xqc_wt_interop_test_stream_ownership();
    xqc_wt_interop_test_stream_bound();
    xqc_wt_interop_test_file_confinement();
    puts("PASS: interop callback ownership and file confinement");
    return 0;
}
