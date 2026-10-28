# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Game discovery, install/rollback safety and launch option handling."""

import json
import os
import tempfile
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
        _library(steam, 1328670, "Mass Effect LE", "MELE",
                 ["amd_fidelityfx_dx12.dll", "Game/ME3/BioGame/CookedPCConsole/SFXCharacterClass_Vanguard.pcc"])
        # a manifest whose installdir climbs out of steamapps/common is ignored
        _library(steam, 6000, "Escape", "../../outside", ["amd_fidelityfx_dx12.dll"])

        games = {g["appid"]: g for g in fsr4_games.scan(steam)}
        self.assertEqual(set(games), {1817070, 1903340, 5000, 5001, 5002, 1328670})
        self.assertTrue(games[1903340]["target_dir"].endswith(os.path.join("Binaries", "Win64")))
        self.assertTrue(all(games[a]["anticheat"] for a in (5000, 5001, 5002)))
        self.assertFalse(games[1817070]["anticheat"])
        # Mass Effect's Vanguard class files are not Riot Vanguard
        self.assertFalse(games[1328670]["anticheat"])


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

    def test_old_format_is_unchanged_without_other_overrides(self):
        # launch_applied of games set up by earlier versions must still match byte for byte
        for original, wm, want in (("~/.dlo/run %command%", False, f"{I.TOKEN} ~/.dlo/run %command%"),
                                   ("-novid", False, f"{I.TOKEN} %command% -novid"),
                                   ("", True, f"{I.TOKEN} {I.WATERMARK} %command%")):
            self.assertEqual(I.with_token(original, wm), want)

    def test_merges_into_another_tools_overrides_in_either_order(self):
        theirs = 'WINEDLLOVERRIDES="d3dcompiler_47=n;dxgi=n,b"'
        merged = 'WINEDLLOVERRIDES="d3dcompiler_47=n;dxgi=n,b;amdxc64=n,b"'
        # theirs first, then FSR4 on; FSR4 off restores theirs exactly
        applied = I.with_token(f"{theirs} %command%")
        self.assertEqual(applied, f"{merged} %command%")
        self.assertTrue(I.has_token(applied))
        self.assertEqual(I.without_token(applied, f"{theirs} %command%", applied), f"{theirs} %command%")
        # FSR4 first, the other tool merges its entries after ours; FSR4 off takes out only its entry
        later = 'WINEDLLOVERRIDES="amdxc64=n,b;d3dcompiler_47=n;dxgi=n,b" %command%'
        self.assertTrue(I.has_token(later))
        self.assertEqual(I.without_token(later, "", f"{I.TOKEN} %command%"), f"{theirs} %command%")
        # the other tool removed first: our entry stays alone, unquoted; then ours goes and the variable with it
        self.assertEqual(I.without_token(f"{I.TOKEN} %command% -novid", "-novid", "x"), "%command% -novid")

    def test_users_own_override_stays(self):
        original = "WINEDLLOVERRIDES=dinput8=n,b %command%"
        applied = I.with_token(original)
        self.assertEqual(applied, 'WINEDLLOVERRIDES="dinput8=n,b;amdxc64=n,b" %command%')
        self.assertEqual(I.without_token(applied + " -x", original, applied), "WINEDLLOVERRIDES=dinput8=n,b %command% -x")

    def test_dll_lists_sharing_one_mode(self):
        self.assertTrue(I.has_token("WINEDLLOVERRIDES=dxgi,amdxc64=n,b %command%"))
        self.assertFalse(I.has_token("WINEDLLOVERRIDES=dxgi,amdxc64=b %command%"))  # builtin: not ours
        # amdxc64 leaves the list instead of appearing twice in the variable
        self.assertEqual(I.with_token("WINEDLLOVERRIDES=dxgi,amdxc64=b %command%"),
                         'WINEDLLOVERRIDES="dxgi=b;amdxc64=n,b" %command%')
        self.assertEqual(I.without_token("WINEDLLOVERRIDES=dxgi,amdxc64=n,b %command%", "", "x"),
                         "WINEDLLOVERRIDES=dxgi=n,b %command%")

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

    def test_amd_library_is_one_hard_link_when_the_drive_allows(self):
        I.enable(self.m, self.game, self.shim, self.ffx, "")
        self.assertTrue(os.path.samefile(self.ffx, os.path.join(self.target, I.FFX)))
        self.assertFalse(os.path.samefile(self.shim, os.path.join(self.target, I.SHIM)))  # the shim stays a copy
        I.disable(self.m, 42, "")
        self.assertTrue(os.path.isfile(self.ffx))  # removing the game's link keeps the plugin's copy

    def test_amd_library_is_copied_where_links_are_refused(self):
        with mock.patch.object(I.os, "link", side_effect=OSError(18, "Invalid cross-device link")):
            I.enable(self.m, self.game, self.shim, self.ffx, "")
        dst = os.path.join(self.target, I.FFX)
        self.assertFalse(os.path.samefile(self.ffx, dst))
        with open(dst, "rb") as f:
            self.assertEqual(f.read(), b"amd")

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
        def flaky(src, dst):
            raise OSError(28, "disk full", dst)
        with mock.patch.object(I, "_link_or_copy", flaky), self.assertRaisesRegex(I.InstallError, "disk full"):
            I.enable(self.m, self.game, self.shim, self.ffx, "")
        self.assertEqual(list(I.Manifest(self.mpath).entries[42]["files"]), ["amdxc64.dll"])
        # a copy that fails half way leaves neither half a file nor a temp file behind
        before = self.files()
        with mock.patch("dk_fs._copy", side_effect=lambda data, f: (f.write(b"half"), f.flush(),
                                                                  (_ for _ in ()).throw(OSError("full")))):
            with self.assertRaises(OSError):
                I._copy(self.ffx, os.path.join(self.target, "x.dll"))
        self.assertEqual(self.files(), before)
        with mock.patch.object(I.os, "replace", side_effect=OSError("full")):  # a link that cannot be renamed
            with self.assertRaises(OSError):
                I._link_or_copy(self.ffx, os.path.join(self.target, "y.dll"))
        self.assertEqual(self.files(), before)
        I.disable(I.Manifest(self.mpath), 42, "")
        self.assertEqual(self.files(), ["game.exe"])

    def test_a_manifest_that_cannot_be_saved_at_the_end_is_an_install_error(self):
        with mock.patch.object(I.Manifest, "save", side_effect=[None, None, OSError(28, "No space left on device")]):
            with self.assertRaisesRegex(I.InstallError, "No space left"):
                I.enable(self.m, self.game, self.shim, self.ffx, "")

    @unittest.skipUnless(os.name == "posix", "symlinks")
    def test_a_game_folder_that_is_a_link_still_works(self):
        moved = os.path.join(os.path.dirname(self.target), "other-drive")
        os.rename(self.target, moved)
        os.symlink(moved, self.target)  # a game moved to another drive and linked back
        I.enable(self.m, self.game, self.shim, self.ffx, "")
        self.assertEqual(sorted(os.listdir(moved)), ["amdxc64.dll", "amdxcffx64.dll", "game.exe"])
        _write(self.shim, b"shim v2")
        self.assertEqual(I.refresh_shim(self.m, self.shim), 1)
        I.disable(self.m, 42, "")
        self.assertEqual(os.listdir(moved), ["game.exe"])

    @unittest.skipUnless(os.name == "posix", "symlinks")
    def test_a_symlink_in_the_game_folder_is_never_written_through(self):
        outside = os.path.join(os.path.dirname(self.target), "outside.dll")
        _write(outside, b"shim")  # the same content as ours, so it passes the 'not ours' check
        os.symlink(outside, os.path.join(self.target, I.SHIM))
        with self.assertRaises(I.InstallError):
            I.enable(self.m, self.game, self.shim, self.ffx, "")
        with open(outside, "rb") as f:
            self.assertEqual(f.read(), b"shim")


