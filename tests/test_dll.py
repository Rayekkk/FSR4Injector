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
import unittest.mock

import _harness  # noqa: F401
import dk_net
import fsr4_dll


def _package(dll, before, start_offset, junk):
    """Remote file bytes and a recipe pointing at a 'reset chunk' that begins after junk bytes."""
    stream = before + dll + os.urandom(4096)
    packed = lzma.compress(stream, format=lzma.FORMAT_RAW, filters=[
        {"id": lzma.FILTER_X86, "start_offset": start_offset}, {"id": lzma.FILTER_LZMA2, "dict_size": 2**20}])
    remote = os.urandom(junk) + packed
    recipe = {"url": "https://drivers.amd.com/x.exe", "referer": "https://www.amd.com/", "packed_offset": junk,
              "packed_size": len(packed), "packed_sha256": hashlib.sha256(packed).hexdigest(),
              "unpacked_offset": start_offset, "dict_size": 2**20, "dll_offset": len(before), "dll_size": len(dll),
              "sha256": hashlib.sha256(dll).hexdigest()}
    return remote, recipe


def _spool(remote, seen=None):
    """dk_net.spool serving the asked range of remote, with its size and hash checks."""
    def spool(url, folder, limit, sha256=None, **options):
        if seen is not None:
            seen.update(options, url=url, folder=folder, limit=limit, sha256=sha256)
        first, last = options["byte_range"]
        body = remote[first:last + 1]
        if options.get("cancel") and options["cancel"]():
            raise dk_net.NetError("cancelled")
        if options.get("progress"):
            options["progress"](len(body))
        if hashlib.sha256(body).hexdigest() != sha256:
            raise dk_net.Mismatch("not the expected file (SHA-256 differs)")
        return io.BytesIO(body)
    return spool


class Fetch(unittest.TestCase):
    def setUp(self):
        rnd = random.Random(7)
        # x86-ish bytes with E8/E9 call opcodes so BCJ actually rewrites something
        self.dll = bytes(rnd.choice((0xE8, 0xE9, 0x00, 0xFF, rnd.randrange(256))) for _ in range(300_000))
        self.before = bytes(rnd.randrange(256) for _ in range(150_000))
        self.dir = tempfile.mkdtemp()
        self.dest = os.path.join(self.dir, "amdxcffx64.dll")

    def test_extracts_exact_dll_from_exactly_the_pinned_range(self):
        remote, recipe = _package(self.dll, self.before, 1610612736, 5000)
        seen, progress = {}, []
        fsr4_dll.fetch(self.dest, recipe, progress=lambda d, t: progress.append((d, t)), spool=_spool(remote, seen))
        with open(self.dest, "rb") as f:
            self.assertEqual(f.read(), self.dll)
        self.assertEqual(progress[-1], (recipe["packed_size"], recipe["packed_size"]), "progress of the download")
        self.assertTrue(fsr4_dll.is_valid(self.dest, recipe))
        self.assertEqual(seen["byte_range"], (5000, 5000 + recipe["packed_size"] - 1))
        self.assertEqual((seen["limit"], seen["sha256"]), (recipe["packed_size"], recipe["packed_sha256"]))
        self.assertEqual(seen["hosts"], {"drivers.amd.com"}, "AMD's download host only, also for redirects")
        self.assertEqual(seen["headers"]["Referer"], "https://www.amd.com/")
        self.assertEqual(os.path.abspath(seen["folder"]), os.path.abspath(self.dir), "spooled beside the DLL")
        self.assertEqual(os.listdir(self.dir), ["amdxcffx64.dll"])

    def test_the_real_recipe_is_complete(self):
        keys = {"url", "referer", "packed_offset", "packed_size", "packed_sha256", "unpacked_offset", "dict_size",
                "dll_offset", "dll_size", "sha256"}
        for recipe in fsr4_dll.RECIPES:
            self.assertLessEqual(keys, set(recipe))
            self.assertLessEqual(recipe["packed_size"], dk_net.MAX_BODY)
            self.assertEqual(dk_net.check_url(recipe["url"], fsr4_dll.HOSTS), recipe["url"])

    def test_wrong_bcj_offset_fails_checksum_and_leaves_nothing(self):
        # BCJ x86 keeps 25 address bits, so only an offset that differs below 2**25 changes the output
        remote, recipe = _package(self.dll, self.before, 123457, 0)
        recipe["unpacked_offset"] = 0
        with self.assertRaisesRegex(fsr4_dll.FetchError, "checksum"):
            fsr4_dll.fetch(self.dest, recipe, spool=_spool(remote))
        self.assertEqual(os.listdir(self.dir), [])

    def test_a_range_too_short_for_the_dll(self):
        remote, recipe = _package(self.dll, self.before, 0, 0)
        recipe["packed_size"] = 1000
        recipe["packed_sha256"] = hashlib.sha256(remote[:1000]).hexdigest()
        with self.assertRaisesRegex(fsr4_dll.FetchError, "ended"):
            fsr4_dll.fetch(self.dest, recipe, spool=_spool(remote))
        self.assertEqual(os.listdir(self.dir), [])

    def test_changed_package_and_network_errors_are_fetch_errors(self):
        remote, recipe = _package(self.dll, self.before, 0, 0)
        with self.assertRaisesRegex(fsr4_dll.FetchError, "AMD changed the package"):
            fsr4_dll.fetch(self.dest, recipe, spool=_spool(b"x" + remote))
        for error in (dk_net.NetError("the server did not send the requested part of the file"),
                      dk_net.NetError("the connection dropped before the end")):
            def spool(*a, **k):
                raise error
            with self.assertRaisesRegex(fsr4_dll.FetchError, str(error)):
                fsr4_dll.fetch(self.dest, recipe, spool=spool)
        self.assertEqual(os.listdir(self.dir), [])

    def test_cancel(self):
        remote, recipe = _package(self.dll, self.before, 0, 0)
        with self.assertRaisesRegex(fsr4_dll.FetchError, "cancelled"):
            fsr4_dll.fetch(self.dest, recipe, spool=_spool(remote), cancelled=lambda: True)

    def test_a_full_disk_names_no_path(self):
        remote, recipe = _package(self.dll, self.before, 0, 0)
        full = OSError(28, "No space left on device", self.dest)
        with unittest.mock.patch("dk_fs.write_atomic", side_effect=full):
            with self.assertRaisesRegex(fsr4_dll.FetchError, "No space left") as caught:
                fsr4_dll.fetch(self.dest, recipe, spool=_spool(remote))
        self.assertNotIn(self.dir, str(caught.exception))

    def test_existing_file_validation(self):
        self.assertFalse(fsr4_dll.is_valid(self.dest))
        with open(self.dest, "wb") as f:
            f.write(b"x" * 10)
        self.assertFalse(fsr4_dll.is_valid(self.dest))


if __name__ == "__main__":
    unittest.main()
