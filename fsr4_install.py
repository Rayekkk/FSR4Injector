# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Putting our two DLLs next to a game and taking them away again.

Rules that make rollback safe:
  * we only ever add files; a file of the same name that is not ours stops the install,
  * the manifest records every file we wrote with its sha256, and we delete only files whose hash still matches,
  * launch options: we remember the original string and, on removal, restore it when nobody edited them since,
    otherwise we take out only our own token.
"""

import calendar
import hashlib
import json
import os
import shutil
import time

from fsr4_dll import sha256_file

SHIM = "amdxc64.dll"
FFX = "amdxcffx64.dll"
GPU = "fsr4injector.gpu"  # the GPU's real family/revision for the shim
STATUS = "fsr4injector.status.json"
MODE_NATIVE = "native"  # the game's own FidelityFX path (FSR 3.1+)
# Required: without it Wine loads its builtin amdxc64 from system32 and ignores ours (checked on Proton 11).
TOKEN = "WINEDLLOVERRIDES=amdxc64=n,b"
WATERMARK = "FSR_WATERMARK=1"  # the shim turns it into AMD's own on-screen FSR 4 watermark


def launch_prefix(watermark=False):
    """What goes in front of %command%; also what the panel's copy buttons copy."""
    return f"{TOKEN} {WATERMARK}" if watermark else TOKEN


class InstallError(Exception):
    pass


class Manifest:
    """appid -> {target_dir, files: {name: sha256}, launch_original, launch_applied, enabled_at}"""

    def __init__(self, path):
        self.path = path
        try:
            with open(path, encoding="utf-8") as f:
                self.entries = {int(k): v for k, v in json.load(f).items()}
        except (OSError, ValueError):
            self.entries = {}

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in self.entries.items()}, f, indent=1)
        os.replace(tmp, self.path)


def with_token(options, watermark=False):
    """Launch options with our token (and the watermark) in front; %command% added when the options had none."""
    words = [w for w in (options or "").split() if w != TOKEN and not (watermark and w == WATERMARK)]
    options = " ".join(words)
    if "WINEDLLOVERRIDES=" in options:
        raise InstallError("this game already sets WINEDLLOVERRIDES in its launch options: turn off \"Add launch option "
                           "automatically\" and add amdxc64=n,b to that override yourself")
    if "%command%" not in options:
        options = f"%command% {options}".strip()
    return f"{launch_prefix(watermark)} {options}"


def without_token(current, original, applied):
    """Undo with_token: the original when untouched since, else just our words removed (a watermark the user
    already had stays)."""
    current = (current or "").strip()
    if current == applied:
        return original
    users_watermark = WATERMARK in (original or "").split()
    words = [w for w in current.split() if w != TOKEN and (w != WATERMARK or users_watermark)]
    if words == ["%command%"] and "%command%" not in original:
        return original
    return " ".join(words)


def _replace_via_tmp(dst, fill):
    """Write through a temp file, so a failed copy (a full SD card) never leaves half a DLL or the temp file."""
    tmp = dst + ".fsr4i-tmp"
    try:
        fill(tmp)
        os.replace(tmp, dst)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _copy(src, dst):
    _replace_via_tmp(dst, lambda tmp: shutil.copyfile(src, tmp))


def _write(dst, data):
    def fill(tmp):
        with open(tmp, "wb") as f:
            f.write(data)
    _replace_via_tmp(dst, fill)


def gpu_file_content(gpu):
    return f"{gpu['device']} {gpu['family']} {gpu['rev']}\n".encode()


