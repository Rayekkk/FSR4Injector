# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Checking GitHub for a newer FSR4 Injector release and saving its ZIP to the user's Downloads folder (as the Companion plugins do).

Only a published, stable release of this repository is accepted, with exactly one FSR4Injector-<version>.zip whose
size and SHA-256 GitHub reports; the ZIP is checked entry by entry before it is kept. Installing stays the user's
step (Decky → Developer → Install Plugin from ZIP), so nothing runs that the user did not pick.
"""

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
import zipfile

from fsr4_dll import _ssl_context

REPOSITORY = "Rayekkk/FSR4Injector"
PLUGIN_NAME = "FSR4 Injector"
ARCHIVE_ROOT = "FSR4Injector"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASE_BASE = f"https://github.com/{REPOSITORY}/releases"
MAX_METADATA = 1 << 20
MAX_DOWNLOAD = 32 << 20
MAX_EXPANDED = 64 << 20
MAX_MEMBERS = 512
TIMEOUT = 10
_VERSION = re.compile(r"(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})")
_DIGEST = re.compile(r"sha256:([0-9a-fA-F]{64})")


class UpdateError(Exception):
    pass


def downloads_dir(home):
    """The user's download folder: XDG_DOWNLOAD_DIR, which a desktop in another language names differently
    (e.g. ~/Pobrane), else ~/Downloads. Only a folder inside home is accepted."""
    try:
        with open(os.path.join(home, ".config", "user-dirs.dirs"), encoding="utf-8") as f:
            for line in f:
                match = re.fullmatch(r'\s*XDG_DOWNLOAD_DIR="([^"\r\n]*)"\s*', line.rstrip("\n"))
                if not match:
                    continue
                path = match.group(1)
                if path.startswith("$HOME/"):
                    path = home + path[5:]
                if path.startswith(home + "/") and "$" not in path and ".." not in path.split("/"):
                    return path
                break
    except (OSError, UnicodeError):
        pass
    return os.path.join(home, "Downloads")


def version_tuple(value):
    if not isinstance(value, str) or not _VERSION.fullmatch(value):
        raise UpdateError("The release version must use stable X.Y.Z numbering.")
    return tuple(int(part) for part in value.split("."))


def _open(url, opener, current):
    request = urllib.request.Request(url, headers={"User-Agent": f"FSR4Injector/{current}",
                                                   "Accept": "application/vnd.github+json"})
    return opener(request, timeout=TIMEOUT, context=_ssl_context())


def _read(response, limit):
    data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("GitHub sent more data than expected.")
    return data


def parse_release(data, current):
    """(view for the panel, release to download or None) from GitHub's latest-release JSON."""
    if not isinstance(data, dict) or not isinstance(data.get("tag_name"), str):
        raise UpdateError("GitHub returned no stable release.")
    tag = data["tag_name"]
    version = tag[1:] if tag.startswith("v") else tag
    available = version_tuple(version) > version_tuple(current)
    if data.get("draft") is not False or data.get("prerelease") is not False:
        raise UpdateError("Only published stable releases can be downloaded.")
    if data.get("html_url") != f"{RELEASE_BASE}/tag/{tag}":
        raise UpdateError("The release does not belong to the FSR4 Injector repository.")
    view = {"current_version": current, "latest_version": version, "update_available": available}
    name = f"{ARCHIVE_ROOT}-{version}.zip"
    assets = data.get("assets") if isinstance(data.get("assets"), list) else []
    matching = [a for a in assets if isinstance(a, dict) and a.get("name") == name]
    if len(matching) != 1:
        if available:
            view["error"] = "The release has no FSR4 Injector ZIP yet."
        return view, None
    asset, url = matching[0], f"{RELEASE_BASE}/download/{tag}/{name}"
    size, digest = asset.get("size"), asset.get("digest")
    if (asset.get("browser_download_url") != url or asset.get("state") != "uploaded" or type(size) is not int or
            not 0 < size <= MAX_DOWNLOAD or not isinstance(digest, str) or not _DIGEST.fullmatch(digest)):
        if available:
            view["error"] = "The release ZIP is missing a trusted size, address or SHA-256."
        return view, None
    view["asset_name"] = name
    return view, {"version": version, "name": name, "url": url, "size": size,
                  "sha256": _DIGEST.fullmatch(digest).group(1).lower()}


