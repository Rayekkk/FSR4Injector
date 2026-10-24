#!/bin/bash
# play.sh <label> <appid> <exe-substring> <seconds>: run a game with its current launch options, screenshot, stop.
set -u
label=$1 app=$2 exe=$3 wait=$4
out=~/fsr4test/results/$label; mkdir -p "$out"; rm -f "$out"/*
cdp() { python3 -I ~/lg2c-tools/cdp.py eval "$1"; }
cdp "SteamClient.Apps.RunGame('$app', '', -1, 100), 'run'" >/dev/null
for i in $(seq 1 120); do pgrep -f "$exe" >/dev/null && break; sleep 1; done
sleep "$wait"
gamescopectl screenshot "$out/shot.png" >/dev/null 2>&1
cdp "SteamClient.Apps.TerminateApp('$app', false), 'stop'" >/dev/null
for i in $(seq 1 60); do pgrep -f "$exe" >/dev/null || break; sleep 1; done
sleep 2
python3 -I ~/lg2c-tools/cdp.py magic-on >/dev/null
echo "$label done"