def enable(manifest, game, shim_path, ffx_path, launch_options, gpu=None, launch=True, watermark=False):
    """Install into game["target_dir"]; returns the launch options to apply.

    gpu: fsr4_gpu.detect() result; written next to the shim so it passes the real family/revision to AMD's DLL.
    launch: False leaves the launch options to the user (returned unchanged, and never touched on disable).
    """
    appid, target = game["appid"], game["target_dir"]
    sources = {SHIM: shim_path, FFX: ffx_path}
    want = {SHIM: sha256_file(shim_path), FFX: sha256_file(ffx_path)}
    if gpu:
        want[GPU] = hashlib.sha256(gpu_file_content(gpu)).hexdigest()
    known = manifest.entries.get(appid, {}).get("files", {})

    for name in want:
        path = os.path.join(target, name)
        if os.path.exists(path) and sha256_file(path) not in (want[name], known.get(name)):
            raise InstallError(f"{name} already exists in the game folder and is not ours; leaving it alone")

    # Our token can already be there (left by an earlier install); it is never part of the user's original.
    original = " ".join(w for w in (launch_options or "").split() if w != TOKEN)
    entry = manifest.entries.get(appid) or {"target_dir": target, "files": {}, "launch_original": original}
    entry.setdefault("mode", MODE_NATIVE)
    new_options = with_token(launch_options, watermark) if launch else None
    try:
        for name in want:
            dst = os.path.join(target, name)
            if name == GPU:
                _write(dst, gpu_file_content(gpu))
            else:
                _copy(sources[name], dst)
            entry["files"][name] = want[name]
            manifest.entries[appid] = entry  # recorded as soon as a file exists, so a crash can still be undone
            manifest.save()
    except OSError as e:
        raise InstallError(f"could not write to the game folder: {e}") from e

    if launch:
        entry["launch_applied"] = new_options
    entry["enabled_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest.save()
    return new_options if launch else (launch_options or "").strip()


def set_watermark(manifest, appid, current, on):
    """Add or take out FSR_WATERMARK=1 in a game whose launch options we manage; None when we do not."""
    entry = manifest.entries.get(appid)
    if not entry or not entry.get("launch_applied"):
        return None
    if on:
        try:
            new = with_token(current, True)
        except InstallError:
            return None
    else:
        users_watermark = WATERMARK in entry.get("launch_original", "").split()
        new = " ".join(w for w in (current or "").split() if w != WATERMARK or users_watermark)
    entry["launch_applied"] = new
    manifest.save()
    return new


def refresh_shim(manifest, shim_path):
    """After a plugin update, bring games' amdxc64.dll up to the bundled build; returns how many were updated.

    Only files that still match what we installed are replaced, so nothing the user put there is touched.
    """
    try:
        want = sha256_file(shim_path)
    except OSError:
        return 0
    updated = 0
    for entry in manifest.entries.values():
        had = entry["files"].get(SHIM)
        path = os.path.join(entry["target_dir"], SHIM)
        try:
            if not had or had == want or sha256_file(path) != had:
                continue
            _copy(shim_path, path)
        except OSError:
            continue
        entry["files"][SHIM] = want
        updated += 1
    if updated:
        manifest.save()
    return updated


def disable(manifest, appid, launch_options):
    """Remove what we installed. Returns {launch_options, kept: [files left because they changed]}."""
    entry = manifest.entries.get(appid)
    if not entry:
        return {"launch_options": (launch_options or "").strip(), "kept": []}
    kept = []
    for name, digest in entry["files"].items():
        path = os.path.join(entry["target_dir"], name)
        try:
            if not os.path.exists(path):
                continue
            if sha256_file(path) == digest:
                os.remove(path)
            else:
                kept.append(name)
        except OSError:
            kept.append(name)
    for name in (STATUS, STATUS + ".tmp"):  # written by the shim at runtime
        try:
            os.remove(os.path.join(entry["target_dir"], name))
        except OSError:
            pass
    if entry.get("launch_applied"):
        restored = without_token(launch_options, entry.get("launch_original", ""), entry["launch_applied"])
    else:  # the user manages this game's launch options
        restored = (launch_options or "").strip()
    del manifest.entries[appid]
    manifest.save()
    return {"launch_options": restored, "kept": kept}


def read_status(manifest, appid):
    """Last session status written by the shim, or None."""
    entry = manifest.entries.get(appid)
    if not entry:
        return None
    try:
        # errors="replace": the Proton path in it comes from a Windows code page, not always valid UTF-8
        with open(os.path.join(entry["target_dir"], STATUS), encoding="utf-8", errors="replace") as f:
            status = json.load(f)
    except (OSError, ValueError):
        return None
    return status if isinstance(status, dict) else None


def _epoch(iso):
    try:
        return calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return None


def session_verdict(status, session_start, launch_options, managed=True):
    """verdict() for a session that just ended: a status not written during it means our DLL never loaded.

    managed: whether the plugin set the launch options (else the user adds the token by hand).
    """
    started = _epoch((status or {}).get("started"))
    if session_start and (started is None or started < session_start - 5):  # shim clock has 1 s resolution
        if TOKEN not in (launch_options or "").split():
            if not managed:
                return "failed", (f"FSR4 Injector was not loaded: add {TOKEN} in front of %command% in the game's "
                                  "launch options (Copy launch options in the plugin).")
            return "failed", (f"FSR4 Injector was not loaded: the game's launch options no longer contain {TOKEN} "
                              "(another tool may have changed them). Toggle the game off and on to repair.")
        return "failed", ("FSR4 Injector's DLL was not loaded in this session (the game did not start DirectX 12, "
                          "for example it ran in DirectX 11 mode or was closed in its launcher).")
    return verdict(status)


def verdict(status):
    """(ok | unused | failed | unknown, human-readable reason) for a session status."""
    if not status:
        return "unknown", "Start the game and use FSR once."
    if not status.get("ffx_requested"):
        return "unused", "Pick AMD FSR as the upscaler in the game's graphics settings."
    active = status.get("active")
    if active in ("INT8_LITE", "INT8", "INT8_NAVI2", "FP8"):
        return "ok", f"FSR {str(status.get('provider') or '').strip(' *') or '4'} ({active}) ran in the last session."
    if not status.get("dll_loaded"):
        return "failed", "The AMD FSR4 DLL did not load."
    if not status.get("family"):
        return "failed", f"GPU {status.get('gpu', '?')} is not supported by this plugin version."
    if active == "unknown":
        return "failed", "This AMD DLL version is not recognised; the plugin needs an update."
    if active == "FSR3":
        return "failed", "The AMD DLL refused FSR4 and fell back to FSR3 (likely after a SteamOS/Proton update)."
    return "unknown", "FSR was requested but the result is not known yet."
