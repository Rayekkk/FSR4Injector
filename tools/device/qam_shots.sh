#!/bin/bash
# qam_shots.sh <out dir>: README screenshots of the FSR4 Injector panel in the Quick Access Menu, one per section,
# clipped to the menu like the Companion plugins' (375 × 695 CSS px, 577 × 1070 on the Legion Go 2).
set -eu
out=$1; mkdir -p "$out"
D=$(dirname "$0")
cdp() { python3 -I "$D/cdp.py" eval "$1"; }
qam() { CDP_TARGET=QuickAccess_uid2 python3 -I "$D/cdp.py" "$@"; }
cdp "DFL.Navigation.OpenQuickAccessMenu(999), DeckyPluginLoader.deckyState.setActivePlugin('FSR4 Injector'), 1" >/dev/null
sleep 2
# <file> <heading text to scroll to top, or '' for the top of the panel>
shot() {
  qam eval "(() => { const h = [...document.querySelectorAll('*')].find(e => e.childElementCount === 0 && e.textContent.trim().toLowerCase() === '$2'.toLowerCase()); if ('$2' && !h) return 'missing'; (h || document.querySelector('*')).scrollIntoView({block: 'start'}); return 'ok'; })()" | grep -q ok || { echo "section '$2' not found"; return; }
  sleep 1
  qam shot "$out/$1" 0 0 375 695
  echo "$out/$1"
}
shot overview.png ""
shot games.png "Games with FSR 3.1+"
shot launch-options.png "Launch options"
shot about.png "About"
cdp "DFL.Navigation.CloseSideMenus(), 1" >/dev/null
