# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Recipe-driven DLL fetch against a synthetic package built the same way as AMD's (raw LZMA2 + BCJ x86)."""

import hashlib
import io
import lzma
import os
import random
import tempfile
import unittest

import _harness  # noqa: F401
import fsr4_dll


def _package(dll, before, start_offset, junk):
    """Remote file bytes and a recipe pointing at a 'reset chunk' that begins after junk bytes."""
    stream = before + dll + os.urandom(4096)
    packed = lzma.compress(stream, format=lzma.FORMAT_RAW, filters=[
        {"id": lzma.FILTER_X86, "start_offset": start_offset}, {"id": lzma.FILTER_LZMA2, "dict_size": 2**24}])
    remote = os.urandom(junk) + packed
    recipe = {"url": "test://", "referer": "", "packed_offset": junk, "unpacked_offset": start_offset,
              "dll_offset": len(before), "dll_size": len(dll), "sha256": hashlib.sha256(dll).hexdigest()}
    return remote, recipe


class _Resp(io.BytesIO):
    status = 206


def _opener(remote, cut=None):
    def open_(recipe):
        data = remote[recipe["packed_offset"]:]
        return _Resp(data[:cut] if cut else data)
    return open_


class Fetch(unittest.TestCase):
    def setUp(self):
        rnd = random.Random(7)
        # x86-ish bytes with E8/E9 call opcodes so BCJ actually rewrites something
        self.dll = bytes(rnd.choice((0xE8, 0xE9, 0x00, 0xFF, rnd.randrange(256))) for _ in range(300_000))
        self.before = bytes(rnd.randrange(256) for _ in range(150_000))
        self.dir = tempfile.mkdtemp()
        self.dest = os.path.join(self.dir, "amdxcffx64.dll")

    def test_extracts_exact_dll(self):
        remote, recipe = _package(self.dll, self.before, 1610612736, 5000)
        seen = []
        fsr4_dll.fetch(self.dest, recipe, progress=lambda d, t: seen.append(d), opener=_opener(remote))
        with open(self.dest, "rb") as f:
            self.assertEqual(f.read(), self.dll)
        self.assertEqual(seen[-1], len(self.dll))
        self.assertTrue(fsr4_dll.is_valid(self.dest, recipe))

    def test_wrong_bcj_offset_fails_checksum_and_leaves_nothing(self):
        # BCJ x86 keeps 25 address bits, so only an offset that differs below 2**25 changes the output
        remote, recipe = _package(self.dll, self.before, 123457, 0)
        recipe["unpacked_offset"] = 0
        with self.assertRaisesRegex(fsr4_dll.FetchError, "checksum"):
            fsr4_dll.fetch(self.dest, recipe, opener=_opener(remote))
        self.assertEqual(os.listdir(self.dir), [])

    def test_truncated_download(self):
        remote, recipe = _package(self.dll, self.before, 0, 0)
        with self.assertRaisesRegex(fsr4_dll.FetchError, "ended"):
            fsr4_dll.fetch(self.dest, recipe, opener=_opener(remote, cut=1000))
        self.assertEqual(os.listdir(self.dir), [])

    def test_server_without_range_support(self):
        remote, recipe = _package(self.dll, self.before, 0, 0)

        class Full(_Resp):
            status = 200
        with self.assertRaisesRegex(fsr4_dll.FetchError, "range"):
            fsr4_dll.fetch(self.dest, recipe, opener=lambda r: Full(remote))

    def test_cancel(self):
        remote, recipe = _package(self.dll, self.before, 0, 0)
        with self.assertRaisesRegex(fsr4_dll.FetchError, "cancelled"):
            fsr4_dll.fetch(self.dest, recipe, opener=_opener(remote), cancelled=lambda: True)

    def test_existing_file_validation(self):
        self.assertFalse(fsr4_dll.is_valid(self.dest))
        with open(self.dest, "wb") as f:
            f.write(b"x" * 10)
        self.assertFalse(fsr4_dll.is_valid(self.dest))


if __name__ == "__main__":
    unittest.main()
