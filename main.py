# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""FSR4Injector - official AMD FSR 4.1 (Lite model) for RDNA 3.5 APUs under Proton.

Two files go next to a game's FidelityFX DLL: AMD's own amdxcffx64.dll (fetched from AMD, see fsr4_dll) and our
amdxc64.dll shim (shim/, LGPL), which tells the AMD DLL the GPU family Wine cannot provide. Launch options are
applied by the frontend through SteamClient; this backend computes them so they can be undone exactly, and the
frontend reports back what Steam kept. Every RPC answers {ok, error?, state?} (DeckyKit D2, dk_rpc).
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

import dk_fs  # noqa: E402
import dk_rpc  # noqa: E402
import dk_update  # noqa: E402
import fsr4_dll  # noqa: E402
import fsr4_env  # noqa: E402
import fsr4_games  # noqa: E402
import fsr4_gpu  # noqa: E402
import fsr4_install  # noqa: E402

REPOSITORY = "Rayekkk/FSR4Injector"
SHIM_PATH = os.path.join(PLUGIN_DIR, "bin", fsr4_install.SHIM)
try:
    with open(os.path.join(PLUGIN_DIR, "plugin.json"), encoding="utf-8") as _f:
        VERSION = json.load(_f)["version"]
except (OSError, ValueError, KeyError):
    VERSION = "0.0.0"
# auto_launch_options: turning a game on also adds the launch option; watermark: AMD's FSR 4 watermark with it.
DEFAULT_SETTINGS = {"auto_launch_options": True, "watermark": False}
# Decky imports the frontend while _main is still running (it hashes the 85 MB DLL); calls wait for it.
_ready = asyncio.Event()
rpc = dk_rpc.boundary(decky.logger, _ready)


def _data_dir():
    return getattr(decky, "DECKY_PLUGIN_RUNTIME_DIR", decky.DECKY_PLUGIN_SETTINGS_DIR)


def _ffx_path():
    return os.path.join(_data_dir(), fsr4_install.FFX)


def _home():
    return getattr(decky, "DECKY_USER_HOME", os.path.expanduser("~"))


def gpu_unsupported(gpu):
    if not gpu:
        return "No AMD GPU was found, or its details could not be read."
    return (f"AMD's FSR 4 has no model for this GPU (PCI 1002:{gpu['device']:04x}, family {gpu['family']}, "
            f"revision {gpu['rev']}), so games would stay on FSR 3.")


def _load_settings(path):
    """The two switches; a damaged or unreadable file gives the defaults (it is replaced on the next change)."""
    try:
        saved = dk_fs.read_json(path, {}, validate=dk_fs.require_object)
    except OSError as e:
        decky.logger.warning(f"settings could not be read ({e.strerror or type(e).__name__}); using defaults")
        saved = {}
    return {k: saved[k] if isinstance(saved.get(k), bool) else v for k, v in DEFAULT_SETTINGS.items()}


def _steam_root():
    return os.path.join(_home(), ".local", "share", "Steam")


