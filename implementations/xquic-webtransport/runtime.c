/* Copyright (c) 2026, Alibaba Group Holding Limited. */

#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
#include <event2/event.h>
#include <openssl/ssl.h>
#include <openssl/x509.h>
#include <xquic/xquic.h>
#include <xquic/xqc_http3.h>
#include "xqc_wt_interop.h"

typedef struct {
    struct event_base  *events;
    struct event       *timer;
    struct event       *reads[2];
    struct event       *writes[2];
    struct event       *stop;
    struct event       *timeout;
    xqc_engine_t       *engine;
    xqc_cid_t           cid;
    struct sockaddr_storage peer;
    socklen_t           peer_length;
    int                 sockets[2];
    int                 server;
    int                 draft;
    int                 port;
    int                 lifetime;
    int                 connected;
    int                 accepted;
    int                 stopping;
    int                 failed;
    char               *certificate;
    char               *private_key;
    const char         *ca;
    const char         *url;
    char                authority[512];
    char                hostname[256];
    char                path[1025];
    FILE               *log;
    FILE               *keys;
    xqc_log_level_t     log_level;
} xqc_interop_runtime_t;

static xqc_interop_runtime_t xqc_interop_runtime;

static xqc_usec_t xqc_interop_now(void);
static void xqc_interop_timer_set(xqc_usec_t delay, void *user_data);
static void xqc_interop_timer(int socket, short flags, void *user_data);
static void xqc_interop_schedule(void *user_data);
static void xqc_interop_finished(void *user_data);
static void xqc_interop_stop(int signal_number, short flags, void *user_data);
static void xqc_interop_timeout(int socket, short flags, void *user_data);
static void xqc_interop_log(xqc_log_level_t level, const void *data,
    size_t length, void *user_data);
static void xqc_interop_qlog(qlog_event_importance_t importance,
    const void *data, size_t length, void *user_data);
static void xqc_interop_keys(const xqc_cid_t *cid, const char *line,
    void *user_data);
static ssize_t xqc_interop_send(const unsigned char *data, size_t length,
    const struct sockaddr *peer, socklen_t peer_length, void *user_data);
static ssize_t xqc_interop_send_path(uint64_t path,
    const unsigned char *data, size_t length, const struct sockaddr *peer,
    socklen_t peer_length, void *user_data);
static void xqc_interop_read(int socket, short flags, void *user_data);
static void xqc_interop_write(int socket, short flags, void *user_data);
static int xqc_interop_accept(xqc_engine_t *engine, xqc_connection_t *conn,
    const xqc_cid_t *cid, void *user_data);
static int xqc_interop_verify(const unsigned char *certificates[],
    const size_t lengths[], size_t count, void *user_data);
static void xqc_interop_token(const unsigned char *token, uint32_t length,
    void *user_data);
static void xqc_interop_session(const char *data, size_t length,
    void *user_data);
static int xqc_interop_connection_create(xqc_h3_conn_t *connection,
    const xqc_cid_t *cid, void *user_data);
static int xqc_interop_connection_close(xqc_h3_conn_t *connection,
    const xqc_cid_t *cid, void *user_data);
static void xqc_interop_handshake(xqc_h3_conn_t *connection,
    void *user_data);
static void xqc_interop_cid(xqc_connection_t *connection,
    const xqc_cid_t *old_cid, const xqc_cid_t *new_cid, void *user_data);
static int xqc_interop_number(const char *text, int maximum);
static int xqc_interop_arguments(int argc, char **argv);
static int xqc_interop_url(void);
static int xqc_interop_socket(int family, int port);
static int xqc_interop_network(void);
static xqc_conn_settings_t xqc_interop_settings(void);
static int xqc_interop_engine(void);
static void xqc_interop_cleanup(void);

static xqc_usec_t
xqc_interop_now(void)
{
    struct timeval now;
    gettimeofday(&now, NULL);
    return (xqc_usec_t) now.tv_sec * 1000000 + now.tv_usec;
}

static void
xqc_interop_timer_set(xqc_usec_t delay, void *user_data)
{
    xqc_interop_runtime_t *ctx = user_data;
    struct timeval timeout = {delay / 1000000, delay % 1000000};

    event_add(ctx->timer, &timeout);
}

static void
xqc_interop_timer(int socket, short flags, void *user_data)
{
    xqc_interop_runtime_t *ctx = user_data;
    xqc_engine_main_logic(ctx->engine);
}

