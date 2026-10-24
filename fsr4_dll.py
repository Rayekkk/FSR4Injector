# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Fetching AMD's amdxcffx64.dll without redistributing it.

The DLL ships only inside AMD's Adrenalin installer, a 1.7 GB 7z SFX compressed as a few solid LZMA2+BCJ blocks.
7-Zip's multithreaded LZMA2 resets its dictionary every so often, so decoding can start at a reset chunk shortly
before the DLL. A recipe pins that chunk's offsets (made with tools/find_recipe.py) and the DLL's sha256; we download
from the chunk to the end of the DLL (~43 MiB), decode it in one streaming pass and keep only the verified DLL.
"""

import hashlib
import os
import ssl
import urllib.request

RECIPES = [
    {
        "driver": "Adrenalin 26.10.1",
        "fsr": "4.1.2",
        "file_version": "2.4.0.4370",
        "url": "https://drivers.amd.com/drivers/whql-amd-software-adrenalin-edition-26.10.1-win11-c.exe",
        "referer": "https://www.amd.com/",
        "packed_offset": 857273233,  # LZMA2 dictionary-reset chunk, absolute file offset
        "unpacked_offset": 1610612736,  # position of that chunk in the block's decoded stream (BCJ needs it)
        "dll_offset": 124861144,  # DLL start, counted from the chunk
        "dll_size": 85684104,
        "sha256": "c33a287f3048bf02311cae430b6a977500b94ca7b315cd7bff751e6b03e483e3",
    },
]
RECIPE = RECIPES[0]
EULA_URL = "https://www.amd.com/en/legal/eula/amd-software-eula.html"
CHUNK = 1 << 20
USER_AGENT = "Mozilla/5.0 (FSR4Injector)"


class FetchError(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def is_valid(path, recipe=RECIPE):
    try:
        return os.path.getsize(path) == recipe["dll_size"] and sha256_file(path) == recipe["sha256"]
    except OSError:
        return False


CA_FILES = ("/etc/ssl/certs/ca-certificates.crt", "/etc/ssl/cert.pem")


def _ssl_context():
    """Verified TLS. Decky's frozen Python has no CA store of its own, so use certifi (bundled with Decky) or the
    system bundle; verification is never turned off."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError):
        pass
    for cafile in CA_FILES:
        if os.path.isfile(cafile):
            return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


def _open(recipe):
    # AMD's CDN answers open-ended ranges with the whole file; a closed one works. Packed data never exceeds
    # the unpacked size by more than LZMA2's per-chunk overhead, and we stop reading once the DLL is complete.
    start = recipe["packed_offset"]
    end = start + int((recipe["dll_offset"] + recipe["dll_size"]) * 1.01) + CHUNK
    req = urllib.request.Request(recipe["url"], headers={
        "User-Agent": USER_AGENT, "Referer": recipe["referer"], "Range": f"bytes={start}-{end}"})
    return urllib.request.urlopen(req, timeout=60, context=_ssl_context())


def fetch(dest, recipe=RECIPE, progress=None, opener=_open, cancelled=lambda: False):
    """Download, decode and verify the DLL into dest. Leaves nothing behind on failure.

    progress(done_bytes_of_dll, dll_size) is called as the DLL is produced.
    """
    try:
        import lzma  # imported here so a Python without it still loads the plugin and can say why
    except ImportError as e:
        raise FetchError("this Decky Loader's Python has no lzma module; the DLL cannot be decoded") from e
    skip, size = recipe["dll_offset"], recipe["dll_size"]
    decoder = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[
        {"id": lzma.FILTER_X86, "start_offset": recipe["unpacked_offset"] % 2**32},
        {"id": lzma.FILTER_LZMA2, "dict_size": 2**24},
    ])
    digest = hashlib.sha256()
    tmp = dest + ".part"
    got = 0
    try:
        with opener(recipe) as resp, open(tmp, "wb") as out:
            if getattr(resp, "status", 206) != 206:
                raise FetchError(f"server ignored the range request (HTTP {resp.status})")
            while got < size:
                if cancelled():
                    raise FetchError("cancelled")
                chunk = resp.read(CHUNK)
                if not chunk:
                    raise FetchError("download ended before the DLL was complete")
                try:
                    data = decoder.decompress(chunk)
                except lzma.LZMAError as e:
                    raise FetchError(f"AMD package does not match the recipe ({e})") from e
                if skip:
                    cut = min(skip, len(data))
                    skip -= cut
                    data = data[cut:]
                data = data[:size - got]
                if data:
                    out.write(data)
                    digest.update(data)
                    got += len(data)
                    if progress:
                        progress(got, size)
        if digest.hexdigest() != recipe["sha256"]:
            raise FetchError("checksum mismatch: AMD changed the package, a new recipe is needed")
        os.replace(tmp, dest)
    except OSError as e:
        raise FetchError(f"network or disk error: {e}") from e
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
