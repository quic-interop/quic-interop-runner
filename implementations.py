import json
import sys

# add your QUIC implementation here
IMPLEMENTATIONS = (
    {  # name => [ docker image, role ]; role: 0 == 'client', 1 == 'server', 2 == both
        "quic-go": {"url": "martenseemann/quic-go-interop:latest", "role": 2},
        "quicly": {"url": "h2oserver/quicly-interop-runner:latest", "role": 2},
        "ngtcp2": {"url": "ngtcp2/ngtcp2-interop:latest", "role": 2},
        "quant": {"url": "ntap/quant:interop", "role": 2},
        "mvfst": {"url": "lnicco/mvfst-qns:latest", "role": 2},
        "quiche": {"url": "cloudflare/quiche-qns:latest", "role": 2},
        "kwik": {"url": "peterdoornbosch/kwik_n_flupke-interop", "role": 0},
        "picoquic": {"url": "privateoctopus/picoquic:latest", "role": 2},
        "aioquic": {"url": "aiortc/aioquic-qns:latest", "role": 2},
        "neqo": {"url": "neqoquic/neqo-qns:latest", "role": 2},
        "nginx": {"url": "nginx/nginx-quic-qns:latest", "role": 1},
        "msquic": {"url": "mcr.microsoft.com/msquic/qns:latest", "role": 1},
        "pquic": {"url": "pquic/pquic-interop:latest", "role": 2},
    }
)


def main():
    """
    export the list of client and server implementations in JSON format
    """
    print(
        json.dumps(
            {
                "server": [
                    name for name, val in IMPLEMENTATIONS.items() if val["role"] > 0
                ],
                "client": [
                    name
                    for name, val in IMPLEMENTATIONS.items()
                    if val["role"] % 2 == 0
                ],
            }
        )
    )


if __name__ == "__main__":
    sys.exit(main())
