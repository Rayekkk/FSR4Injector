#!/bin/bash
# A/B/C session scenarios for Spider-Man Remastered with the plugin enabled.
G="$HOME/.local/share/Steam/steamapps/common/Marvel's Spider-Man Remastered"
PLUGIN="WINEDLLOVERRIDES=amdxc64=n,b ~/.dlo/run %command%"
cdp() { python3 -I ~/fsr4test/cdp.py eval "$1"; }
set_opts() { cdp "SteamClient.Apps.SetAppLaunchOptions(1817070, $(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$1")), 'set'" >/dev/null; }
toasts() {
  for i in $(seq 1 8); do
    t=$(CDP_TARGET=notificationtoasts_uid2 python3 -I ~/fsr4test/cdp.py eval "document.body.innerText" 2>/dev/null)
    case "$t" in *"FSR4 not active"*) echo "  toast: $(echo "$t" | tr '\n' ' ' | cut -c1-220)"; return;; esac
    sleep 0.5
  done
  echo "  toast: none"
}
scenario() {
  label=$1 opts=$2
  echo "== $label: $opts"
  set_opts "$opts"
  since=$(date '+%Y-%m-%d %H:%M:%S')
  ~/fsr4test/play.sh "$label" 1817070 Spider-Man.exe 70 >/dev/null
  toasts
  journalctl -u plugin_loader --since "$since" --no-pager | grep -a "FSR4 not active for" | sed 's/.*FSR4 not active/  log: FSR4 not active/' | cut -c1-260
  python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); print("  status:", s["started"], "active=", s["active"], "family=", s["family"])' "$G/fsr4injector.status.json" 2>/dev/null
}
scenario A_normal "$PLUGIN"
scenario B_token_removed "~/.dlo/run %command%"
scenario C_dll_rejects "$PLUGIN FSR4I_FAMILY=1 FSR4I_REV=1"
set_opts "$PLUGIN"
~/fsr4test/fsr4call.sh get_state | python3 -c 'import json,sys; s=json.loads(json.loads(sys.stdin.read())); g=[g for g in s["games"] if g["appid"]==1817070][0]; print("panel view:", g["enabled"], g["verdict"], g["reason"])'
