#!/bin/bash
# Plan B probe: OptiScaler 0.9.4 (fsr31 backend, Fsr4Update) translating a game's XeSS/FSR2/DLSS inputs, with our
# amdxc64 shim + AMD's amdxcffx64 4.1.2 answering the driver-side FSR4 upgrade.
# Usage: optiscaler_test.sh <label> <appid> <game exe dir> <exe name> <seconds>
# Needs ~/fsr4test/opti (extracted OptiScaler 0.9.4), ~/fsr4test/412/amdxcffx64.dll and the plugin's bin/amdxc64.dll.
# Adds only files that are not in the game folder yet, and removes exactly those afterwards.
set -u
label=$1 app=$2 dir=$3 exe=$4 wait=$5
T=~/fsr4test; O=$T/opti; out=$T/results/$label; mkdir -p "$out"; rm -f "$out"/*
added="$out/added.txt"; : > "$added"
cdp() { python3 -I ~/lg2c-tools/cdp.py eval "$1"; }
opts_of() { cdp "new Promise(r=>{let d=0;const g=SteamClient.Apps.RegisterForAppDetails($app,x=>{if(d)return;d=1;setTimeout(()=>g?.unregister?.(),0);r(x?.strLaunchOptions??'')})})"; }
set_opts() { cdp "SteamClient.Apps.SetAppLaunchOptions($app, $(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$1")), 'set'" >/dev/null; }
put() { # put <src> <name in game dir>
  [ -e "$dir/$2" ] && { echo "CONFLICT: $2 exists in the game folder, aborting"; exit 1; }
  cp "$1" "$dir/$2" && echo "$dir/$2" >> "$added"
}

original=$(opts_of | python3 -c 'import json,sys; print(json.loads(sys.stdin.read()))')
echo "original launch options: $original" | tee "$out/info.txt"

# FULL=1: every file of the OptiScaler archive the game does not already have (its own copies stay in use).
if [ "${FULL:-0}" = 1 ]; then
  (cd "$O" && find . -type f ! -name OptiScaler.dll ! -name OptiScaler.ini ! -name '*.sh' ! -name '*.bat' ! -name '*.txt' ! -path './Licenses/*') |
  while IFS= read -r f; do
    f=${f#./}
    if [ -e "$dir/$f" ]; then echo "  keeping the game's own $f"; continue; fi
    mkdir -p "$dir/$(dirname "$f")"; cp "$O/$f" "$dir/$f" && echo "$dir/$f" >> "$added"
  done
  [ -d "$dir/D3D12_Optiscaler" ] && echo "$dir/D3D12_Optiscaler" >> "$added.dirs"
else
  for f in amd_fidelityfx_dx12.dll amd_fidelityfx_upscaler_dx12.dll; do put "$O/$f" "$f"; done
fi
# PROXY=<name>: the DLL name OptiScaler is loaded as (dxgi by default).
proxy=${PROXY:-dxgi}
put "$O/OptiScaler.dll" "$proxy.dll"
overrides=$proxy
# SHIM=0: OptiScaler alone, without our amdxc64 / AMD 4.1.2 DLL, to tell their problems apart.
if [ "${SHIM:-1}" = 1 ]; then
  put "$T/412/amdxcffx64.dll" amdxcffx64.dll
  put ~/homebrew/plugins/FSR4Injector/bin/amdxc64.dll amdxc64.dll
  printf '5390 150 20\n' > "$dir/fsr4injector.gpu" && echo "$dir/fsr4injector.gpu" >> "$added"
  overrides=$proxy,amdxc64
fi
# INI="Key=value Key2=value2": extra OptiScaler.ini settings (each key must be a unique "=auto" line).
python3 - "$O/OptiScaler.ini" "$dir/OptiScaler.ini" ${INI:-} <<'EOF'
import re, sys
src, dst = sys.argv[1:3]
want = {"Dx12Upscaler": "fsr31", "Fsr4Update": "true", "Fsr4EnableWatermark": "true", "Dxgi": "false",
        "LogToFile": "true", "LogLevel": "2"}
want.update(kv.split("=", 1) for kv in sys.argv[3:])
text = open(src, encoding="utf-8").read()
for k, v in want.items():
    text, n = re.subn(rf"^{k}=auto$", f"{k}={v}", text, flags=re.M)
    assert n == 1, k
open(dst, "w", encoding="utf-8").write(text)
EOF
echo "$dir/OptiScaler.ini" >> "$added"; echo "$dir/OptiScaler.log" >> "$added"
for f in fsr4injector.status.json fsr4injector.status.json.tmp; do echo "$dir/$f" >> "$added"; done

# Env vars only work in front of %command%; options without it are game arguments. ARGS: extra game arguments.
case $original in *%command%*) cmd=$original ;; *) cmd="%command% $original" ;; esac
set_opts "WINEDLLOVERRIDES=$overrides=n,b FSR_WATERMARK=1 PROTON_LOG=+amdxc $cmd ${ARGS:-}"
rm -f ~/steam-$app.log
# LAUNCH=<n>: Steam launch entry; -1 opens Steam's chooser in games with several entries.
cdp "SteamClient.Apps.RunGame('$app', '', ${LAUNCH:--1}, 100), 'run'" >/dev/null
# Wine shows the game as a Windows path, case not kept (retail\hitman3.exe); in our own command line the bare name
# follows a space. (pgrep does not match a literal backslash.)
running() { pgrep -i -f "[^ /]${exe##*/}" >/dev/null; }
seen=0; for i in $(seq 1 120); do running && { seen=1; break; }; sleep 1; done
if [ "${HOLD:-0}" = 1 ]; then
  # never end a session someone plays just because we failed to spot the process; wait for $out/stop instead
  [ $seen = 1 ] || { echo "game process not spotted; holding until stop" >> "$out/info.txt"; ps -eo args | grep -i "${exe%.*}" > "$out/ps.txt"; }
  # HOLD=1: someone plays; touch $out/shot for a screenshot, $out/stop (or quit the game) to finish. <seconds> caps it.
  n=0
  for t in $(seq 1 "$wait"); do
    sleep 1
    if [ -e "$out/shot" ]; then rm -f "$out/shot"; n=$((n+1)); gamescopectl screenshot "$out/held_$n.png" >/dev/null 2>&1; echo "shot $n at ${t}s" >> "$out/info.txt"; fi
    [ -e "$out/stop" ] && break
    [ $seen = 0 ] || running || { echo "game ended at ${t}s" >> "$out/info.txt"; break; }
  done