static void
xqc_interop_schedule(void *user_data)
{
    xqc_interop_timer_set(1000, user_data);
}

static void
xqc_interop_finished(void *user_data)
{
    xqc_interop_runtime_t *ctx = user_data;
    struct timeval grace = {0, 200000};

    event_base_loopexit(ctx->events, &grace);
}

static void
xqc_interop_stop(int signal_number, short flags, void *user_data)
{
    xqc_interop_runtime_t *ctx = user_data;
    ctx->stopping = 1;
    event_base_loopbreak(ctx->events);
}

static void
xqc_interop_timeout(int socket, short flags, void *user_data)
{
    xqc_interop_runtime_t *ctx = user_data;
    fprintf(stderr, "WebTransport endpoint timed out\n");
    ctx->failed = 1;
    event_base_loopbreak(ctx->events);
}

static void
xqc_interop_log(xqc_log_level_t level, const void *data, size_t length,
    void *user_data)
{
    xqc_interop_runtime_t *ctx = user_data;

    if (ctx->log) {
        fwrite(data, 1, length, ctx->log);
        fputc('\n', ctx->log);
    }
}

static void
xqc_interop_qlog(qlog_event_importance_t importance, const void *data,
    size_t length, void *user_data)
{
    xqc_interop_log(XQC_LOG_DEBUG, data, length, user_data);
}

static void
xqc_interop_keys(const xqc_cid_t *cid, const char *line, void *user_data)
{
    xqc_interop_runtime_t *ctx = user_data;

    if (ctx->keys) {
        fprintf(ctx->keys, "%s\n", line);
        fflush(ctx->keys);
    }
}

static ssize_t
xqc_interop_send(const unsigned char *data, size_t length,
    const struct sockaddr *peer, socklen_t peer_length, void *user_data)
{
    xqc_interop_runtime_t *ctx = &xqc_interop_runtime;
    int index = peer->sa_family == AF_INET6;
    ssize_t result;

    if (ctx->sockets[index] < 0) {
        return XQC_SOCKET_ERROR;
    }
    do {
        result = sendto(ctx->sockets[index], data, length, 0,
                        peer, peer_length);
    } while (result < 0 && errno == EINTR);
    if (result < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
        event_add(ctx->writes[index], NULL);
        return XQC_SOCKET_EAGAIN;
    }
    return result < 0 ? XQC_SOCKET_ERROR : result;
}

static ssize_t
xqc_interop_send_path(uint64_t path, const unsigned char *data,
    size_t length, const struct sockaddr *peer, socklen_t peer_length,
    void *user_data)
{
    return xqc_interop_send(data, length, peer, peer_length, user_data);
}

static void
xqc_interop_read(int socket, short flags, void *user_data)
{
    xqc_interop_runtime_t *ctx = user_data;
    unsigned char packet[65536];
    struct sockaddr_storage local, peer;
    socklen_t local_length = sizeof(local);

    if (getsockname(socket, (struct sockaddr *) &local, &local_length) < 0) {
        ctx->failed = 1;
        event_base_loopbreak(ctx->events);
        return;
    }
    for (;;) {
        socklen_t peer_length = sizeof(peer);
        ssize_t length = recvfrom(socket, packet, sizeof(packet), 0,
                                  (struct sockaddr *) &peer, &peer_length);
        if (length < 0) {
            if (errno == EINTR) {
                continue;
            }
            if (errno != EAGAIN && errno != EWOULDBLOCK) {
                perror("recvfrom");
                ctx->failed = 1;
                event_base_loopbreak(ctx->events);
            }
            break;
        }
        if (!length) {
            continue;
        }
        int result = xqc_engine_packet_process(ctx->engine, packet, length,
            (struct sockaddr *) &local, local_length,
            (struct sockaddr *) &peer, peer_length, xqc_interop_now(), ctx);
        if (result != XQC_OK) {
            fprintf(stderr, "QUIC packet rejected: %d\n", result);
        }
    }
    xqc_engine_finish_recv(ctx->engine);
}

static void
xqc_interop_write(int socket, short flags, void *user_data)
{
    xqc_interop_runtime_t *ctx = user_data;

    for (int i = 0; i < 2; i++) {
        if (ctx->sockets[i] == socket) {
            event_del(ctx->writes[i]);
        }
    }
    if (ctx->connected) {
        xqc_conn_continue_send(ctx->engine, &ctx->cid);
    }
    xqc_engine_main_logic(ctx->engine);
}