class ManifestSafety(unittest.TestCase):
    """The manifest is the only record of what is ours: never silently reset."""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "manifest.json")

    def test_a_damaged_manifest_comes_back_from_its_last_good_copy(self):
        m = I.Manifest(self.path)
        m.entries[42] = {"target_dir": "/g", "files": {I.SHIM: "a" * 64}, "launch_original": ""}
        m.save()
        _write(self.path, b'{"42": {"target_dir": ')  # a write cut short
        again = I.Manifest(self.path)
        self.assertEqual(list(again.entries), [42])
        self.assertTrue(again.recovered)
        self.assertEqual(again.problem, "")

    def test_without_a_good_copy_it_is_kept_and_nothing_is_saved_over_it(self):
        for damaged in (b"[1, 2]", b'{"42": {"files": {}}}', b"{not json"):
            _write(self.path, damaged)
            for name in os.listdir(os.path.dirname(self.path)):
                if name != "manifest.json":
                    os.remove(os.path.join(os.path.dirname(self.path), name))
            m = I.Manifest(self.path)
            self.assertIn("damaged", m.problem)
            with self.assertRaises(I.InstallError):
                m.save()
            with open(self.path, "rb") as f:
                self.assertEqual(f.read(), damaged)

    def test_the_old_format_still_loads(self):
        _write(self.path, json.dumps({"1817070": {
            "target_dir": "/g", "files": {I.SHIM: "a" * 64}, "launch_original": "", "launch_applied": None,
            "mode": "native", "enabled_at": "2026-10-25T10:00:00Z", "verified": {"steamos": "3.9"}, "missed": 1,
        }}, indent=1).encode())
        m = I.Manifest(self.path)
        self.assertEqual((m.problem, list(m.entries)), ("", [1817070]))


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

    def test_watermark_next_to_a_merged_variable(self):
        theirs = 'WINEDLLOVERRIDES="d3dcompiler_47=n;dxgi=n,b"'
        opts = I.enable(self.m, self.game, self.shim, self.ffx, f"{theirs} ~/.dlo/run %command%")
        on = I.set_watermark(self.m, 9, opts, True)
        self.assertEqual(on, f'WINEDLLOVERRIDES="d3dcompiler_47=n;dxgi=n,b;amdxc64=n,b" {I.WATERMARK} ~/.dlo/run %command%')
        off = I.set_watermark(self.m, 9, on, False)
        self.assertEqual(off, 'WINEDLLOVERRIDES="d3dcompiler_47=n;dxgi=n,b;amdxc64=n,b" ~/.dlo/run %command%')
        self.assertEqual(I.disable(self.m, 9, off)["launch_options"], f"{theirs} ~/.dlo/run %command%")

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

    def test_token_inside_a_merged_variable_counts(self):
        stale = {**self.ok, "started": "2026-10-24T19:00:00Z"}
        merged = 'WINEDLLOVERRIDES="d3dcompiler_47=n;amdxc64=n,b" %command%'
        self.assertEqual(I.session_verdict(stale, self.start, merged)[0], "missed")  # not "options changed"

    def test_stale_status_with_token_removed_names_the_cause(self):
        stale = {**self.ok, "started": "2026-10-24T19:00:00Z"}
        verdict, reason = I.session_verdict(stale, self.start, "~/.dlo/run %command%")
        self.assertEqual(verdict, "failed")
        self.assertIn("launch options no longer contain", reason)

    def test_missing_status_with_the_token_is_a_miss(self):
        # the caller warns only on the second miss in a row: a launcher closed early is not a failure
        self.assertEqual(I.session_verdict(None, self.start, I.with_token(""))[0], "missed")

    def test_without_session_start_falls_back_to_plain_verdict(self):
        self.assertEqual(I.session_verdict(self.ok, None, ""), I.verdict(self.ok))


if __name__ == "__main__":
    unittest.main()