else
  for t in $(seq 30 30 "$wait"); do
    sleep 30; gamescopectl screenshot "$out/shot_${t}s.png" >/dev/null 2>&1
    echo "${t}s: proton log lines $(wc -l < ~/steam-$app.log 2>/dev/null)" >> "$out/info.txt"
  done
fi
cdp "SteamClient.Apps.TerminateApp('$app', false), 'stop'" >/dev/null
for i in $(seq 1 60); do running || break; sleep 1; done
sleep 2

cp "$dir/OptiScaler.log" "$out/" 2>/dev/null; cp "$dir/fsr4injector.status.json" "$out/" 2>/dev/null
cp ~/steam-$app.log "$out/steam.log" 2>/dev/null
set_opts "$original"
while IFS= read -r f; do rm -f "$f"; done < "$added"
[ -f "$added.dirs" ] && while IFS= read -r d; do rmdir "$d" 2>/dev/null; done < "$added.dirs"
echo "restored launch options: $(opts_of)" >> "$out/info.txt"
echo "left in game folder: $(ls "$dir" | grep -c -i -E 'optiscaler|amdxc|fsr4injector|amd_fidelityfx|^(dxgi|winmm|winhttp|version|dbghelp|d3d12)\.dll$')" >> "$out/info.txt"
python3 -I ~/lg2c-tools/cdp.py magic-on >/dev/null
cat "$out/info.txt"