def validate_archive(path, version):
    """Refuse a ZIP that is not this plugin at this version, or that could write outside its folder."""
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if not members or len(members) > MAX_MEMBERS:
                raise UpdateError("The release ZIP is empty or has too many entries.")
            total = 0
            for m in members:
                parts = m.filename.rstrip("/").split("/")
                if ("\\" in m.filename or ":" in m.filename or parts[0] != ARCHIVE_ROOT or
                        any(p in ("", ".", "..") for p in parts) or any(ord(c) < 32 for c in m.filename)):
                    raise UpdateError("The release ZIP contains an unsafe entry.")
                total += m.file_size
                if total > MAX_EXPANDED:
                    raise UpdateError("The release ZIP expands beyond the size limit.")
            if archive.testzip() is not None:
                raise UpdateError("The release ZIP is damaged.")
            manifest = json.loads(archive.read(f"{ARCHIVE_ROOT}/plugin.json"))
            for required in ("main.py", "dist/index.js", "bin/amdxc64.dll"):
                archive.getinfo(f"{ARCHIVE_ROOT}/{required}")
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as e:
        if isinstance(e, UpdateError):
            raise
        raise UpdateError("The release ZIP is not a complete FSR4 Injector package.") from e
    if not isinstance(manifest, dict) or manifest.get("name") != PLUGIN_NAME or manifest.get("version") != version:
        raise UpdateError("The release ZIP contains a different plugin or version.")


def check(current, opener=urllib.request.urlopen):
    """Panel view of the latest release, never raising: failures come back as {"error": ...}."""
    try:
        return _check(current, opener)[0]
    except UpdateError as e:
        return {"current_version": current, "update_available": False, "error": str(e)}


def _check(current, opener):
    try:
        with _open(API_URL, opener, current) as response:
            data = json.loads(_read(response, MAX_METADATA))
    except urllib.error.HTTPError as e:
        if e.code == 404:  # no release published yet
            return {"current_version": current, "update_available": False}, None
        raise UpdateError("GitHub's request limit was reached. Try again later." if e.code in (403, 429)
                          else f"GitHub could not check releases (HTTP {e.code}).") from e
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError("Could not connect securely to GitHub. Check the connection and try again.") from e
    except ValueError as e:
        raise UpdateError("GitHub returned unreadable release data.") from e
    return parse_release(data, current)


def download(current, expected_version, downloads_dir, opener=urllib.request.urlopen):
    """Save the expected release's ZIP to downloads_dir; {"path", "version"} or {"error"}."""
    try:
        _, release = _check(current, opener)
        if not release or release["version"] != expected_version:
            raise UpdateError("The latest release changed. Check for updates again.")
        os.makedirs(downloads_dir, exist_ok=True)
        final = os.path.join(downloads_dir, release["name"])
        tmp = final + ".part"
        digest, count = hashlib.sha256(), 0
        try:
            with _open(release["url"], opener, current) as response, open(tmp, "wb") as f:
                while chunk := response.read(1 << 16):
                    count += len(chunk)
                    if count > release["size"]:
                        raise UpdateError("The release ZIP is larger than GitHub said.")
                    digest.update(chunk)
                    f.write(chunk)
            if count != release["size"] or digest.hexdigest() != release["sha256"]:
                raise UpdateError("The release ZIP does not match its SHA-256; nothing was kept.")
            validate_archive(tmp, release["version"])
            os.replace(tmp, final)
        except (urllib.error.URLError, OSError) as e:
            raise UpdateError("The release ZIP could not be downloaded. Check the connection and try again.") from e
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return {"path": final, "version": release["version"]}
    except UpdateError as e:
        return {"error": str(e)}
