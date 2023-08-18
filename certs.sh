#!/usr/bin/env bash

set -e

if [ -z "$1" ] || [ -z "$2" ] ; then
  echo "$0 <cert dir> <chain length>"
  exit 1
fi

CERTDIR=$1
CHAINLEN=$2

mkdir -p $CERTDIR || true

# Generate Root CA and certificate
openssl req -x509 -sha256 -nodes -days 365 -newkey rsa:2048 \
  -keyout $CERTDIR/ca_0.key -out $CERTDIR/cert_0.pem \
  -subj "/O=interop runner Root Certificate Authority/" \
  -config cert_config.txt \
  -extensions v3_ca \
  2> /dev/null

for i in $(seq 1 $CHAINLEN); do
  # Generate a CSR
  SUBJ="interop runner intermediate $i"
  if [[ $i == $CHAINLEN ]]; then
    SUBJ="interop runner leaf"
  fi
  openssl req -out $CERTDIR/cert.csr -new -newkey rsa:2048 -nodes -keyout $CERTDIR/ca_$i.key \
    -subj "/O=$SUBJ/" \
    2> /dev/null

  # Sign the certificate
  j=$(($i-1))
  if [[ $i < $CHAINLEN ]]; then
    openssl x509 -req -sha256 -days 365 -in $CERTDIR/cert.csr -out $CERTDIR/cert_$i.pem \
      -CA $CERTDIR/cert_$j.pem -CAkey $CERTDIR/ca_$j.key -CAcreateserial \
      -extfile cert_config.txt \
      -extensions v3_ca \
      2> /dev/null
  else
    openssl x509 -req -sha256 -days 365 -in $CERTDIR/cert.csr -out $CERTDIR/cert_$i.pem \
      -CA $CERTDIR/cert_$j.pem -CAkey $CERTDIR/ca_$j.key -CAcreateserial \
      -extfile <(printf "subjectAltName=DNS:server,DNS:server4,DNS:server6,DNS:server46") \
      2> /dev/null
  fi
done

mv $CERTDIR/cert_0.pem $CERTDIR/ca.pem
cp $CERTDIR/ca_$CHAINLEN.key $CERTDIR/priv.key

# combine certificates
for i in $(seq $CHAINLEN -1 1); do
  cat $CERTDIR/cert_$i.pem >> $CERTDIR/cert.pem
  rm $CERTDIR/cert_$i.pem $CERTDIR/ca_$i.key
done
rm -f $CERTDIR/*.srl $CERTDIR/ca_0.key $CERTDIR/cert.csr
