# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Game discovery, install/rollback safety and launch option handling."""

import asyncio
import json
import os
import tempfile
import time
import unittest
from unittest import mock

import _harness  # noqa: F401
import fsr4_games
import fsr4_install as I


def _write(path, data=b""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _library(root, appid, name, installdir, files):
    _write(os.path.join(root, "steamapps", f"appmanifest_{appid}.acf"),
           f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n\t"installdir"\t\t"{installdir}"\n}}\n'
           .encode())
    for rel in files:
        _write(os.path.join(root, "steamapps", "common", installdir, rel), b"x")


class Discovery(unittest.TestCase):
    def test_finds_ffx_games_in_all_libraries(self):
        steam, sd = tempfile.mkdtemp(), tempfile.mkdtemp()
        _write(os.path.join(steam, "steamapps", "libraryfolders.vdf"),
               f'"libraryfolders"\n{{\n"0"\n{{\n"path" "{steam}"\n}}\n"1"\n{{\n"path" "{sd}"\n}}\n}}\n'
               .replace("\\", "\\\\").encode())
        _library(steam, 1817070, "Spider-Man", "SM", ["Spider-Man.exe", "amd_fidelityfx_dx12.dll"])
        _library(sd, 1903340, "Expedition 33", "E33",
                 ["Sandfall/Binaries/Win64/SandFall.exe", "Sandfall/Binaries/Win64/amd_fidelityfx_upscaler_dx12.dll"])
        _library(sd, 4000, "No FSR", "NoFSR", ["game.exe"])
        _library(steam, 5000, "Online", "Online", ["amd_fidelityfx_dx12.dll", "EasyAntiCheat/EasyAntiCheat_x64.dll"])
        _library(steam, 5001, "Korean MMO", "KMMO", ["amd_fidelityfx_dx12.dll", "XIGNCODE/x3.xem"])
        _library(steam, 5002, "Old FPS", "OldFPS", ["amd_fidelityfx_dx12.dll", "pb/pbsvc.exe"])
        # a manifest whose installdir climbs out of steamapps/common is ignored
        _library(steam, 6000, "Escape", "../../outside", ["amd_fidelityfx_dx12.dll"])

        games = {g["appid"]: g for g in fsr4_games.scan(steam)}
        self.assertEqual(set(games), {1817070, 1903340, 5000, 5001, 5002})
        self.assertTrue(games[1903340]["target_dir"].endswith(os.path.join("Binaries", "Win64")))
        self.assertTrue(all(games[a]["anticheat"] for a in (5000, 5001, 5002)))
        self.assertFalse(games[1817070]["anticheat"])


class LaunchOptions(unittest.TestCase):
    def test_round_trip(self):
        for original in ("", "%command% -dx12", "gamemoderun %command%", "-skipintro"):
            applied = I.with_token(original)
            self.assertTrue(applied.startswith(I.TOKEN + " "))
            self.assertIn("%command%", applied)
            self.assertEqual(I.without_token(applied, original, applied), original)

    def test_user_edit_after_enable_keeps_their_change(self):
        applied = I.with_token("%command%")
        edited = applied + " -novid"
        self.assertEqual(I.without_token(edited, "%command%", applied), "%command% -novid")

    def test_refuses_foreign_dll_overrides(self):
        with self.assertRaises(I.InstallError):
            I.with_token("WINEDLLOVERRIDES=dxgi=n,b %command%")

    def test_idempotent(self):
        once = I.with_token("%command%")
        self.assertEqual(I.with_token(once), once)


