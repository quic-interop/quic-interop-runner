# add your QUIC implementation here
IMPLEMENTATIONS = { # name => [ docker image, role ]; role: 0 == 'client', 1 == 'server', 2 == both
  "quicgo": { "url": "martenseemann/quic-go-interop:latest", "role": 2 },
  "quicly": { "url": "janaiyengar/quicly:interop", "role": 2 },
  "ngtcp2": { "url": "ngtcp2/ngtcp2-interop:latest", "role": 2 },
  "quant":  { "url": "ntap/quant:interop", "role": 2 },
  "mvfst":  { "url": "lnicco/mvfst-qns:latest", "role": 2 },
  "quiche": { "url": "cloudflare/quiche-qns:latest", "role": 2 },
  "kwik":   { "url": "peterdoornbosch/kwik_n_flupke-interop", "role": 0 },
}
