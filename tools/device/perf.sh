#!/bin/bash
# Usage: perf.sh <label> <appid> <exe-substring> <launch options...>
# Starts the game, logs 40 s of mangoapp frame stats after 60 s, screenshots, stops the game, clears launch options.
set -u
label=$1 app=$2 exe=$3; shift 3; opts="$*"
out=~/fsr4test/results/$label; mkdir -p "$out"; rm -f "$out"/*
cdp() { python3 -I ~/lg2c-tools/cdp.py eval "$1"; }
js_opts=$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$opts")

cdp "SteamClient.Apps.SetAppLaunchOptions($app, $js_opts), 'set'" > /dev/null
rm -f ~/steam-$app.log
cdp "SteamClient.Apps.RunGame('$app', '', -1, 100), 'run'" > /dev/null
for i in $(seq 1 120); do pgrep -f "$exe" >/dev/null && break; sleep 1; done
sleep 60
touch "$out/.stamp"
mangohudctl set log_session 1; sleep 40; mangohudctl set log_session 0; sleep 2
gamescopectl screenshot "$out/shot.png" >/dev/null 2>&1
cdp "SteamClient.Apps.TerminateApp('$app', false), 'stop'" > /dev/null
for i in $(seq 1 60); do pgrep -f "$exe" >/dev/null || break; sleep 1; done
cdp "SteamClient.Apps.SetAppLaunchOptions($app, ''), 'cleared'" > /dev/null
cp ~/steam-$app.log "$out/steam.log" 2>/dev/null
csv=$(find ~ -maxdepth 3 -name "*.csv" -newer "$out/.stamp" 2>/dev/null | grep -v summary | head -1)
[ -n "$csv" ] && mv "$csv" "$out/frames.csv"
python3 -I ~/lg2c-tools/cdp.py magic-on > /dev/null
python3 -I - "$out/frames.csv" "$label" <<'EOF'
import csv, sys, statistics as st
try:
    rows = list(csv.reader(open(sys.argv[1])))
except OSError:
    sys.exit(f'{sys.argv[2]}: no frame log')
hi = next(i for i, r in enumerate(rows) if r and r[0] == 'fps')
h = rows[hi]; data = [r for r in rows[hi + 1:] if len(r) == len(h)]
col = lambda n: [float(r[h.index(n)]) for r in data if n in h and r[h.index(n)] not in ('', 'nan')]
fps, ft, gpu, gclk, gpow = col('fps'), col('frametime'), col('gpu_load'), col('gpu_core_clock'), col('gpu_power')
fts = sorted(ft); p99 = fts[int(len(fts) * 0.99) - 1] if fts else 0
m = lambda v: f'{st.mean(v):.1f}' if v else 'n/a'
print(f'{sys.argv[2]}: samples={len(ft)} fps_avg={m(fps)} frametime_avg={m(ft)}ms ft_p99={p99:.2f}ms gpu_load={m(gpu)}% gpu_clk={m(gclk)}MHz gpu_power={m(gpow)}W')
EOF
