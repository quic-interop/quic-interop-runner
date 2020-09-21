#!/bin/bash

set -e

if [ -z $1 ]; then
  echo "$0 <cert dir>"
  exit 1
fi

CERTDIR=$1


mkdir -p $CERTDIR || true

echo "Generating CA key and certificate:"
openssl req -x509 -sha256 -nodes -days 365 -newkey rsa:2048 \
  -keyout $CERTDIR/ca.key -out $CERTDIR/ca.pem \
  -subj "/O=interop runner Certificate Authority/"

echo "Generating CSR"
openssl req -out $CERTDIR/cert.csr -new -newkey rsa:2048 -nodes -keyout $CERTDIR/priv.key \
  -subj "/O=interop runner/"

echo "Sign certificate:"
openssl x509 -req -sha256 -days 365 -in $CERTDIR/cert.csr -out $CERTDIR/cert.pem \
  -CA $CERTDIR/ca.pem -CAkey $CERTDIR/ca.key -CAcreateserial \
  -extfile <(printf "subjectAltName=DNS:server")

# debug output the certificate
openssl x509 -noout -text -in $CERTDIR/cert.pem

# we don't need the CA key, the serial number and the CSR any more
rm $CERTDIR/ca.key $CERTDIR/cert.csr $CERTDIR/ca.srl

