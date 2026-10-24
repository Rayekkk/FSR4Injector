# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Rayekkk

"""Noticing SteamOS/Proton updates since FSR4 was last confirmed."""

import os
import tempfile
import unittest

import _harness  # noqa: F401
import fsr4_env as E


def _file(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class Env(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.osr = os.path.join(d, "os-release")
        self.proton = os.path.join(d, "Proton 11.0")
        _file(self.osr, 'NAME="SteamOS"\nVERSION_ID=3.9.5\nBUILD_ID=20261023.100\n')
        _file(os.path.join(self.proton, "version"), "1791559474 proton-11.0-2e\n")

    def test_reads_versions(self):
        self.assertEqual(E.steamos_build(self.osr), "3.9.5 (20261023.100)")
        self.assertEqual(E.proton_version(self.proton), "proton-11.0-2e")
        self.assertEqual(E.proton_version(""), "")
        self.assertEqual(E.steamos_build(self.osr + ".missing"), "")

    def test_no_change_right_after_verification(self):
        fp = E.fingerprint({"compat_tool": self.proton, "shim": "0.1.0"}, self.osr)
        self.assertEqual(fp["proton"], "proton-11.0-2e")
        self.assertEqual(E.changes(fp, self.osr), [])
        self.assertEqual(E.changes(None, self.osr), [])

    def test_reports_steamos_and_proton_updates(self):
        fp = E.fingerprint({"compat_tool": self.proton}, self.osr)
        _file(self.osr, "VERSION_ID=3.9.6\nBUILD_ID=20261101.1\n")
        _file(os.path.join(self.proton, "version"), "1792000000 proton-11.0-3\n")
        self.assertEqual(E.changes(fp, self.osr),
                         ["SteamOS 3.9.5 (20261023.100) → 3.9.6 (20261101.1)", "Proton proton-11.0-2e → proton-11.0-3"])

    def test_unknown_values_are_not_a_change(self):
        fp = E.fingerprint({}, self.osr)  # old shim without compat_tool
        self.assertEqual(E.changes(fp, self.osr), [])


if __name__ == "__main__":
    unittest.main()
