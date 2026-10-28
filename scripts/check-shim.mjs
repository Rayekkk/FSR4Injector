#!/usr/bin/env node
// SPDX-License-Identifier: BSD-3-Clause
// Before packaging: the shipped bin/amdxc64.dll must be the current build of shim/ (shim/build.sh copies it there
// and builds deterministically). Where shim/ was not built (CI's package job) only its presence is checked.
import { existsSync, readFileSync } from "node:fs";

const bin = "bin/amdxc64.dll", build = "shim/build/amdxc64.dll";
const fail = message => { console.error(`error: ${message}`); process.exit(1); };
if (!existsSync(bin)) fail(`${bin} is missing - run bash shim/build.sh`);
if (existsSync(build) && !readFileSync(build).equals(readFileSync(bin)))
  fail(`${bin} differs from ${build} - rerun bash shim/build.sh`);
