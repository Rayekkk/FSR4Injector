#!/bin/bash
# Install a plugin ZIP through Decky's own root installer (no sudo needed), confirming its prompt.
# Usage: decky_install.sh <zip> <plugin name> <version>
set -euo pipefail
zip=$1 name=$2 version=$3
hash=$(sha256sum "$zip" | cut -d' ' -f1)
cdp() { python3 -I ~/lg2c-tools/cdp.py eval "$1"; }
since=$(date '+%Y-%m-%d %H:%M:%S')

cdp "DeckyBackend.call('utilities/install_plugin', 'file://$zip', '$name', '$version', '$hash', 0).then(() => 'requested')" >/dev/null
req=""
for i in $(seq 1 20); do
  req=$(journalctl -u plugin_loader --since "$since" --no-pager | grep -a "add_plugin_install_prompt with args ('$name'" | tail -1 | sed -E "s/.*'$version', '([0-9.]+)'.*/\1/")
  [ -n "$req" ] && break; sleep 0.5
done
[ -n "$req" ] || { echo "no install prompt seen"; exit 1; }
cdp "DeckyBackend.call('utilities/confirm_plugin_install', '$req').then(() => 'confirmed')" >/dev/null
for i in $(seq 1 30); do
  journalctl -u plugin_loader --since "$since" --no-pager | grep -aq "Loaded $name (v$version)" && break; sleep 1
done
# The prompt modal Decky raised is stale now; close it.
CDP_TARGET="Steam Big Picture Mode" python3 -I ~/lg2c-tools/cdp.py eval "(() => { const b = [...document.querySelectorAll('button, .DialogButton')].find(e => e.innerText.trim() === 'Cancel' && e.closest('.ModalPosition, [role=dialog], .DialogContent')); if (b) b.click(); return !!b; })()" >/dev/null
journalctl -u plugin_loader --since "$since" --no-pager | grep -a "Loaded $name" | tail -1
python3 -I ~/lg2c-tools/cdp.py magic-on >/dev/null