static int
xqc_interop_accept(xqc_engine_t *engine, xqc_connection_t *conn,
    const xqc_cid_t *cid, void *user_data)
{
    xqc_interop_runtime_t *ctx = user_data;

    if (ctx->accepted) {
        return XQC_ERROR;
    }
    ctx->accepted = 1;
    ctx->connected = 1;
    ctx->cid = *cid;
    xqc_conn_set_transport_user_data(conn, ctx);
    return XQC_OK;
}

static int
xqc_interop_verify(const unsigned char *certificates[],
    const size_t lengths[], size_t count, void *user_data)
{
    /* This runs only after normal chain/hostname verification fails. */
    return XQC_ERROR;
}

static void
xqc_interop_token(const unsigned char *token, uint32_t length,
    void *user_data)
{
    /* Each runner case uses a fresh 1-RTT connection. */
}

static void
xqc_interop_session(const char *data, size_t length, void *user_data)
{
    /* Session tickets and cached transport parameters are not reused. */
}

static int
xqc_interop_connection_create(xqc_h3_conn_t *connection,
    const xqc_cid_t *cid, void *user_data)
{
    xqc_interop_runtime_t *ctx = &xqc_interop_runtime;

    xqc_h3_conn_set_user_data(connection, ctx);
    if (ctx->server) {
        return XQC_OK;
    }
    SSL *ssl = xqc_h3_conn_get_ssl(connection);
    X509_STORE *store = X509_STORE_new();
    int valid = 0;
    if (ssl && store) {
        valid = ctx->ca ? X509_STORE_load_locations(store, ctx->ca, NULL)
            : X509_STORE_set_default_paths(store);
        if (valid == 1 && ctx->ca) {
            /* Local tests may explicitly trust the leaf; host checks remain. */
            valid = X509_VERIFY_PARAM_set_flags(SSL_get0_param(ssl),
                                                X509_V_FLAG_PARTIAL_CHAIN);
        }
        if (valid == 1) {
            valid = SSL_set1_verify_cert_store(ssl, store);
        }
    }
    X509_STORE_free(store);
    if (valid != 1) {
        fprintf(stderr, "WebTransport certificate trust setup failed\n");
        ctx->failed = 1;
        return XQC_ERROR;
    }
    return XQC_OK;
}

static int
xqc_interop_connection_close(xqc_h3_conn_t *connection,
    const xqc_cid_t *cid, void *user_data)
{
    xqc_interop_runtime_t *ctx = &xqc_interop_runtime;
    ctx->connected = 0;
    return XQC_OK;
}

static void
xqc_interop_handshake(xqc_h3_conn_t *connection, void *user_data)
{
    xqc_interop_runtime_t *ctx = &xqc_interop_runtime;

    if (!ctx->server) {
        if (xqc_demo_wt_client_open(connection, ctx->authority, ctx->path,
                                    NULL) != XQC_OK)
        {
            ctx->failed = 1;
        }
    }
}

static void
xqc_interop_cid(xqc_connection_t *connection, const xqc_cid_t *old_cid,
    const xqc_cid_t *new_cid, void *user_data)
{
    xqc_interop_runtime_t *ctx = &xqc_interop_runtime;
    ctx->cid = *new_cid;
}

static int
xqc_interop_number(const char *text, int maximum)
{
    char *end;
    errno = 0;
    long value = strtol(text, &end, 10);
    return !errno && *text && !*end && value > 0 && value <= maximum
        ? (int) value : -1;
}

