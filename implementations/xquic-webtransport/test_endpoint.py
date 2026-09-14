#!/usr/bin/env python3
"""Check the runner-to-demo argument boundary without starting endpoints."""

import unittest

from run_endpoint import endpoint_command


class EndpointTests(unittest.TestCase):
    def test_client_session_and_trust(self):
        command = endpoint_command(
            {
                "ROLE": "client",
                "TESTCASE": "transfer-unidirectional-receive",
                "REQUESTS": "https://server4:443/wt/file1 https://server4:443/wt/file2",
                "SSLKEYLOGFILE": "/logs/client.keys",
            }
        )
        self.assertEqual(command[0], "/usr/local/bin/wt_interop_client")
        self.assertEqual(command[command.index("-U") + 1], "https://server4:443/wt")
        self.assertEqual(command[command.index("-J") + 1], "/certs/ca.pem")
        self.assertEqual(command[command.index("-k") + 1], "/logs/client.keys")

    def test_client_default_and_custom_ports(self):
        for url, port in [
            ("https://server4/wt", "443"),
            ("https://server4:8443/wt", "8443"),
        ]:
            with self.subTest(url=url):
                command = endpoint_command(
                    {"ROLE": "client", "TESTCASE": "handshake", "REQUESTS": url}
                )
                self.assertEqual(command[command.index("-U") + 1], url)
                self.assertEqual(command[command.index("-p") + 1], port)

    def test_server_certificate_and_port(self):
        command = endpoint_command(
            {"ROLE": "server", "TESTCASE": "transfer", "XQC_WT_PORT": "4443"}
        )
        self.assertEqual(command[0], "/usr/local/bin/wt_interop_server")
        self.assertEqual(command[command.index("-p") + 1], "4443")
        self.assertEqual(command[command.index("-T") + 1], "/certs/cert.pem")
        self.assertEqual(command[command.index("-K") + 1], "/certs/priv.key")

    def test_unsupported_case_and_malformed_request(self):
        self.assertIsNone(endpoint_command({"ROLE": "server", "TESTCASE": "unknown"}))
        self.assertIsNone(endpoint_command({"ROLE": "client", "TESTCASE": "transfer"}))
        self.assertIsNone(
            endpoint_command({"ROLE": "invalid", "TESTCASE": "handshake"})
        )
        for url in [
            "",
            "http://server/wt/file",
            "https://user@server/wt/file",
            "https://server:invalid/wt/file",
            "https://server/../file",
            "https://server/wt/file?query=1",
            "https://server/wt/file#fragment",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                endpoint_command(
                    {"ROLE": "client", "TESTCASE": "handshake", "REQUESTS": url}
                )


if __name__ == "__main__":
    unittest.main()