class InstallRollback(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.shim, self.ffx = os.path.join(d, "shim.dll"), os.path.join(d, "ffx.dll")
        _write(self.shim, b"shim")
        _write(self.ffx, b"amd")
        self.target = os.path.join(d, "game")
        _write(os.path.join(self.target, "game.exe"), b"exe")
        self.game = {"appid": 42, "target_dir": self.target}
        self.mpath = os.path.join(d, "manifest.json")
        self.m = I.Manifest(self.mpath)

    def files(self):
        return sorted(os.listdir(self.target))

    def test_enable_then_disable_restores_folder_and_options(self):
        gpu = {"device": 0x150E, "family": 150, "rev": 20}
        opts = I.enable(self.m, self.game, self.shim, self.ffx, "-novid", gpu)
        self.assertEqual(self.files(), ["amdxc64.dll", "amdxcffx64.dll", "fsr4injector.gpu", "game.exe"])
        with open(os.path.join(self.target, I.GPU)) as f:
            self.assertEqual(f.read(), "5390 150 20\n")  # what the shim parses
        self.assertEqual(opts, f"{I.TOKEN} %command% -novid")
        entry = I.Manifest(self.mpath).entries[42]  # persisted
        self.assertEqual(entry["mode"], I.MODE_NATIVE)
        _write(os.path.join(self.target, I.STATUS), b"{}")  # shim runtime output
        res = I.disable(I.Manifest(self.mpath), 42, opts)
        self.assertEqual(res, {"launch_options": "-novid", "kept": []})
        self.assertEqual(self.files(), ["game.exe"])

    def test_leftover_token_is_not_recorded_as_original(self):
        # manifest lost (or older plugin left the token behind): disabling must still return the user's own options
        opts = I.enable(self.m, self.game, self.shim, self.ffx, f"{I.TOKEN} ~/.dlo/run %command%")
        self.assertEqual(I.disable(self.m, 42, opts)["launch_options"], "~/.dlo/run %command%")

    def test_never_overwrites_foreign_file(self):
        _write(os.path.join(self.target, "amdxc64.dll"), b"someone else's")
        with self.assertRaisesRegex(I.InstallError, "not ours"):
            I.enable(self.m, self.game, self.shim, self.ffx, "")
        with open(os.path.join(self.target, "amdxc64.dll"), "rb") as f:
            self.assertEqual(f.read(), b"someone else's")
        self.assertNotIn(42, self.m.entries)

    def test_disable_keeps_file_changed_since(self):
        I.enable(self.m, self.game, self.shim, self.ffx, "")
        _write(os.path.join(self.target, "amdxcffx64.dll"), b"replaced by user")
        res = I.disable(self.m, 42, "")
        self.assertEqual(res["kept"], ["amdxcffx64.dll"])
        self.assertEqual(self.files(), ["amdxcffx64.dll", "game.exe"])

    def test_reenable_updates_our_files(self):
        I.enable(self.m, self.game, self.shim, self.ffx, "")
        _write(self.shim, b"shim v2")
        I.enable(self.m, self.game, self.shim, self.ffx, I.with_token(""))
        with open(os.path.join(self.target, "amdxc64.dll"), "rb") as f:
            self.assertEqual(f.read(), b"shim v2")
        self.assertEqual(I.disable(self.m, 42, I.with_token(""))["launch_options"], "")

    def test_refresh_shim_after_plugin_update(self):
        I.enable(self.m, self.game, self.shim, self.ffx, "")
        _write(self.shim, b"shim v2")
        self.assertEqual(I.refresh_shim(self.m, self.shim), 1)
        with open(os.path.join(self.target, I.SHIM), "rb") as f:
            self.assertEqual(f.read(), b"shim v2")
        self.assertEqual(I.refresh_shim(self.m, self.shim), 0)  # already current
        # a file the user changed is left alone
        _write(os.path.join(self.target, I.SHIM), b"user's own")
        _write(self.shim, b"shim v3")
        self.assertEqual(I.refresh_shim(self.m, self.shim), 0)
        self.assertEqual(I.refresh_shim(self.m, os.path.join(self.target, "missing.dll")), 0)

    def test_partial_install_is_recorded_for_rollback(self):
        real_copy = I._copy

        def flaky(src, dst):
            if dst.endswith(I.FFX):
                raise OSError("disk full")
            real_copy(src, dst)
        with mock.patch.object(I, "_copy", flaky), self.assertRaisesRegex(I.InstallError, "disk full"):
            I.enable(self.m, self.game, self.shim, self.ffx, "")
        self.assertEqual(list(I.Manifest(self.mpath).entries[42]["files"]), ["amdxc64.dll"])
        # a copy that fails half way leaves no temp file behind
        with mock.patch.object(I.shutil, "copyfile", side_effect=lambda s, d: (open(d, "wb").write(b"half"),
                                                                                 (_ for _ in ()).throw(OSError("full")))):
            with self.assertRaises(OSError):
                I._copy(self.ffx, os.path.join(self.target, "x.dll"))
        self.assertNotIn("x.dll.fsr4i-tmp", os.listdir(self.target))
        I.disable(I.Manifest(self.mpath), 42, "")
        self.assertEqual(self.files(), ["game.exe"])


class LaunchSettings(unittest.TestCase):
    """The panel's launch option switches: automatic token (default) or hands-off, and the watermark."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.shim, self.ffx = os.path.join(d, "shim.dll"), os.path.join(d, "ffx.dll")
        _write(self.shim, b"shim")
        _write(self.ffx, b"amd")
        self.target = os.path.join(d, "game")
        os.makedirs(self.target)
        self.game = {"appid": 9, "target_dir": self.target}
        self.m = I.Manifest(os.path.join(d, "manifest.json"))

    def test_watermark_rides_along_and_is_undone(self):
        opts = I.enable(self.m, self.game, self.shim, self.ffx, "~/.dlo/run %command%", watermark=True)
        self.assertEqual(opts, f"{I.TOKEN} {I.WATERMARK} ~/.dlo/run %command%")
        self.assertEqual(I.with_token(opts, True), opts)  # idempotent
        self.assertEqual(I.disable(self.m, 9, opts + " -novid")["launch_options"], "~/.dlo/run %command% -novid")

    def test_users_own_watermark_survives(self):
        opts = I.enable(self.m, self.game, self.shim, self.ffx, f"{I.WATERMARK} %command%", watermark=True)
        self.assertEqual(I.set_watermark(self.m, 9, opts, False), opts)  # theirs, not ours to take out
        self.assertEqual(I.disable(self.m, 9, opts + " x")["launch_options"], f"{I.WATERMARK} %command% x")

    def test_switching_the_watermark_on_set_up_games(self):
        opts = I.enable(self.m, self.game, self.shim, self.ffx, "-novid")
        on = I.set_watermark(self.m, 9, opts, True)
        self.assertEqual(on, f"{I.TOKEN} {I.WATERMARK} %command% -novid")
        off = I.set_watermark(self.m, 9, on, False)
        self.assertEqual(off, f"{I.TOKEN} %command% -novid")
        self.assertEqual(I.disable(self.m, 9, off)["launch_options"], "-novid")

    def test_hands_off_mode_never_touches_launch_options(self):
        self.assertEqual(I.enable(self.m, self.game, self.shim, self.ffx, "-novid", launch=False), "-novid")
        self.assertIn(I.SHIM, os.listdir(self.target))
        self.assertIsNone(I.set_watermark(self.m, 9, "-novid", True))
        mine = f"{I.TOKEN} %command% -novid"  # the user added it by hand
        self.assertEqual(I.disable(self.m, 9, mine), {"launch_options": mine, "kept": []})
        self.assertEqual(os.listdir(self.target), [])

    def test_missing_token_in_hands_off_mode_says_to_add_it(self):
        start = 1792873295
        verdict, reason = I.session_verdict(None, start, "%command%", managed=False)
        self.assertEqual(verdict, "failed")
        self.assertIn("add WINEDLLOVERRIDES=amdxc64=n,b", reason)


class Verdict(unittest.TestCase):
    def test_states(self):
        ok = {"ffx_requested": True, "dll_loaded": True, "family": 150, "active": "INT8_LITE", "provider": "4.1.2 *"}
        self.assertEqual(I.verdict(ok)[0], "ok")
        self.assertIn("4.1.2", I.verdict(ok)[1])
        self.assertEqual(I.verdict(None)[0], "unknown")
        self.assertEqual(I.verdict({"ffx_requested": False})[0], "unused")
        self.assertEqual(I.verdict({**ok, "active": "FSR3"})[0], "failed")
        self.assertEqual(I.verdict({**ok, "dll_loaded": False, "active": None})[0], "failed")
        self.assertIn("not supported", I.verdict({**ok, "family": 0, "active": "FSR3", "gpu": "1002:15bf"})[1])
        self.assertIn("update", I.verdict({**ok, "active": "unknown"})[1])


class SessionVerdict(unittest.TestCase):
    ok = {"started": "2026-10-24T20:21:38Z", "ffx_requested": True, "dll_loaded": True, "family": 150,
          "active": "INT8_LITE"}
    start = 1792873295  # 2026-10-24T20:21:35Z

    def test_status_from_this_session_is_judged_normally(self):
        self.assertEqual(I.session_verdict(self.ok, self.start, I.with_token(""))[0], "ok")

    def test_stale_status_with_token_removed_names_the_cause(self):
        stale = {**self.ok, "started": "2026-10-24T19:00:00Z"}
        verdict, reason = I.session_verdict(stale, self.start, "~/.dlo/run %command%")
        self.assertEqual(verdict, "failed")
        self.assertIn("launch options no longer contain", reason)

    def test_missing_status_is_a_failure(self):
        self.assertEqual(I.session_verdict(None, self.start, I.with_token(""))[0], "failed")

    def test_without_session_start_falls_back_to_plain_verdict(self):
        self.assertEqual(I.session_verdict(self.ok, None, ""), I.verdict(self.ok))


class Plugin(unittest.TestCase):
    """End to end through the RPC layer with a fake Steam library."""

    def test_enable_disable_via_rpc(self):
        import decky
        import main
        steam = os.path.join(decky.DECKY_USER_HOME, ".local", "share", "Steam")
        _library(steam, 1817070, "Spider-Man", "SM", ["Spider-Man.exe", "amd_fidelityfx_dx12.dll"])
        # never touch the repo's real bin/amdxc64.dll
        self.enterContext(mock.patch.object(main, "SHIM_PATH", os.path.join(tempfile.mkdtemp(), "amdxc64.dll")))
        gpu = {"device": 0x150E, "family": 150, "rev": 20, "model": "INT8_LITE", "model_name": "INT8 Lite",
               "verified": True}
        self.enterContext(mock.patch.object(main.fsr4_gpu, "detect", return_value=gpu))
        p = main.Plugin()
        run = asyncio.run

        async def flow():
            await p._main()
            state = await p.scan_games()
            self.assertEqual([g["appid"] for g in state["games"]], [1817070])
            blocked = await p.enable_game(1817070, "")
            self.assertFalse(blocked["ok"])  # no DLL yet
            _write(main._ffx_path(), b"amd")
            _write(main.SHIM_PATH, b"shim")
            p.dll_ok = True
            p.gpu = {**gpu, "family": 148, "model": None}  # e.g. a 780M: AMD has no model
            self.assertIn("no model for this GPU", (await p.enable_game(1817070, ""))["error"])
            p.gpu = gpu
            res = await p.enable_game(1817070, "")
            self.assertTrue(res["ok"], res)
            target = os.path.join(steam, "steamapps", "common", "SM")
            await p.session_started(1817070)
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _write(os.path.join(target, I.STATUS), json.dumps(
                {"started": now, "ffx_requested": True, "dll_loaded": True, "family": 150, "active": "FSR3"}).encode())
            ended = await p.session_ended(1817070, res["launch_options"])
            self.assertEqual(ended["verdict"], "failed")
            state = await p.get_state()
            self.assertTrue(state["games"][0]["enabled"])
            # SteamOS update notice: silent on first run, once after a change, then silent again
            env_path = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "env.json")
            with mock.patch.object(main.fsr4_env, "steamos_build", return_value="3.9.5 (1)"):
                self.assertEqual((await p.startup_notice())["message"], "")
            with mock.patch.object(main.fsr4_env, "steamos_build", return_value="3.9.6 (2)"):
                self.assertIn("3.9.5 (1) → 3.9.6 (2)", (await p.startup_notice())["message"])
                self.assertEqual((await p.startup_notice())["message"], "")
            os.remove(env_path)

            # a plugin update runs _uninstall and then a fresh backend: the game must stay set up
            await p._uninstall()
            self.assertIn(I.SHIM, os.listdir(target))
            updated = main.Plugin()
            await updated._main()
            await updated.scan_games()
            self.assertTrue((await updated.get_state())["games"][0]["enabled"])
            res = await updated.disable_game(1817070, res["launch_options"])
            self.assertEqual(res["launch_options"], "")
            self.assertEqual(sorted(os.listdir(target)), ["Spider-Man.exe", "amd_fidelityfx_dx12.dll"])

            # settings: validated, persisted, and used by the next enable
            state = await updated.get_state()
            self.assertEqual(state["settings"], {"auto_launch_options": True, "watermark": False})
            self.assertEqual(state["copy_options"]["watermark"], f"{I.TOKEN} {I.WATERMARK} %command%")
            updated.dll_ok = True  # the fake DLL above has no AMD checksum
            await updated.set_setting("watermark", "yes")  # not a bool: ignored
            await updated.set_setting("nonsense", True)
            self.assertEqual((await updated.set_setting("watermark", True))["settings"]["watermark"], True)
            res = await updated.enable_game(1817070, "")
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["launch_options"],
                             f"{I.TOKEN} {I.WATERMARK} %command%")
            self.assertEqual((await updated.apply_watermark(1817070, f"{I.TOKEN} {I.WATERMARK} %command%"))
                             ["launch_options"], f"{I.TOKEN} {I.WATERMARK} %command%")
            await updated.disable_game(1817070, f"{I.TOKEN} {I.WATERMARK} %command%")
            await updated.set_setting("auto_launch_options", False)
            again = main.Plugin()
            await again._main()
            await again.scan_games()
            again.dll_ok = True
            self.assertEqual(again.settings, {"auto_launch_options": False, "watermark": True})
            res = await again.enable_game(1817070, "-novid")
            self.assertEqual(res["launch_options"], "-novid")  # left to the user
            self.assertFalse((await again.get_state())["games"][0]["managed_options"])
            self.assertFalse((await again.apply_watermark(1817070, "-novid"))["ok"])
            await again.disable_game(1817070, "-novid")
            await again.set_setting("auto_launch_options", True)
            await again.set_setting("watermark", False)
        run(flow())


if __name__ == "__main__":
    unittest.main()
