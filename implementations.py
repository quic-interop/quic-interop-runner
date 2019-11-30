# add your QUIC implementation here
IMPLEMENTATIONS = { # name => [ docker image, role ]; role: 0 == 'client', 1 == 'server', 2 == both
  "quicgo": [ "martenseemann/quic-go-interop:latest", 2 ],
  "quicly": [ "janaiyengar/quicly:interop", 2 ],
  "ngtcp2": [ "ngtcp2/ngtcp2-interop:latest", 2 ],
  "quant":  [ "ntap/quant:interop", 2 ],
  "mvfst":  [ "lnicco/mvfst-qns:latest", 2 ],
  "quiche": [ "cloudflare/quiche-qns:latest", 2 ],
  "kwik":   [ "peterdoornbosch/kwik_n_flupke-interop", 0 ],
}
