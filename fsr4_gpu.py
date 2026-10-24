# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""The GPU's real family and revision, read from the amdgpu kernel driver, and the FSR4 model AMD's DLL will pick.

amdxcffx64.dll chooses its model from the family/revision AMD's Windows kernel driver reports. Under Wine the shim
answers that query; these values come from the same place RADV gets them (AMDGPU_INFO_DEV_INFO), so the choice
stays AMD's own. The model rules below mirror the IsSupported checks of amdxcffx64 2.4.0.4370 (FSR 4.1.2).
"""

import glob
import os
import struct

# DRM_IOW(DRM_COMMAND_BASE + DRM_AMDGPU_INFO, struct drm_amdgpu_info), the struct being 32 bytes.
DRM_IOCTL_AMDGPU_INFO = (1 << 30) | (32 << 16) | (ord("d") << 8) | (0x40 + 0x05)
AMDGPU_INFO_DEV_INFO = 0x16

# Families (AMDGPU_FAMILY_*): 143 NV (RDNA1/2), 144 VGH (Van Gogh), 145 GC 11.0 (RDNA3), 150 GC 11.5 (RDNA 3.5),
# 152 GC 12 (RDNA4).
MODELS = {"FP8": "FP8", "INT8": "INT8", "INT8_NAVI2": "INT8 (RDNA2)", "INT8_LITE": "INT8 Lite"}
ARCH = {143: "RDNA 1/2", 144: "RDNA 2 APU (Van Gogh)", 145: "RDNA 3", 148: "RDNA 3 APU", 150: "RDNA 3.5",
        152: "RDNA 4"}
# (family, revision range) combinations checked on real hardware.
VERIFIED = [(150, 1, 0x3F)]  # Radeon 880M/890M (Strix Point), Legion Go 2


def expected_model(family, rev):
    """The model amdxcffx64 4.1.2 accepts for this GPU, in the order it checks them, or None (FSR 3 stays)."""
    if family == 152:
        return "FP8"
    if (family == 145 and 1 <= rev <= 0xFE) or (family == 150 and 0xC0 <= rev <= 0xCF):
        return "INT8"
    if family == 143 and 0x28 <= rev <= 0x4F:
        return "INT8_NAVI2"
    if (family == 150 and 1 <= rev <= 0x3F) or (family == 144 and 1 <= rev <= 0x7F):
        return "INT8_LITE"
    return None


def is_verified(family, rev):
    return any(f == family and lo <= rev <= hi for f, lo, hi in VERIFIED)


def _query(path):
    """(device_id, family, external_rev) of one render node, via AMDGPU_INFO_DEV_INFO."""
    import ctypes
    import fcntl  # Linux only; imported here so the module (and its tests) load anywhere

    out = ctypes.create_string_buffer(256)
    request = struct.pack("<QII16x", ctypes.addressof(out), len(out), AMDGPU_INFO_DEV_INFO)
    fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
    try:
        fcntl.ioctl(fd, DRM_IOCTL_AMDGPU_INFO, request)
    finally:
        os.close(fd)
    device_id, _chip_rev, external_rev, _pci_rev, family = struct.unpack_from("<5I", out.raw)
    return device_id, family, external_rev


# Used only if the kernel query fails: values measured with RADV_DEBUG=info (same table as the shim's).
KNOWN = {0x150E: (150, 20)}  # Radeon 890M, Legion Go 2


def _sysfs_int(sysfs, node, name):
    with open(os.path.join(sysfs, os.path.basename(node), "device", name)) as f:
        return int(f.read(), 16)


def detect(dri="/dev/dri", sysfs="/sys/class/drm", query=None):
    """The first AMD GPU as {device, family, rev, model, verified}, or None when there is none or it can't be read."""
    query = query or _query
    for node in sorted(glob.glob(os.path.join(dri, "renderD*"))):
        try:
            if _sysfs_int(sysfs, node, "vendor") != 0x1002:
                continue
        except (OSError, ValueError):
            continue
        try:
            device, family, rev = query(node)
        except (OSError, ValueError, ImportError, AttributeError):
            try:
                device = _sysfs_int(sysfs, node, "device")
            except (OSError, ValueError):
                continue
            if device not in KNOWN:
                continue
            family, rev = KNOWN[device]
        model = expected_model(family, rev)
        return {"device": device, "family": family, "rev": rev, "arch": ARCH.get(family, f"family {family}"),
                "model": model, "model_name": MODELS.get(model, ""), "verified": is_verified(family, rev)}
    return None
