#!/bin/bash
# Builds build/amdxc64.dll with MinGW-w64 (x86_64) and runs the self-test against the AMD DLL given as $1.
#   ./build.sh [path/to/amdxcffx64.dll]
set -euo pipefail
cd "$(dirname "$0")"
CC=${CC:-x86_64-w64-mingw32-gcc}
command -v "$CC" >/dev/null || CC=gcc
CFLAGS="-O2 -Wall -Wextra -Wno-unused-parameter -Wno-cast-function-type -std=gnu11 ${CFLAGS_EXTRA:-}"
mkdir -p build

# --no-insert-timestamp: the same source gives the same DLL, so bin/amdxc64.dll only changes in git when the code does
"$CC" $CFLAGS -shared -o build/amdxc64.dll src/amdxc64.c src/fsr4i.c -Wl,--kill-at,--no-insert-timestamp -static-libgcc -s
"$CC" $CFLAGS -DFSR4I_NO_DLLMAIN -o build/test_shim.exe test/test_shim.c src/amdxc64.c src/fsr4i.c -static-libgcc
mkdir -p ../bin && cp build/amdxc64.dll ../bin/amdxc64.dll  # where the plugin backend ships it from

if [ $# -ge 1 ]; then
    ./build/test_shim.exe "$1"
fi
