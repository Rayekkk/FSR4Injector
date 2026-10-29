# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Fetching AMD's amdxcffx64.dll without redistributing it.

The DLL ships only inside AMD's Adrenalin installer, a 1.7 GB 7z SFX compressed as a few solid LZMA2+BCJ blocks.
7-Zip's multithreaded LZMA2 resets its dictionary every so often, so decoding can start at a reset chunk shortly
before the DLL. A recipe pins that chunk's offsets, the exact packed range that holds the DLL and the SHA-256 of
both (made with tools/find_recipe.py); dk_net fetches that range (~43 MiB) beside the destination, it is decoded in
one streaming pass, and only the verified DLL is kept (published by dk_fs).
"""

import hashlib
import os

import dk_fs
import dk_net
from dk_fs import sha256_file

RECIPES = [
    {
        "driver": "Adrenalin 26.10.1",
        "fsr": "4.1.2",
        "file_version": "2.4.0.4370",
        "url": "https://drivers.amd.com/drivers/whql-amd-software-adrenalin-edition-26.10.1-win11-c.exe",
        "referer": "https://www.amd.com/",
        "packed_offset": 857273233,  # LZMA2 dictionary-reset chunk, absolute file offset
        "packed_size": 44843008,  # bytes from that chunk until the DLL is decoded completely
        "packed_sha256": "820aeb5ad7e077e5a380551d9e604d0cae413c08c3576fa9002dfedf33b84be7",
        "unpacked_offset": 1610612736,  # position of that chunk in the block's decoded stream (BCJ needs it)
        "dict_size": 2**24,  # the 7z block's LZMA2 dictionary
        "dll_offset": 124861144,  # DLL start, counted from the chunk
        "dll_size": 85684104,
        "sha256": "c33a287f3048bf02311cae430b6a977500b94ca7b315cd7bff751e6b03e483e3",
    },
]
RECIPE = RECIPES[0]
EULA_URL = "https://www.amd.com/en/legal/eula/amd-software-eula.html"
HOSTS = frozenset({"drivers.amd.com"})
DEADLINE = 1800  # 43 MiB still arrive at 25 kB/s
CHUNK = 1 << 20
USER_AGENT = "Mozilla/5.0 (FSR4Injector)"  # AMD's CDN is known to answer this one


class FetchError(Exception):
    pass


def is_valid(path, recipe=RECIPE):
    try:
        return os.path.getsize(path) == recipe["dll_size"] and sha256_file(path) == recipe["sha256"]
    except OSError:
        return False


class _Decoded:
    """The DLL decoded from the packed range, as a file object for dk_fs.write_atomic. It reaches its end only with
    the pinned SHA-256; anything else raises, so write_atomic never publishes it."""

    def __init__(self, packed, recipe, lzma):
        self.packed, self.recipe, self.lzma_error = packed, recipe, lzma.LZMAError
        self.decoder = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[
            {"id": lzma.FILTER_X86, "start_offset": recipe["unpacked_offset"] % 2**32},
            {"id": lzma.FILTER_LZMA2, "dict_size": recipe["dict_size"]},
        ])
        self.skip, self.got, self.digest = recipe["dll_offset"], 0, hashlib.sha256()

    def read(self, _size=-1):
        size = self.recipe["dll_size"]
        while self.got < size:
            chunk = self.packed.read(CHUNK)
            if not chunk:
                raise FetchError("download ended before the DLL was complete")
            try:
                data = self.decoder.decompress(chunk)
            except self.lzma_error as e:
                raise FetchError(f"AMD package does not match the recipe ({e})") from e
            if self.skip:
                cut = min(self.skip, len(data))
                self.skip -= cut
                data = data[cut:]
            data = data[:size - self.got]
            if data:
                self.got += len(data)
                self.digest.update(data)
                return data
        if self.digest.hexdigest() != self.recipe["sha256"]:
            raise FetchError("checksum mismatch: AMD changed the package, a new recipe is needed")
        return b""


def fetch(dest, recipe=RECIPE, progress=None, cancelled=None, spool=dk_net.spool):
    """Download, decode and verify the DLL into dest. Leaves nothing behind on failure.

    progress(done_bytes, total_bytes) follows the download from AMD; cancelled() stops it.
    """
    try:
        import lzma  # imported here so a Python without it still loads the plugin and can say why
    except ImportError as e:
        raise FetchError("this Decky Loader's Python has no lzma module; the DLL cannot be decoded") from e
    first, size = recipe["packed_offset"], recipe["packed_size"]
    try:
        packed = spool(recipe["url"], os.path.dirname(os.path.abspath(dest)), size, recipe["packed_sha256"],
                       hosts=HOSTS, headers={"User-Agent": USER_AGENT, "Referer": recipe["referer"]},
                       byte_range=(first, first + size - 1), deadline=DEADLINE, cancel=cancelled,
                       progress=(lambda done: progress(done, size)) if progress else None)
    except dk_net.Mismatch as e:
        raise FetchError("checksum mismatch: AMD changed the package, a new recipe is needed") from e
    except dk_net.NetError as e:
        raise FetchError(str(e)) from e
    with packed:
        try:
            dk_fs.write_atomic(dest, _Decoded(packed, recipe, lzma), 0o644)
        except OSError as e:
            raise FetchError(f"the DLL could not be saved ({dk_fs.shown(e)})") from e
