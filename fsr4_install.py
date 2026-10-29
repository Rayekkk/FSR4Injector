# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Putting our two DLLs next to a game and taking them away again.

Rules that make rollback safe:
  * we only ever add files; a file of the same name that is not ours stops the install,
  * the manifest records every file we wrote with its sha256, and we delete only files whose hash still matches,
  * launch options: our amdxc64=n,b goes into WINEDLLOVERRIDES next to whatever is already there (the user's own
    overrides or another tool's; a game can have only one such variable). On removal we restore the original
    string when nobody edited the options since, otherwise we take out only our own entry.
"""

import calendar
import hashlib
import json
import os
import re
import secrets
import time

import dk_fs
from dk_fs import sha256_file

SHIM = "amdxc64.dll"
FFX = "amdxcffx64.dll"
GPU = "fsr4injector.gpu"  # the GPU's real family/revision for the shim
STATUS = "fsr4injector.status.json"
MODE_NATIVE = "native"  # the game's own FidelityFX path (FSR 3.1+)
# Required: without it Wine loads its builtin amdxc64 from system32 and ignores ours (checked on Proton 11).
TOKEN = "WINEDLLOVERRIDES=amdxc64=n,b"
ENTRY = "amdxc64=n,b"  # our entry inside WINEDLLOVERRIDES
_OVERRIDES = re.compile(r"""^WINEDLLOVERRIDES=(["']?)(.*)\1$""")
WATERMARK = "FSR_WATERMARK=1"  # the shim turns it into AMD's own on-screen FSR 4 watermark


def launch_prefix(watermark=False):
    """What goes in front of %command%; also what the panel's copy buttons copy."""
    return f"{TOKEN} {WATERMARK}" if watermark else TOKEN


class InstallError(Exception):
    pass


def _check_manifest(data):
    """dk_fs's validate hook: app id -> an entry with the fields everything here relies on."""
    dk_fs.require_object(data)
    for appid, e in data.items():
        if (not appid.isdigit() or not isinstance(e, dict) or not isinstance(e.get("target_dir"), str)
                or not isinstance(e.get("files"), dict)
                or not all(isinstance(k, str) and isinstance(v, str) for k, v in e["files"].items())
                or not isinstance(e.get("launch_original", ""), str)
                or not isinstance(e.get("launch_applied") or "", str)):
            raise ValueError(f"entry {appid!r} is not a game set up by this plugin")


class Manifest:
    """appid -> {target_dir, files: {name: sha256}, launch_original, launch_applied, enabled_at, verified, missed}

    It is the only record of what the plugin put into game folders. A damaged file comes back from its last-good
    copy; when that is impossible (or the file cannot be read) `problem` says why and nothing is saved over it, so
    the record is never lost to a later change."""

    def __init__(self, path):
        self.path, self.entries, self.problem, self.recovered = path, {}, "", ""
        try:
            loaded = dk_fs.load_json(path, {}, validate=_check_manifest)
        except OSError as e:
            self.problem = f"The list of games set up could not be read ({e.strerror or type(e).__name__})."
            return
        if loaded.status == "lost":
            self.problem = ("The list of games set up is damaged, so no game can be changed. It is kept as it is; "
                            "the Decky log has the details.")
        self.recovered = loaded.detail if loaded.status in ("lost", "recovered") else ""
        self.entries = {int(k): v for k, v in loaded.value.items()}

    def save(self):
        if self.problem:
            raise InstallError(self.problem)
        dk_fs.write_json(self.path, {str(k): v for k, v in self.entries.items()})


def _override_entries(word):
    """The entries of a WINEDLLOVERRIDES=... launch option word, or None for any other word."""
    match = _OVERRIDES.match(word)
    return [e for e in match.group(2).split(";") if e] if match else None


def _without_amdxc64(entries):
    """Entries with amdxc64 taken out; in a list sharing one mode ('dxgi,amdxc64=n,b') the others keep it."""
    kept = []
    for entry in entries:
        dlls, sep, mode = entry.partition("=")
        rest = [d for d in dlls.split(",") if d and d.lower() != "amdxc64"]
        if rest:
            kept.append(",".join(rest) + sep + mode)
    return kept


def _overrides_word(entries):
    value = ";".join(entries)
    return f'WINEDLLOVERRIDES="{value}"' if ";" in value else f"WINEDLLOVERRIDES={value}"


def _without_ours(words):
    """Launch option words with our amdxc64 entry taken out of WINEDLLOVERRIDES (dropped once it is empty)."""
    out = []
    for word in words:
        entries = _override_entries(word)
        if entries is not None:
            kept = _without_amdxc64(entries)
            if not kept:
                continue
            word = _overrides_word(kept)
        out.append(word)
    return out


def has_token(options):
    """Whether the launch options load our amdxc64: amdxc64=n,b in WINEDLLOVERRIDES, alone or in a DLL list."""
    for word in (options or "").split():
        for entry in _override_entries(word) or []:
            dlls, _, mode = entry.partition("=")
            if mode == "n,b" and "amdxc64" in (d.lower() for d in dlls.split(",")):
                return True
    return False


def with_token(options, watermark=False):
    """Launch options with amdxc64=n,b merged into WINEDLLOVERRIDES (and the watermark next to it).

    Without other overrides this is our token in front, as it always was; %command% is added when the options had
    none (they were the game's arguments).
    """
    words = [w for w in (options or "").split() if not (watermark and w == WATERMARK)]
    for i, word in enumerate(words):
        entries = _override_entries(word)
        if entries is not None:
            words[i] = _overrides_word(_without_amdxc64(entries) + [ENTRY])
            if watermark:
                words.insert(i + 1, WATERMARK)
            break
    else:
        if "%command%" not in words:
            words = ["%command%"] + words
        words = launch_prefix(watermark).split() + words
    if "%command%" not in words:
        words.append("%command%")
    return " ".join(words)


def without_token(current, original, applied):
    """Undo with_token: the original when untouched since, else just our entry and watermark taken out (other
    overrides and a watermark the user already had stay)."""
    current = (current or "").strip()
    if current == applied:
        return original
    users_watermark = WATERMARK in (original or "").split()
    words = [w for w in _without_ours(current.split()) if w != WATERMARK or users_watermark]
    if words == ["%command%"] and "%command%" not in original:
        return original
    return " ".join(words)


# Game files: never written through a symlink (dk_fs's no_links), and a failed copy (a full SD card) leaves neither
# half a DLL nor its temp file. The game folder itself may be a link (a game moved to another drive), so it is
# resolved first; no_links alone would refuse it.

def _real(dst):
    return os.path.join(os.path.realpath(os.path.dirname(dst)), os.path.basename(dst))


def _copy(src, dst):
    with open(src, "rb") as f:
        dk_fs.write_atomic(_real(dst), f, no_links=True)


def _link_or_copy(src, dst):
    """A hard link to src where the file system allows it, so every game shares one 82 MB copy of AMD's library;
    a copy on another drive (an SD card), on FAT/exFAT or where links are refused. The link gets a fresh temp name
    and is renamed into place (a rename replaces a symlink itself, never its target)."""
    tmp = f"{dst}.{secrets.token_hex(6)}.fsr4i-tmp"
    try:
        os.link(src, tmp)
    except OSError:
        return _copy(src, dst)
    try:
        os.replace(tmp, dst)
    except OSError:
        os.remove(tmp)
        raise


def _write(dst, data):
    dk_fs.write_atomic(_real(dst), data, no_links=True)


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
    original = " ".join(_without_ours((launch_options or "").split()))
    entry = manifest.entries.get(appid) or {"target_dir": target, "files": {}, "launch_original": original}
    entry.setdefault("mode", MODE_NATIVE)
    new_options = with_token(launch_options, watermark) if launch else None
    try:
        for name in want:
            dst = os.path.join(target, name)
            if name == GPU:
                _write(dst, gpu_file_content(gpu))
            else:
                (_link_or_copy if name == FFX else _copy)(sources[name], dst)
            entry["files"][name] = want[name]
            manifest.entries[appid] = entry  # recorded as soon as a file exists, so a crash can still be undone
            manifest.save()
        if launch:
            entry["launch_applied"] = new_options
        entry["enabled_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        manifest.save()
    except dk_fs.UnsafePath as e:
        raise InstallError("a file the plugin writes is a link in the game folder; leaving it alone") from e
    except OSError as e:
        raise InstallError(f"could not write to the game folder ({e.strerror or type(e).__name__})") from e
    return new_options if launch else (launch_options or "").strip()


def set_watermark(manifest, appid, current, on):
    """Add or take out FSR_WATERMARK=1 in a game whose launch options we manage; None when we do not."""
    entry = manifest.entries.get(appid)
    if not entry or entry.get("launch_applied") is None:  # None: the user manages them ("" is ours, emptied)
        return None
    if on:
        new = with_token(current, True)
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
        except OSError:  # usually absent (the game never ran); a leftover status is harmless and never ours to keep
            pass
    if entry.get("launch_applied") is not None:
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
    except (OSError, ValueError, RecursionError):
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
    "missed": not loaded although the token is there; often harmless (closed in a launcher, DirectX 11 mode), so the
    caller only warns when it happens again.
    """
    started = _epoch((status or {}).get("started"))
    if session_start and (started is None or started < session_start - 5):  # shim clock has 1 s resolution
        if not has_token(launch_options):
            if not managed:
                return "failed", (f"FSR4 Injector was not loaded: add {TOKEN} in front of %command% in the game's "
                                  "launch options (Copy launch options in the plugin).")
            return "failed", (f"FSR4 Injector was not loaded: the game's launch options no longer contain {TOKEN} "
                              "(another tool may have changed them). Toggle the game off and on to repair.")
        return "missed", ("FSR4 Injector's DLL was not loaded in this session (the game did not start DirectX 12, "
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
