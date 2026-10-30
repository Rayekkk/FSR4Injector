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
# <file> <heading text to scroll to top, or '' for the top of the panel>; the controller's focus highlight is hidden
shot() {
  qam eval "(() => { document.querySelectorAll('.gpfocus, .gpfocuswithin').forEach(e => e.classList.remove('gpfocus', 'gpfocuswithin')); const h = [...document.querySelectorAll('*')].find(e => e.childElementCount === 0 && e.textContent.trim().toLowerCase() === '$2'.toLowerCase()); if ('$2' && !h) return 'missing'; (h || document.querySelector('*')).scrollIntoView({block: 'start'}); return 'ok'; })()" | grep -q ok || { echo "section '$2' not found"; return; }
  sleep 1
  qam shot "$out/$1" 0 0 375 695
  echo "$out/$1"
}
shot overview.png ""
shot games.png "Steam games"
shot launch-options.png "Launch options"
# About is a page of its own, opened from the panel's last row
qam eval "(() => { const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let n; while ((n = w.nextNode()) && n.textContent.trim() !== 'About'); n?.parentElement.closest('.Focusable, [tabindex], button')?.click(); return n ? 'ok' : 'missing'; })()" | grep -q ok || echo "About row not found"
sleep 2
shot about.png ""
cdp "DFL.Navigation.CloseSideMenus(), 1" >/dev/null
