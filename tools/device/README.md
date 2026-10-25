# On-device test scripts

Run on the handheld over SSH (copy them to `~/fsr4test/`). They drive Steam and Decky through the Steam
client's CEF debugger with `~/lg2c-tools/cdp.py` (a small stdlib CDP evaluator from LegionGo2Companion's tooling).

| Script | Purpose |
|---|---|
| `decky_install.sh <zip> <name> <version>` | Install a plugin ZIP through Decky's own root installer and confirm its prompt (no sudo) |
| `fsr4call.sh <method> [json args]` | Call an FSR4 Injector backend method the way the panel does |
| `panel_toggle.js` | The panel's enable/disable flow (read launch options, backend, apply); `__APPID__`/`__ON__` placeholders |
| `play.sh <label> <appid> <exe> <seconds>` | Start a game with its current launch options, screenshot, stop |
| `scenarios.sh` | Session checks: normal, launch option removed by another tool, AMD DLL refusing FSR4 |
| `update_test.sh` | SteamOS/Proton update detection, shim refresh after a plugin update, rollback |

They change launch options and game folders of the games they test; each restores what it changed.
