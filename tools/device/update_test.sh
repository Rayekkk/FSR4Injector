#!/bin/bash
# Update-awareness test for FSR4 Injector on Spider-Man Remastered.
set -u
T=~/fsr4test; Z=$T/release/FSR4Injector-0.1.0.zip; S=~/homebrew/settings/FSR4Injector
G="$HOME/.local/share/Steam/steamapps/common/Marvel's Spider-Man Remastered"
tog() { sed -e "s/__APPID__/1817070/" -e "s/__ON__/$1/" $T/panel_toggle.js > /tmp/pt.js; python3 -I ~/fsr4test/cdp.py eval "$(cat /tmp/pt.js)" >/dev/null; }
view() { $T/fsr4call.sh get_state | python3 -c 'import json,sys; s=json.loads(json.loads(sys.stdin.read())); g=[g for g in s["games"] if g["appid"]==1817070][0]; print("  panel:", g["verdict"], "|", g["reason"])'; }
toast() { for i in $(seq 1 10); do for t in notificationtoasts_uid2 "Steam Big Picture Mode"; do x=$(CDP_TARGET="$t" timeout 3 python3 -I ~/fsr4test/cdp.py eval "document.body.innerText.includes('$1') ? 'yes' : ''" 2>/dev/null); [ "$x" = '"yes"' ] && { echo "  toast '$1' in $t"; return; }; done; sleep 0.5; done; echo "  toast '$1': not seen"; }

echo "1) install, enable, play"
$T/decky_install.sh $Z "FSR4 Injector" 0.1.0 >/dev/null; sleep 2
echo "  env.json: $(cat $S/env.json 2>/dev/null)"
tog true
$T/play.sh u1 1817070 Spider-Man.exe 70 >/dev/null; sleep 3
python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); print("  status:", s["active"], "| compat_tool:", s["compat_tool"])' "$G/fsr4injector.status.json"
python3 -c 'import json; e=json.load(open("'$S'/manifest.json"))["1817070"]; print("  verified:", e.get("verified"))'
view

echo "2) simulate Proton + SteamOS update and an old shim in the game, then restart the plugin"
cp $T/proxy/amdxc64.dll "$G/amdxc64.dll"
python3 - "$S" "$G" <<'EOF'
import hashlib, json, sys
s, g = sys.argv[1:3]
m = json.load(open(f"{s}/manifest.json")); e = m["1817070"]
e["verified"]["proton"] = "proton-11.0-1"
e["files"]["amdxc64.dll"] = hashlib.sha256(open(f"{g}/amdxc64.dll", "rb").read()).hexdigest()
json.dump(m, open(f"{s}/manifest.json", "w"))
json.dump({"steamos": "3.9.4 (20261001.1)"}, open(f"{s}/env.json", "w"))
EOF
since=$(date '+%Y-%m-%d %H:%M:%S')
$T/decky_install.sh $Z "FSR4 Injector" 0.1.0 >/dev/null
toast "SteamOS was updated"
journalctl -u plugin_loader --since "$since" --no-pager | grep -a "updated amdxc64.dll in" | sed 's/.*PluginLoader\[[0-9]*\]: /  log: /'
echo "  shim in game == bundled: $(cmp -s "$G/amdxc64.dll" ~/homebrew/plugins/FSR4Injector/bin/amdxc64.dll && echo yes || echo NO)"
view

echo "3) play again: re-checked"
$T/play.sh u2 1817070 Spider-Man.exe 70 >/dev/null; sleep 3
view

echo "4) rollback"
tog false
echo "  files left: $(ls "$G" | grep -ci -E 'amdxc|fsr4injector')"
python3 -I ~/fsr4test/cdp.py eval "new Promise(r=>{let d=0;const g=SteamClient.Apps.RegisterForAppDetails(1817070,x=>{if(d)return;d=1;setTimeout(()=>g?.unregister?.(),0);r(x?.strLaunchOptions)})})"
