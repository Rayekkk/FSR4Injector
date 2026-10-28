# On-device test scripts

Run on the handheld over SSH (copy them to `~/fsr4test/`). They drive Steam and Decky through the Steam
client's CEF debugger with `cdp.py` (a small stdlib CDP client in this folder). Installing the plugin, its logs,
single RPC calls and panel screenshots are DeckyKit's tools (`deploy`, `logs`, `call_rpc`, `qam_screenshot`); these
scripts are the multi-step game-session flows those tools do not cover.

| Script | Purpose |
|---|---|
| `cdp.py eval <js>` / `cdp.py shot <png>` | Evaluate JavaScript in, or screenshot, a Steam client page (`CDP_TARGET`, e.g. `QuickAccess_uid2`) |
| `fsr4call.sh <method> [json args]` | Call an FSR4 Injector backend method the way the panel does (for the scripts below) |
| `panel_toggle.js` | The panel's enable/disable flow (read launch options, backend, apply); `__APPID__`/`__ON__` placeholders |
| `play.sh <label> <appid> <exe> <seconds>` | Start a game with its current launch options, screenshot, stop |
| `scenarios.sh` | Session checks: normal, launch option removed by another tool, AMD DLL refusing FSR4 |
| `qam_shots.sh <out dir>` | The README screenshots: the plugin's Quick Access Menu panel, one PNG per section |
| `update_test.sh` | SteamOS/Proton update detection, shim refresh after a plugin restart, rollback (needs passwordless sudo on the device) |

They change launch options and game folders of the games they test; each restores what it changed.
