#!/usr/bin/env python3

from setuptools import setup

setup(
    name='QUIC interop runner',
    version='1.0',
    url='https://github.com/marten-seemann/quic-interop-runner/',
    install_requires=[
        "pycrypto",
        "termcolor",
        "prettytable",
        "pyshark",
    ],
)