static int
xqc_interop_arguments(int argc, char **argv)
{
    xqc_interop_runtime_t *ctx = &xqc_interop_runtime;
    const char *role = getenv("ROLE");
    int option;

    if (!role || (strcmp(role, "client") && strcmp(role, "server"))) {
        return -1;
    }
    ctx->server = !strcmp(role, "server");
    ctx->draft = 16;
    ctx->port = 443;
    ctx->lifetime = 45;
    ctx->log_level = XQC_LOG_INFO;
    while ((option = getopt(argc, argv, "Wv:l:L:k:U:J:K:p:T:")) != -1) {
        switch (option) {
        case 'W':
            break;
        case 'v':
            ctx->draft = xqc_interop_number(optarg, 16);
            if (ctx->draft != 7 && ctx->draft != 16) {
                return -1;
            }
            break;
        case 'l':
            ctx->log_level = *optarg == 'd' ? XQC_LOG_DEBUG
                : *optarg == 'e' ? XQC_LOG_ERROR : XQC_LOG_INFO;
            break;
        case 'L':
            if (ctx->log || !(ctx->log = fopen(optarg, "a"))) {
                return -1;
            }
            break;
        case 'k':
            if (ctx->keys || !(ctx->keys = fopen(optarg, "a"))) {
                return -1;
            }
            break;
        case 'U':
            ctx->url = optarg;
            break;
        case 'J':
            ctx->ca = optarg;
            break;
        case 'K':
            if (ctx->server) {
                ctx->private_key = optarg;
            } else {
                ctx->lifetime = xqc_interop_number(optarg, 3600);
                if (ctx->lifetime < 0) {
                    return -1;
                }
            }
            break;
        case 'p':
            ctx->port = xqc_interop_number(optarg, 65535);
            if (ctx->port < 0) {
                return -1;
            }
            break;
        case 'T':
            ctx->certificate = optarg;
            break;
        default:
            return -1;
        }
    }
    return optind == argc && (ctx->server
        ? ctx->certificate && ctx->private_key : ctx->url != NULL) ? 0 : -1;
}

static int
xqc_interop_url(void)
{
    xqc_interop_runtime_t *ctx = &xqc_interop_runtime;
    const char *url = ctx->url;

    if (strncmp(url, "https://", 8)) {
        return -1;
    }
    const char *authority = url + 8;
    const char *path = strchr(authority, '/');
    if (!path || (size_t) (path - authority) >= sizeof(ctx->authority)
        || strlen(path) >= sizeof(ctx->path)
        || strpbrk(authority, "@?#\r\n\t "))
    {
        return -1;
    }
    memcpy(ctx->authority, authority, path - authority);
    ctx->authority[path - authority] = '\0';
    strcpy(ctx->path, path);
    const char *host = ctx->authority, *host_end, *port;
    if (*host == '[') {
        host++;
        host_end = strchr(host, ']');
        if (!host_end) {
            return -1;
        }
        port = host_end + 1;
    } else {
        host_end = strchr(host, ':');
        if (!host_end) {
            host_end = host + strlen(host);
        }
        port = host_end;
    }
    if (host_end == host || (size_t) (host_end - host) >= sizeof(ctx->hostname)
        || (*port && *port != ':'))
    {
        return -1;
    }
    memcpy(ctx->hostname, host, host_end - host);
    ctx->hostname[host_end - host] = '\0';
    if (*port) {
        ctx->port = xqc_interop_number(port + 1, 65535);
        if (ctx->port < 0) {
            return -1;
        }
    }
    return 0;
}

static int
xqc_interop_socket(int family, int port)
{
    int socket_fd = socket(family, SOCK_DGRAM, 0);
    int enabled = 1, buffer_size = 4 * 1024 * 1024;

    if (socket_fd < 0) {
        return -1;
    }
    if (evutil_make_socket_nonblocking(socket_fd) < 0) {
        close(socket_fd);
        return -1;
    }
    setsockopt(socket_fd, SOL_SOCKET, SO_REUSEADDR, &enabled, sizeof(enabled));
    setsockopt(socket_fd, SOL_SOCKET, SO_RCVBUF,
               &buffer_size, sizeof(buffer_size));
    setsockopt(socket_fd, SOL_SOCKET, SO_SNDBUF,
               &buffer_size, sizeof(buffer_size));
    int result;
    if (family == AF_INET6) {
        struct sockaddr_in6 address = {0};
        address.sin6_family = AF_INET6;
        address.sin6_addr = in6addr_any;
        address.sin6_port = htons(port);
        setsockopt(socket_fd, IPPROTO_IPV6, IPV6_V6ONLY,
                   &enabled, sizeof(enabled));
        result = bind(socket_fd, (struct sockaddr *) &address,
                       sizeof(address));
    } else {
        struct sockaddr_in address = {0};
        address.sin_family = AF_INET;
        address.sin_addr.s_addr = htonl(INADDR_ANY);
        address.sin_port = htons(port);
        result = bind(socket_fd, (struct sockaddr *) &address,
                       sizeof(address));
    }
    if (result < 0) {
        close(socket_fd);
        return -1;
    }
    return socket_fd;
}

