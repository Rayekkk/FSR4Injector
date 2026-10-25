# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Finding installed Steam games that can take the FSR4 upgrade.

A game qualifies when it ships AMD's FidelityFX API loader as a separate DLL (FSR 3.1+ / FSR4 through the FFX API):
that is the only path the driver-side upgrade hooks into. The directory holding that DLL is where our two DLLs go.
"""

import os
import re

FFX_DLLS = ("amd_fidelityfx_dx12.dll", "amd_fidelityfx_upscaler_dx12.dll", "amd_fidelityfx_loader_dx12.dll")
# Lower-case name fragments of anti-cheat files and folders: EAC, BattlEye, Vanguard, XIGNCODE, nProtect GameGuard,
# PunkBuster, EQU8. Online games without any of these are caught by the panel through Steam's store categories.
ANTICHEAT = ("easyanticheat", "battleye", "beservice", "start_protected_game.exe", "eac_launcher",
             "vanguard", "xigncode", "gameguard", "npgamemon", "punkbuster", "pbsvc", "equ8")
MAX_DEPTH = 5

_KV = re.compile(r'"([^"]+)"\s+"([^"]*)"')


def _values(text, key):
    return [v for k, v in _KV.findall(text) if k.lower() == key]


def libraries(steam_root):
    """Steam library roots, the main one first."""
    roots = [steam_root]
    try:
        with open(os.path.join(steam_root, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return roots
    for path in _values(text, "path"):
        path = path.replace("\\\\", "\\")
        if os.path.realpath(path) not in map(os.path.realpath, roots):
            roots.append(path)
    return roots


def _find_ffx(install_dir):
    """(directory with the FFX DLL, its name, anti-cheat seen) for one game."""
    found, anticheat = None, False
    base_depth = install_dir.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(install_dir):
        names = [n.lower() for n in dirs + files]
        if any(marker in n for n in names for marker in ANTICHEAT):
            anticheat = True
        if not found:
            hit = next((f for f in files if f.lower() in FFX_DLLS), None)
            if hit:
                found = (root, hit)
        if root.count(os.sep) - base_depth >= MAX_DEPTH:
            dirs[:] = []
    return (found[0], found[1], anticheat) if found else (None, None, anticheat)


def scan(steam_root):
    """Installed games with an FFX API DLL, sorted by name."""
    games = []
    for lib in libraries(steam_root):
        apps = os.path.join(lib, "steamapps")
        try:
            manifests = [n for n in os.listdir(apps) if n.startswith("appmanifest_") and n.endswith(".acf")]
        except OSError:
            continue
        for name in manifests:
            try:
                with open(os.path.join(apps, name), encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            appid, title, installdir = (_values(text, k) for k in ("appid", "name", "installdir"))
            if not (appid and installdir) or not appid[0].isdigit():
                continue
            # installdir is a folder name in steamapps/common; anything path-like could lead out of the library
            # (a symlinked game folder is fine: it is still that name)
            if installdir[0] in ("", ".", "..") or "/" in installdir[0] or "\\" in installdir[0]:
                continue
            install_dir = os.path.join(apps, "common", installdir[0])
            if not os.path.isdir(install_dir):
                continue
            target, ffx, anticheat = _find_ffx(install_dir)
            if target:
                games.append({"appid": int(appid[0]), "name": title[0] if title else installdir[0],
                              "install_dir": install_dir, "target_dir": target, "ffx_dll": ffx,
                              "anticheat": anticheat})
    return sorted(games, key=lambda g: g["name"].lower())
