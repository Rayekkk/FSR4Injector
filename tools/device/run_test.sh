#!/bin/bash
# Usage: run_test.sh <label> <appid> <exe-substring> <wait-seconds> <launch options...>
# Sets Steam launch options via CDP, starts the game, screenshots, records loaded FSR DLLs, stops the game.
set -u
label=$1 app=$2 exe=$3 wait=$4; shift 4; opts="$*"
out=~/fsr4test/results/$label; mkdir -p "$out"; rm -f "$out"/*
cdp() { python3 -I ~/lg2c-tools/cdp.py eval "$1"; }
js_opts=$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$opts")

cdp "SteamClient.Apps.SetAppLaunchOptions($app, $js_opts), 'set'" > "$out/cdp.txt"
rm -f ~/steam-$app.log
cdp "SteamClient.Apps.RunGame('$app', '', -1, 100), 'run'" >> "$out/cdp.txt"

pid=""
for i in $(seq 1 120); do pid=$(pgrep -f "$exe" | head -1); [ -n "$pid" ] && break; sleep 1; done
[ -z "$pid" ] && { echo "game did not start" | tee "$out/error.txt"; exit 1; }
echo "pid=$pid start=$(date +%T)" > "$out/info.txt"

for t in $(seq 30 30 "$wait"); do
  sleep 30
  pid=$(pgrep -f "$exe" | head -1); [ -z "$pid" ] && { echo "game exited at ${t}s" >> "$out/info.txt"; break; }
  gamescopectl screenshot "$out/shot_${t}s.png" >/dev/null 2>&1
  awk '$6 ~ /amdxc|fidelityfx/ {print $6}' /proc/$pid/maps 2>/dev/null | sort -u > "$out/maps_${t}s.txt"
done

cdp "SteamClient.Apps.TerminateApp('$app', false), 'stop'" >> "$out/cdp.txt"
for i in $(seq 1 60); do pgrep -f "$exe" >/dev/null || break; sleep 1; done
cdp "SteamClient.Apps.SetAppLaunchOptions($app, ''), 'cleared'" >> "$out/cdp.txt"
grep -a -i -E "amdxc|fidelityfx|FSR4|Replaced|unsupported" ~/steam-$app.log 2>/dev/null | grep -v -i "fixme" | head -40 > "$out/log.txt"
cp ~/steam-$app.log "$out/steam.log" 2>/dev/null
python3 -I ~/lg2c-tools/cdp.py magic-on >> "$out/info.txt" 2>&1
echo done >> "$out/info.txt"
