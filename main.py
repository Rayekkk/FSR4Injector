# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""FSR4Injector - official AMD FSR 4.1 (Lite model) for RDNA 3.5 APUs under Proton.

Two files go next to a game's FidelityFX DLL: AMD's own amdxcffx64.dll (fetched from AMD, see fsr4_dll) and our
amdxc64.dll shim (shim/, LGPL), which tells the AMD DLL the GPU family Wine cannot provide. Launch options are
applied by the frontend through SteamClient; this backend computes them so they can be undone exactly.
"""

import asyncio
import json
import os
import sys
import time

import decky

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

import fsr4_dll  # noqa: E402
import fsr4_env  # noqa: E402
import fsr4_games  # noqa: E402
import fsr4_gpu  # noqa: E402
import fsr4_install  # noqa: E402

SHIM_PATH = os.path.join(PLUGIN_DIR, "bin", fsr4_install.SHIM)
# Decky imports the frontend while _main is still running (it hashes the 85 MB DLL); calls wait for it.
_ready = asyncio.Event()


def _data_dir():
    return getattr(decky, "DECKY_PLUGIN_RUNTIME_DIR", decky.DECKY_PLUGIN_SETTINGS_DIR)


def _ffx_path():
    return os.path.join(_data_dir(), fsr4_install.FFX)


def gpu_unsupported(gpu):
    if not gpu:
        return "No AMD GPU was found, or its details could not be read."
    return (f"AMD's FSR 4 has no model for this GPU (PCI 1002:{gpu['device']:04x}, family {gpu['family']}, "
            f"revision {gpu['rev']}), so games would stay on FSR 3.")


def _steam_root():
    home = getattr(decky, "DECKY_USER_HOME", os.path.expanduser("~"))
    return os.path.join(home, ".local", "share", "Steam")


class Plugin:
    async def _main(self):
        os.makedirs(_data_dir(), exist_ok=True)
        os.makedirs(decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
        self.manifest = fsr4_install.Manifest(os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "manifest.json"))
        self.games = []
        self.download = {"state": "idle", "done": 0, "total": fsr4_dll.RECIPE["dll_size"], "error": ""}
        self.dll_ok = await asyncio.to_thread(fsr4_dll.is_valid, _ffx_path())
        self.gpu = await asyncio.to_thread(fsr4_gpu.detect)
        decky.logger.info(f"GPU: {self.gpu}")
        self.lock = asyncio.Lock()
        self._cancel = False
        self.sessions = {}  # appid -> session start (epoch s)
        self.scanned = False
        refreshed = await asyncio.to_thread(fsr4_install.refresh_shim, self.manifest, SHIM_PATH)
        if refreshed:
            decky.logger.info(f"updated amdxc64.dll in {refreshed} configured game(s)")
        _ready.set()
        # First panel open should not wait for a library walk.
        self._scan_task = asyncio.create_task(self.scan_games())

    def _game_view(self, g):
        appid = g["appid"]
        entry = self.manifest.entries.get(appid)
        status = fsr4_install.read_status(self.manifest, appid)
        verdict, reason = fsr4_install.verdict(status)
        if entry and verdict == "ok":
            changed = fsr4_env.changes(entry.get("verified"))
            if changed:
                verdict, reason = "changed", f"Updated since FSR4 was last confirmed: {', '.join(changed)}. Play once to re-check."
        return {**g, "enabled": entry is not None, "verdict": verdict, "reason": reason}

    async def get_state(self) -> dict:
        await _ready.wait()
        enabled_missing = [{"appid": a, "name": f"App {a}", "target_dir": e["target_dir"], "anticheat": False}
                           for a, e in self.manifest.entries.items() if a not in {g["appid"] for g in self.games}]
        return {
            "dll_ready": self.dll_ok,
            "shim_ready": os.path.isfile(SHIM_PATH),
            "gpu": self.gpu,
            "recipe": {k: fsr4_dll.RECIPE[k] for k in ("driver", "fsr", "dll_size")},
            "eula_url": fsr4_dll.EULA_URL,
            "download": self.download,
            "scanned": self.scanned,
            "games": [self._game_view(g) for g in self.games + enabled_missing],
        }

    async def scan_games(self) -> dict:
        self.games = await asyncio.to_thread(fsr4_games.scan, _steam_root())
        self.scanned = True
        return await self.get_state()

    async def startup_notice(self) -> dict:
        """One-time message after a SteamOS update, when games are set up; '' otherwise."""
        await _ready.wait()
        path = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "env.json")
        now = fsr4_env.steamos_build()
        try:
            with open(path, encoding="utf-8") as f:
                before = json.load(f).get("steamos", "")
        except (OSError, ValueError):
            before = ""
        message = ""
        if before and now and before != now and self.manifest.entries:
            message = (f"SteamOS was updated ({before} → {now}). FSR4 is re-checked the next time you play "
                       "each game; you'll be told if it stopped working.")
        if now and now != before:  # only once the message is decided, so a failure cannot swallow it
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"steamos": now}, f)
        return {"message": message}

    async def download_dll(self) -> dict:
        if self.download["state"] == "running":
            return await self.get_state()
        self.download.update(state="running", done=0, error="")
        self._cancel = False

        def progress(done, total):
            self.download.update(done=done, total=total)

        try:
            await asyncio.to_thread(fsr4_dll.fetch, _ffx_path(), progress=progress, cancelled=lambda: self._cancel)
            self.dll_ok = True
            self.download["state"] = "done"
        except fsr4_dll.FetchError as e:
            decky.logger.error(f"DLL download failed: {e}")
            self.download.update(state="error", error=str(e))
        return await self.get_state()

    async def cancel_download(self) -> dict:
        self._cancel = True
        return await self.get_state()

    async def enable_game(self, appid: int, launch_options: str) -> dict:
        async with self.lock:
            game = next((g for g in self.games if g["appid"] == appid), None)
            if not game:
                return {"ok": False, "error": "Game not found; rescan the library."}
            if not (self.dll_ok and os.path.isfile(SHIM_PATH)):
                return {"ok": False, "error": "Download the AMD FSR4 DLL first."}
            if not (self.gpu and self.gpu["model"]):
                return {"ok": False, "error": gpu_unsupported(self.gpu)}
            try:
                options = await asyncio.to_thread(fsr4_install.enable, self.manifest, game, SHIM_PATH, _ffx_path(),
                                                  launch_options, self.gpu)
            except fsr4_install.InstallError as e:
                return {"ok": False, "error": str(e)}
            decky.logger.info(f"enabled FSR4 for {appid} in {game['target_dir']}")
            return {"ok": True, "launch_options": options}

    async def disable_game(self, appid: int, launch_options: str) -> dict:
        async with self.lock:
            result = await asyncio.to_thread(fsr4_install.disable, self.manifest, appid, launch_options)
            decky.logger.info(f"disabled FSR4 for {appid}, kept={result['kept']}")
            return {"ok": True, **result}

    async def session_started(self, appid: int) -> dict:
        if appid in self.manifest.entries:
            self.sessions[appid] = time.time()
        return {"managed": appid in self.manifest.entries}

    async def session_ended(self, appid: int, launch_options: str = "") -> dict:
        """Called by the frontend when a game exits; tells it whether to warn the user."""
        if appid not in self.manifest.entries:
            return {"managed": False}
        status = fsr4_install.read_status(self.manifest, appid)
        verdict, reason = fsr4_install.session_verdict(status, self.sessions.pop(appid, None), launch_options)
        if verdict == "ok":
            self.manifest.entries[appid]["verified"] = fsr4_env.fingerprint(status)
            self.manifest.save()
        if verdict == "failed":
            decky.logger.warning(f"FSR4 not active for {appid}: {reason} status={status}")
        return {"managed": True, "verdict": verdict, "reason": reason}

    async def _unload(self):
        self._cancel = True

    async def _uninstall(self):
        # Decky 3.3 runs this on every plugin *update* too (an update is uninstall + install), so tearing games down
        # here would switch FSR4 off everywhere on each update. Games stay as they are and the manifest survives in
        # the settings dir; "Turn off FSR4 and restore all games" in the panel is the full cleanup before a real uninstall.
        decky.logger.info(f"uninstall/update: leaving {len(self.manifest.entries)} game(s) configured")