class Plugin:
    async def _main(self):
        try:
            # Everything the RPCs read exists before anything that can fail.
            self.manifest = fsr4_install.Manifest(os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "manifest.json"))
            self.settings_path = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
            self.settings = dict(DEFAULT_SETTINGS)
            self.games = []
            self.download = {"state": "idle", "done": 0, "total": fsr4_dll.RECIPE["packed_size"], "error": ""}
            self.dll_ok, self.gpu = False, None
            self.lock = asyncio.Lock()
            self._cancel = False
            self.sessions = {}  # appid -> session start (epoch s)
            self.scanned = False
            self._scan_task = None
            self.updates = dk_update.Updates(
                repo=REPOSITORY, folder="FSR4Injector", plugin_name="FSR4 Injector", package_name="fsr4injector",
                current=VERSION, home=_home(), required=(*dk_update.REQUIRED, "bin/amdxc64.dll"),
                max_expanded=64 << 20, max_members=512, logger=decky.logger)
            if self.manifest.problem:
                decky.logger.error(f"manifest: {self.manifest.problem} {self.manifest.recovered}")
            elif self.manifest.recovered:
                decky.logger.warning(f"manifest: {self.manifest.recovered}")
            os.makedirs(_data_dir(), exist_ok=True)
            self.settings = await asyncio.to_thread(_load_settings, self.settings_path)
            self.dll_ok = await asyncio.to_thread(fsr4_dll.is_valid, _ffx_path())
            self.gpu = await asyncio.to_thread(fsr4_gpu.detect)
            decky.logger.info(f"GPU: {self.gpu}")
            refreshed = await asyncio.to_thread(fsr4_install.refresh_shim, self.manifest, SHIM_PATH)
            if refreshed:
                decky.logger.info(f"updated amdxc64.dll in {refreshed} configured game(s)")
            # First panel open should not wait for a library walk.
            self._scan_task = asyncio.create_task(self.scan_games())
        finally:
            _ready.set()

    def _game_view(self, g):
        appid = g["appid"]
        entry = self.manifest.entries.get(appid)
        status = fsr4_install.read_status(self.manifest, appid)
        verdict, reason = fsr4_install.verdict(status)
        if entry and verdict == "ok":
            changed = fsr4_env.changes(entry.get("verified"))
            if changed:
                verdict, reason = "changed", f"Updated since FSR4 was last confirmed: {', '.join(changed)}. Play once to re-check."
        return {**g, "enabled": entry is not None, "verdict": verdict, "reason": reason,
                "managed_options": bool(entry) and entry.get("launch_applied") is not None}

    def _state_now(self):
        entries = dict(self.manifest.entries)  # enable/disable change it from worker threads
        known = {g["appid"] for g in self.games}
        enabled_missing = [{"appid": a, "name": f"App {a}", "target_dir": e["target_dir"], "anticheat": False}
                           for a, e in entries.items() if a not in known]
        return {
            "version": VERSION,
            "dll_ready": self.dll_ok,
            "shim_ready": os.path.isfile(SHIM_PATH),
            "gpu": self.gpu,
            "recipe": {k: fsr4_dll.RECIPE[k] for k in ("driver", "fsr", "dll_size")},
            "eula_url": fsr4_dll.EULA_URL,
            "download": dict(self.download),
            "settings": dict(self.settings),
            "copy_options": {"plain": f"{fsr4_install.launch_prefix(False)} %command%",
                             "watermark": f"{fsr4_install.launch_prefix(True)} %command%"},
            "scanned": self.scanned,
            "error": self.manifest.problem,  # stays on screen: no game can be changed while it is set
            "games": [self._game_view(g) for g in self.games + enabled_missing],
        }

    async def _state(self):
        """The panel's state; reads each set-up game's status file, so it runs off the event loop."""
        return await asyncio.to_thread(self._state_now)

    @rpc
    async def get_state(self) -> dict:
        return dk_rpc.ok(await self._state())

    @rpc
    async def set_setting(self, key: str, value: bool) -> dict:
        if key not in DEFAULT_SETTINGS or not isinstance(value, bool):
            return dk_rpc.fail("Unknown setting.", await self._state())
        async with self.lock:  # two quick changes would both start from the same old settings
            new = {**self.settings, key: value}
            try:
                await asyncio.to_thread(dk_fs.write_json, self.settings_path, new)
            except OSError as e:  # the switch stays as it was, in memory too
                decky.logger.error(f"settings not saved: {e}")
                return dk_rpc.fail(f"The setting could not be saved ({e.strerror or type(e).__name__}).",
                                   await self._state())
            self.settings = new
        decky.logger.info(f"setting {key} = {value}")
        return dk_rpc.ok(await self._state())

    @rpc
    async def apply_watermark(self, appid: int, launch_options: str) -> dict:
        """The watermark setting for one game whose launch options the plugin manages."""
        async with self.lock:
            new = await asyncio.to_thread(fsr4_install.set_watermark, self.manifest, appid, launch_options,
                                          self.settings["watermark"])
        if new is None:
            return dk_rpc.fail("FSR4 Injector does not manage this game's launch options.",
                               launch_options=launch_options)
        decky.logger.info(f"watermark {'on' if self.settings['watermark'] else 'off'} for {appid}")
        return dk_rpc.ok(launch_options=new)

    @rpc
    async def check_for_updates(self) -> dict:
        return await asyncio.to_thread(self.updates.check, True)

    @rpc
    async def perform_update(self, expected_version: str) -> dict:
        return await asyncio.to_thread(self.updates.download, expected_version)

    @rpc
    async def scan_games(self) -> dict:
        self.games = await asyncio.to_thread(fsr4_games.scan, _steam_root())
        self.scanned = True
        return dk_rpc.ok(await self._state())

    @rpc
    async def startup_notice(self) -> dict:
        """One-time message after a SteamOS update, when games are set up; '' otherwise."""
        path = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "env.json")
        now = await asyncio.to_thread(fsr4_env.steamos_build)
        try:
            saved = await asyncio.to_thread(dk_fs.read_json, path, {}, validate=dk_fs.require_object)
        except OSError:
            saved = {}
        before = saved.get("steamos") if isinstance(saved.get("steamos"), str) else ""
        message = ""
        if before and now and before != now and self.manifest.entries:
            message = (f"SteamOS was updated ({before} → {now}). FSR4 is re-checked the next time you play "
                       "each game; you'll be told if it stopped working.")
        if now and now != before:
            try:
                await asyncio.to_thread(dk_fs.write_json, path, {"steamos": now})
            except OSError as e:  # the message is still shown; it may come once more next time
                decky.logger.warning(f"env.json not saved: {e}")
        return dk_rpc.ok(message=message)

    @rpc
    async def download_dll(self) -> dict:
        if self.download["state"] == "running":
            return dk_rpc.fail("The download is already running.", await self._state())
        self.download.update(state="running", done=0, total=fsr4_dll.RECIPE["packed_size"], error="")
        self._cancel = False
        decky.logger.info("AMD FSR4 DLL download started")

        def progress(done, total):
            self.download.update(done=done, total=total)

        try:
            await asyncio.to_thread(fsr4_dll.fetch, _ffx_path(), progress=progress, cancelled=lambda: self._cancel)
            self.dll_ok = True
            self.download["state"] = "done"
            decky.logger.info("AMD FSR4 DLL downloaded and verified")
        except fsr4_dll.FetchError as e:
            decky.logger.error(f"DLL download failed: {e}")
            self.download.update(state="error", error=str(e))
        finally:
            if self.download["state"] == "running":  # anything unexpected: logged by the RPC boundary
                self.download.update(state="error", error="Unexpected error. Details are in the Decky log.")
        if self.download["state"] == "error":
            return dk_rpc.fail(self.download["error"], await self._state())
        return dk_rpc.ok(await self._state())

    @rpc
    async def download_progress(self) -> dict:
        """What the panel polls during the download: no file is read."""
        return dk_rpc.ok(download=dict(self.download), dll_ready=self.dll_ok)

    @rpc
    async def verify_library(self) -> dict:
        """Re-check AMD's library on disk (the Repair button); a damaged or missing one has to be downloaded again."""
        self.dll_ok = await asyncio.to_thread(fsr4_dll.is_valid, _ffx_path())
        return dk_rpc.ok(await self._state())

    @rpc
    async def cancel_download(self) -> dict:
        self._cancel = True
        decky.logger.info("download cancel requested")
        return dk_rpc.ok(await self._state())

    @rpc
    async def enable_game(self, appid: int, launch_options: str) -> dict:
        async with self.lock:
            if self.manifest.problem:
                return dk_rpc.fail(self.manifest.problem, await self._state())
            game = next((g for g in self.games if g["appid"] == appid), None)
            if not game:
                return dk_rpc.fail("Game not found; rescan the library.")
            if not (self.dll_ok and os.path.isfile(SHIM_PATH)):
                return dk_rpc.fail("Download the AMD FSR4 DLL first.")
            if not (self.gpu and self.gpu["model"]):
                return dk_rpc.fail(gpu_unsupported(self.gpu))
            try:
                options = await asyncio.to_thread(fsr4_install.enable, self.manifest, game, SHIM_PATH, _ffx_path(),
                                                  launch_options, self.gpu, self.settings["auto_launch_options"],
                                                  self.settings["watermark"])
            except fsr4_install.InstallError as e:
                decky.logger.warning(f"enable {appid}: {e}")
                return dk_rpc.fail(str(e), await self._state())
            decky.logger.info(f"enabled FSR4 for {appid} in {game['target_dir']}")
            return dk_rpc.ok(await self._state(), launch_options=options)

    @rpc
    async def disable_game(self, appid: int, launch_options: str) -> dict:
        async with self.lock:
            if self.manifest.problem:
                return dk_rpc.fail(self.manifest.problem, await self._state())
            result = await asyncio.to_thread(fsr4_install.disable, self.manifest, appid, launch_options)
            decky.logger.info(f"disabled FSR4 for {appid}, kept={result['kept']}")
            return dk_rpc.ok(await self._state(), **result)

    @rpc
    async def launch_options_saved(self, appid: int, saved: str) -> dict:
        """The panel wrote the launch options to Steam and read them back. The manifest keeps what Steam really
        has, so turning FSR4 off restores the user's own options exactly; a write Steam did not keep is reported."""
        async with self.lock:
            entry = self.manifest.entries.get(appid)
            saved = (saved or "").strip()
            if not entry or entry.get("launch_applied") is None or saved == entry["launch_applied"]:
                return dk_rpc.ok()
            decky.logger.warning(f"launch options of {appid}: Steam kept {saved!r}, not {entry['launch_applied']!r}")
            entry["launch_applied"] = saved
            await asyncio.to_thread(self.manifest.save)
        return dk_rpc.fail("Steam did not keep the new launch options, so FSR4 may not load. Turn the game off and "
                           "on again, or add the launch option by hand.", await self._state())

    @rpc
    async def session_started(self, appid: int) -> dict:
        if appid in self.manifest.entries:
            self.sessions[appid] = time.time()
        return dk_rpc.ok(managed=appid in self.manifest.entries)

    @rpc
    async def session_ended(self, appid: int, launch_options: str = "") -> dict:
        """Called by the frontend when a game exits; tells it whether to warn the user."""
        entry = self.manifest.entries.get(appid)
        if not entry:
            return dk_rpc.ok(managed=False)
        status = await asyncio.to_thread(fsr4_install.read_status, self.manifest, appid)
        verdict, reason = fsr4_install.session_verdict(status, self.sessions.pop(appid, None), launch_options,
                                                       entry.get("launch_applied") is not None)
        async with self.lock:
            # one session without our DLL is usually a launcher closed early; twice in a row is worth a warning
            entry["missed"] = entry.get("missed", 0) + 1 if verdict == "missed" else 0
            if verdict == "missed" and entry["missed"] >= 2:
                verdict, reason = "failed", reason + " It happened twice in a row."
            if verdict == "ok":
                entry["verified"] = await asyncio.to_thread(fsr4_env.fingerprint, status)
            await asyncio.to_thread(self.manifest.save)
        if verdict == "failed":
            decky.logger.warning(f"FSR4 not active for {appid}: {reason} status={status}")
        return dk_rpc.ok(managed=True, verdict=verdict, reason=reason)

    async def _unload(self):
        # Synchronous in effect: a running download or update is cancelled, nothing here waits for the network.
        if not hasattr(self, "updates"):
            return  # _main never ran
        self._cancel = True
        self.updates.close()
        if self._scan_task:
            self._scan_task.cancel()

    async def _uninstall(self):
        # Decky 3.3 runs this on every plugin *update* too (an update is uninstall + install), so tearing games down
        # here would switch FSR4 off everywhere on each update. Games stay as they are and the manifest survives in
        # the settings dir; "Turn off FSR4 and restore all games" in the panel is the full cleanup before a real uninstall.
        entries = getattr(getattr(self, "manifest", None), "entries", {})
        decky.logger.info(f"uninstall/update: leaving {len(entries)} game(s) configured")