static int
xqc_interop_network(void)
{
    xqc_interop_runtime_t *ctx = &xqc_interop_runtime;

    if (ctx->server) {
        ctx->sockets[0] = xqc_interop_socket(AF_INET, ctx->port);
        ctx->sockets[1] = xqc_interop_socket(AF_INET6, ctx->port);
    } else {
        struct addrinfo hints = {0}, *addresses;
        char service[8];
        hints.ai_socktype = SOCK_DGRAM;
        hints.ai_family = AF_UNSPEC;
        snprintf(service, sizeof(service), "%d", ctx->port);
        int result = getaddrinfo(ctx->hostname, service, &hints, &addresses);
        if (result) {
            fprintf(stderr, "resolve host: %s\n", gai_strerror(result));
            return -1;
        }
        for (struct addrinfo *address = addresses; address;
             address = address->ai_next)
        {
            if (address->ai_family != AF_INET
                && address->ai_family != AF_INET6)
            {
                continue;
            }
            int socket_fd = xqc_interop_socket(address->ai_family, 0);
            if (socket_fd < 0) {
                continue;
            }
            ctx->sockets[address->ai_family == AF_INET6] = socket_fd;
            memcpy(&ctx->peer, address->ai_addr, address->ai_addrlen);
            ctx->peer_length = address->ai_addrlen;
            break;
        }
        freeaddrinfo(addresses);
    }
    if (ctx->sockets[0] < 0 && ctx->sockets[1] < 0) {
        return -1;
    }
    for (int i = 0; i < 2; i++) {
        if (ctx->sockets[i] < 0) {
            continue;
        }
        ctx->reads[i] = event_new(ctx->events, ctx->sockets[i],
                                  EV_READ | EV_PERSIST, xqc_interop_read, ctx);
        ctx->writes[i] = event_new(ctx->events, ctx->sockets[i],
                                   EV_WRITE, xqc_interop_write, ctx);
        if (!ctx->reads[i] || !ctx->writes[i]
            || event_add(ctx->reads[i], NULL) < 0)
        {
            return -1;
        }
    }
    return 0;
}

static xqc_conn_settings_t
xqc_interop_settings(void)
{
    xqc_conn_settings_t settings = {
        .proto_version = XQC_VERSION_V1,
        .pacing_on = 1,
        .cong_ctrl_callback = xqc_bbr_cb,
        .cc_params = {.customize_on = 1, .init_cwnd = 96},
        .so_sndbuf = 1024 * 1024,
        .init_idle_time_out = 60000,
        .idle_time_out = 60000,
        .spurious_loss_detect_on = 1,
        .max_pkt_out_size = 1200,
        .max_udp_payload_size = 1200,
        .init_recv_window = 8 * 1024 * 1024,
        .max_streams_bidi = 16,
        .max_streams_uni = 64,
    };
    return settings;
}

