# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""GPU detection through the amdgpu driver and the FSR4 model AMD's DLL picks for it."""

import os
import tempfile
import unittest

import _harness  # noqa: F401
import fsr4_gpu as G


class Model(unittest.TestCase):
    def test_amd_dll_rules(self):
        cases = {
            (150, 20): "INT8_LITE",    # Radeon 890M (Strix Point), measured on a Legion Go 2
            (150, 0xC1): "INT8",       # Strix Halo
            (144, 1): "INT8_LITE",     # Van Gogh (Steam Deck, Z2 A)
            (143, 0x28): "INT8_NAVI2", # RX 6800 (Navi 21)
            (143, 0x46): "INT8_NAVI2", # RX 6500 (Navi 24)
            (143, 0x01): None,         # Navi 10 (RDNA1): no model
            (145, 0x01): "INT8",       # RX 7000
            (148, 0x01): None,         # Phoenix (780M, Z1 Extreme): AMD has no model
            (152, 0x01): "FP8",        # RX 9000
        }
        for (family, rev), model in cases.items():
            self.assertEqual(G.expected_model(family, rev), model, (family, rev))

    def test_only_strix_point_is_verified(self):
        self.assertTrue(G.is_verified(150, 20))
        self.assertFalse(G.is_verified(144, 1))
        self.assertFalse(G.is_verified(150, 0xC1))


class Detect(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.dri = os.path.join(self.base, "dri")
        self.sys = os.path.join(self.base, "sys")
        os.makedirs(self.dri)

    def node(self, name, vendor, device):
        open(os.path.join(self.dri, name), "w").close()
        d = os.path.join(self.sys, name, "device")
        os.makedirs(d)
        for key, value in (("vendor", vendor), ("device", device)):
            with open(os.path.join(d, key), "w") as f:
                f.write(f"0x{value:04x}\n")

    def test_reads_the_amd_gpu(self):
        self.node("renderD128", 0x10DE, 0x2684)  # an NVIDIA card first is skipped
        self.node("renderD129", 0x1002, 0x163F)
        gpu = G.detect(self.dri, self.sys, query=lambda path: (0x163F, 144, 1))
        self.assertEqual(gpu, {"device": 0x163F, "family": 144, "rev": 1, "arch": "RDNA 2 APU (Van Gogh)",
                               "model": "INT8_LITE", "model_name": "INT8 Lite", "verified": False})

    def test_known_gpu_when_the_kernel_query_fails(self):
        self.node("renderD128", 0x1002, 0x150E)

        def broken(path):
            raise OSError("ioctl not permitted")
        gpu = G.detect(self.dri, self.sys, query=broken)
        self.assertEqual((gpu["family"], gpu["rev"], gpu["model"], gpu["verified"]), (150, 20, "INT8_LITE", True))

    def test_unknown_gpu_when_the_kernel_query_fails(self):
        self.node("renderD128", 0x1002, 0x163F)
        self.assertIsNone(G.detect(self.dri, self.sys, query=lambda path: (_ for _ in ()).throw(OSError())))

    def test_no_amd_gpu(self):
        self.assertIsNone(G.detect(self.dri, self.sys))


if __name__ == "__main__":
    unittest.main()
