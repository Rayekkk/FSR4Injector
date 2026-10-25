# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""The About section's updater: which GitHub releases are trusted and what is kept in ~/Downloads."""

import hashlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
import zipfile

import _harness  # noqa: F401
import fsr4_updates as U


def _zip(version, extra=None, root="FSR4Injector", name="FSR4 Injector"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{root}/plugin.json", json.dumps({"name": name, "version": version}))
        for rel in ("main.py", "dist/index.js", "bin/amdxc64.dll"):
            z.writestr(f"{root}/{rel}", b"x")
        for path, data in (extra or {}).items():
            z.writestr(path, data)
    return buf.getvalue()


def _release(version, data, digest=None, **over):
    tag, name = version, f"FSR4Injector-{version}.zip"
    rel = {"tag_name": tag, "draft": False, "prerelease": False, "html_url": f"{U.RELEASE_BASE}/tag/{tag}",
           "assets": [{"name": name, "state": "uploaded", "size": len(data),
                       "browser_download_url": f"{U.RELEASE_BASE}/download/{tag}/{name}",
                       "digest": "sha256:" + (digest or hashlib.sha256(data).hexdigest())}]}
    rel.update(over)
    return rel


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def opener(routes):
    def open_(request, timeout=None, context=None):
        body = routes[request.full_url]
        if isinstance(body, Exception):
            raise body
        return _Response(body)
    return open_


class Updates(unittest.TestCase):
    def setUp(self):
        self.downloads = os.path.join(tempfile.mkdtemp(), "Downloads")

    def serve(self, release, data):
        return opener({U.API_URL: json.dumps(release).encode(),
                       release["assets"][0]["browser_download_url"] if release.get("assets") else "": data})

    def test_newer_release_is_saved_after_every_check(self):
        data = _zip("1.1.0")
        o = self.serve(_release("1.1.0", data), data)
        view = U.check("1.0.0", o)
        self.assertEqual((view["latest_version"], view["update_available"]), ("1.1.0", True))
        res = U.download("1.0.0", "1.1.0", self.downloads, o)
        self.assertEqual(res["path"], os.path.join(self.downloads, "FSR4Injector-1.1.0.zip"))
        with open(res["path"], "rb") as f:
            self.assertEqual(f.read(), data)

    def test_same_version_is_up_to_date(self):
        data = _zip("1.0.0")
        view = U.check("1.0.0", self.serve(_release("1.0.0", data), data))
        self.assertFalse(view["update_available"])
        self.assertNotIn("error", view)

    def test_untrusted_releases_are_refused(self):
        data = _zip("1.1.0")
        for bad in (_release("1.1.0", data, draft=True), _release("1.1.0", data, prerelease=True),
                    _release("1.1.0", data, html_url="https://github.com/someone/fork/releases/tag/1.1.0"),
                    _release("1.1-beta", data)):
            self.assertIn("error", U.check("1.0.0", self.serve(bad, data)), bad)
        no_digest = _release("1.1.0", data)
        del no_digest["assets"][0]["digest"]
        self.assertIn("SHA-256", U.check("1.0.0", self.serve(no_digest, data))["error"])

    def test_nothing_is_kept_from_a_bad_download(self):
        data = _zip("1.1.0")
        cases = [
            (_release("1.1.0", data, digest="0" * 64), data, "SHA-256"),
            (_release("1.1.0", _zip("1.1.0", {"FSR4Injector/../evil.sh": b"x"})),
             _zip("1.1.0", {"FSR4Injector/../evil.sh": b"x"}), "unsafe"),
            (_release("1.1.0", _zip("1.0.9")), _zip("1.0.9"), "different plugin or version"),
            (_release("1.1.0", _zip("1.1.0", name="Other")), _zip("1.1.0", name="Other"), "different plugin"),
        ]
        for release, served, message in cases:
            res = U.download("1.0.0", "1.1.0", self.downloads, self.serve(release, served))
            self.assertIn(message, res.get("error", ""), message)
            self.assertEqual(os.listdir(self.downloads) if os.path.isdir(self.downloads) else [], [])

    def test_release_changed_since_the_check(self):
        data = _zip("1.2.0")
        res = U.download("1.0.0", "1.1.0", self.downloads, self.serve(_release("1.2.0", data), data))
        self.assertIn("changed", res["error"])

    def test_downloads_folder_follows_the_desktop_language(self):
        home = tempfile.mkdtemp()
        self.assertEqual(U.downloads_dir(home), os.path.join(home, "Downloads"))  # no user-dirs.dirs
        cfg = os.path.join(home, ".config")
        os.makedirs(cfg)
        for line, want in (('XDG_DOWNLOAD_DIR="$HOME/Pobrane"', home + "/Pobrane"),
                           (f'XDG_DOWNLOAD_DIR="{home}/Téléchargements"', home + "/Téléchargements"),
                           ('XDG_DOWNLOAD_DIR="/tmp"', os.path.join(home, "Downloads")),  # outside home
                           ('XDG_DOWNLOAD_DIR="$HOME/../x"', os.path.join(home, "Downloads")),
                           ('XDG_DOWNLOAD_DIR="$OTHER/x"', os.path.join(home, "Downloads"))):
            with open(os.path.join(cfg, "user-dirs.dirs"), "w", encoding="utf-8") as f:
                f.write(f'# comment\nXDG_DESKTOP_DIR="$HOME/Pulpit"\n{line}\n')
            self.assertEqual(U.downloads_dir(home), want, line)

    def test_github_errors(self):
        def http(code):
            return opener({U.API_URL: urllib.error.HTTPError(U.API_URL, code, "x", {}, None)})
        self.assertEqual(U.check("1.0.0", http(404)), {"current_version": "1.0.0", "update_available": False})
        self.assertIn("request limit", U.check("1.0.0", http(403))["error"])
        self.assertIn("connect", U.check("1.0.0", opener({U.API_URL: urllib.error.URLError("down")}))["error"])
        self.assertIn("unreadable", U.check("1.0.0", opener({U.API_URL: b"<html>"}))["error"])


if __name__ == "__main__":
    unittest.main()