static int
xqc_interop_engine(void)
{
    xqc_interop_runtime_t *ctx = &xqc_interop_runtime;
    xqc_engine_type_t type = ctx->server ? XQC_ENGINE_SERVER
                                         : XQC_ENGINE_CLIENT;
    xqc_config_t config;
    xqc_engine_ssl_config_t tls = {
        .private_key_file = ctx->private_key,
        .cert_file = ctx->certificate,
        .ciphers = XQC_TLS_CIPHERS,
        .groups = "P-256:X25519:P-384:P-521",
    };
    xqc_engine_callback_t callbacks = {
        .set_event_timer = xqc_interop_timer_set,
        .log_callbacks = {
            .xqc_log_write_err = xqc_interop_log,
            .xqc_log_write_stat = xqc_interop_log,
            .xqc_qlog_event_write = xqc_interop_qlog,
        },
        .keylog_cb = xqc_interop_keys,
    };
    xqc_transport_callbacks_t transport = {
        .server_accept = xqc_interop_accept,
        .write_socket = xqc_interop_send,
        .write_socket_ex = xqc_interop_send_path,
        .conn_send_packet_before_accept = xqc_interop_send,
        .conn_update_cid_notify = xqc_interop_cid,
        .cert_verify_cb = xqc_interop_verify,
        .save_token = xqc_interop_token,
        .save_session_cb = xqc_interop_session,
        .save_tp_cb = xqc_interop_session,
    };
    xqc_h3_callbacks_t http = {
        .h3c_cbs = {
            .h3_conn_create_notify = xqc_interop_connection_create,
            .h3_conn_close_notify = xqc_interop_connection_close,
            .h3_conn_handshake_finished = xqc_interop_handshake,
        },
    };
    if (!ctx->server) {
        transport.conn_closing = xqc_demo_wt_client_conn_closing;
    }
    if (xqc_engine_get_default_config(&config, type) != XQC_OK) {
        return -1;
    }
    config.cfg_log_level = ctx->log_level;
    config.manually_triggered_send = 1;
    ctx->engine = xqc_engine_create(type, &config, &tls, &callbacks,
                                    &transport, ctx);
    if (!ctx->engine) {
        return -1;
    }
    xqc_conn_settings_t settings = xqc_interop_settings();
    if (ctx->server) {
        xqc_server_set_conn_settings(ctx->engine, &settings);
    }
    if (xqc_h3_ctx_init(ctx->engine, &http) != XQC_OK) {
        return -1;
    }
    int result = ctx->server
        ? xqc_demo_wt_init(ctx->engine, ctx->draft, xqc_interop_schedule, ctx)
        : xqc_demo_wt_client_init(ctx->engine, ctx->draft, 0,
                                  xqc_interop_schedule,
                                  xqc_interop_finished, ctx);
    if (result != XQC_OK) {
        return -1;
    }
    if (!ctx->server) {
        xqc_conn_ssl_config_t verify = {
            .cert_verify_flag = XQC_TLS_CERT_FLAG_NEED_VERIFY,
        };
        const xqc_cid_t *cid = xqc_webtransport_connect(ctx->engine,
            &settings, NULL, 0, ctx->hostname, 0, &verify,
            (struct sockaddr *) &ctx->peer, ctx->peer_length, ctx);
        if (!cid) {
            return -1;
        }
        ctx->cid = *cid;
        ctx->connected = 1;
        xqc_interop_schedule(ctx);
    }
    return 0;
}

static void
xqc_interop_cleanup(void)
{
    xqc_interop_runtime_t *ctx = &xqc_interop_runtime;

    ctx->stopping = 1;
    if (ctx->engine) {
        xqc_engine_destroy(ctx->engine);
    }
    for (int i = 0; i < 2; i++) {
        if (ctx->reads[i]) {
            event_free(ctx->reads[i]);
        }
        if (ctx->writes[i]) {
            event_free(ctx->writes[i]);
        }
        if (ctx->sockets[i] >= 0) {
            close(ctx->sockets[i]);
        }
    }
    if (ctx->timer) {
        event_free(ctx->timer);
    }
    if (ctx->stop) {
        event_free(ctx->stop);
    }
    if (ctx->timeout) {
        event_free(ctx->timeout);
    }
    if (ctx->events) {
        event_base_free(ctx->events);
    }
    if (ctx->keys) {
        fclose(ctx->keys);
    }
    if (ctx->log) {
        fclose(ctx->log);
    }
}

int
main(int argc, char **argv)
{
    xqc_interop_runtime_t *ctx = &xqc_interop_runtime;
    int result = 1;

    setvbuf(stdout, NULL, _IOLBF, 0);
    ctx->sockets[0] = ctx->sockets[1] = -1;
    if (xqc_interop_arguments(argc, argv) < 0
        || (!ctx->server && xqc_interop_url() < 0))
    {
        fprintf(stderr, "Invalid WebTransport endpoint arguments\n");
        goto cleanup;
    }
    ctx->events = event_base_new();
    if (!ctx->events) {
        goto cleanup;
    }
    ctx->timer = event_new(ctx->events, -1, 0, xqc_interop_timer, ctx);
    ctx->stop = evsignal_new(ctx->events, SIGTERM, xqc_interop_stop, ctx);
    if (!ctx->timer || !ctx->stop || event_add(ctx->stop, NULL) < 0
        || xqc_interop_network() < 0 || xqc_interop_engine() < 0)
    {
        fprintf(stderr, "WebTransport endpoint initialization failed\n");
        goto cleanup;
    }
    if (!ctx->server) {
        struct timeval timeout = {ctx->lifetime, 0};
        ctx->timeout = event_new(ctx->events, -1, 0, xqc_interop_timeout, ctx);
        if (!ctx->timeout || event_add(ctx->timeout, &timeout) < 0) {
            goto cleanup;
        }
    }
    event_base_dispatch(ctx->events);
    result = ctx->server ? 0 : xqc_demo_wt_client_finish();
    if (ctx->failed) {
        result = 1;
    }
cleanup:
    xqc_interop_cleanup();
    return result;
}
