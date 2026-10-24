# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""What FSR4 was last confirmed working with, so an update to SteamOS or Proton is noticed before the user wonders.

A fingerprint is taken from the status of a session where FSR4 ran: the SteamOS build, the Proton the game was
launched with (the shim records Steam's STEAM_COMPAT_TOOL_PATHS) and its version file, and the shim version.
"""

import os

OS_RELEASE = "/etc/os-release"


def steamos_build(path=OS_RELEASE):
    """'3.9.5 (20261023.100)', or '' when it cannot be read."""
    values = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                values[key] = value.strip('"')
    except OSError:
        return ""
    version, build = values.get("VERSION_ID", ""), values.get("BUILD_ID", "")
    return f"{version} ({build})" if version and build else version or build


def proton_version(tool_dir):
    """Proton's own version string ('proton-11.0-2e', 'experimental-11.0-20261014'), or '' when unknown."""
    if not tool_dir:
        return ""
    try:
        with open(os.path.join(tool_dir, "version"), encoding="utf-8", errors="replace") as f:
            words = f.read().split()
    except OSError:
        return ""
    return words[-1] if words else ""


def fingerprint(status, os_release=OS_RELEASE):
    tool = (status or {}).get("compat_tool", "")
    return {"steamos": steamos_build(os_release), "proton_dir": tool, "proton": proton_version(tool),
            "shim": (status or {}).get("shim", "")}


def changes(verified, os_release=OS_RELEASE):
    """Human-readable list of what differs now from a verified fingerprint."""
    if not verified:
        return []
    now = {"steamos": steamos_build(os_release), "proton": proton_version(verified.get("proton_dir", ""))}
    out = []
    for key, label in (("steamos", "SteamOS"), ("proton", "Proton")):
        before, after = verified.get(key, ""), now[key]
        if before and after and before != after:
            out.append(f"{label} {before} → {after}")
    return out
