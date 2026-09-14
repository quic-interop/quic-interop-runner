#!/usr/bin/env python3
"""Check image source provenance and build failure handling without Docker."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import build_image


class BuildImageTests(unittest.TestCase):
    def invoke_build(self, root, adapter, run):
        arguments = [
            "build_image.py",
            "--xquic",
            str(root),
            "--image",
            "ghcr.io/yanmei-liu/xquic-webtransport-interop:test",
            "--source-url",
            "https://github.com/Yanmei-Liu/quic-interop-runner",
        ]
        with (
            patch.object(sys, "argv", arguments),
            patch.object(build_image, "ADAPTER", adapter),
            patch.object(
                subprocess,
                "check_output",
                side_effect=[b"endpoint.c\0", "a" * 40 + "\n"],
            ),
            patch.object(subprocess, "run", side_effect=run),
        ):
            build_image.main()

    def test_build_copies_sources_and_associates_the_publisher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "xquic"
            adapter = Path(directory) / "adapter"
            root.mkdir()
            adapter.mkdir()
            (root / "endpoint.c").write_text("int endpoint;\n")
            (adapter / "Dockerfile").write_text("FROM scratch\n")
            commands = []

            def run(command, check):
                self.assertTrue(check)
                commands.append(command)
                if command[1] == "build":
                    context = Path(command[-1])
                    self.assertEqual(
                        (context / "xquic/endpoint.c").read_text(),
                        "int endpoint;\n",
                    )
                    self.assertTrue((context / "adapter/Dockerfile").is_file())

            self.invoke_build(root, adapter, run)
            self.assertIn(
                "IMAGE_SOURCE=https://github.com/Yanmei-Liu/quic-interop-runner",
                commands[0],
            )
            self.assertIn("XQUIC_REVISION=" + "a" * 40, commands[0])
            self.assertEqual(commands[1][1:3], ["image", "inspect"])
            self.assertEqual(list((root / "build").iterdir()), [])

    def test_failed_build_propagates_and_cleans_the_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "xquic"
            adapter = Path(directory) / "adapter"
            root.mkdir()
            adapter.mkdir()
            (root / "endpoint.c").write_text("int endpoint;\n")
            (adapter / "Dockerfile").write_text("FROM scratch\n")
            commands = []

            def fail(command, check):
                commands.append(command)
                raise subprocess.CalledProcessError(1, command)

            with self.assertRaises(subprocess.CalledProcessError):
                self.invoke_build(root, adapter, fail)
            self.assertEqual(len(commands), 1)
            self.assertEqual(list((root / "build").iterdir()), [])

    def test_source_digest_changes_for_code_but_not_documentation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "endpoint.c").write_text("int endpoint;\n")
            (root / "README.md").write_text("First description.\n")
            files = ["endpoint.c", "README.md"]
            original = build_image.source_digest(root, files)
            (root / "README.md").write_text("Updated description.\n")
            self.assertEqual(build_image.source_digest(root, files), original)
            (root / "endpoint.c").write_text("int updated_endpoint;\n")
            self.assertNotEqual(build_image.source_digest(root, files), original)


if __name__ == "__main__":
    unittest.main()
