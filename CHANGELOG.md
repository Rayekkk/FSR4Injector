# Changelog

All notable changes to FSR4 Injector, newest first.

## [0.1.0] - 2026-10-25

First release: AMD's official FSR 4.1.2 with its Lite model in FSR 3.1+ games on the Radeon
880M/890M (Ryzen Z2 Extreme, Ryzen AI 9 300) under Proton.

### Added

- **The GPU's own model:** the plugin reads the GPU's real family and revision from the amdgpu
  driver and AMD's library picks its model from them, as on Windows. The panel shows the GPU and
  that model. Checked on the Radeon 890M (Lite); Steam Deck and Ryzen Z2 A (Lite), RX 6000
  (RDNA2 model), RX 7000 and Strix Halo (INT8) and RX 9000 (FP8) are marked beta until tested.
  GPUs AMD has no model for, such as the 780M, are refused with an explanation.
- **FSR 4 per game:** turn it on or off for each installed DirectX 12 game that uses FSR 3.1
  or newer. AMD's library chooses its Lite model by itself, as on Windows. Checked in
  Spider-Man Remastered, Spider-Man 2 and Clair Obscur: Expedition 33, on Proton 11 and Proton
  Experimental.
- **AMD's library from AMD:** **Accept and download** fetches the FSR 4 library from AMD's
  Adrenalin 26.10.1 package, about 43 MB instead of the full 1.7 GB, and keeps it only if its
  checksum matches. The plugin itself contains no AMD software.
- **Never fails silently:** after every session the plugin checks that FSR 4 really ran. If
  AMD's library fell back to FSR 3, or another tool removed the plugin's launch option, a
  notification says so and why.
- **Re-check after updates:** a game shows **↻ Re-check needed** when SteamOS or Proton changed
  since FSR 4 last ran, with the old and new versions. After a SteamOS update you are told once
  at startup.
- **Safe rollback:** files are only added, never overwritten; turning a game off removes only
  files that are still unchanged and restores the launch options, also when another plugin
  such as Decky Launch Options has its own entry there.
- **All games at once:** **Turn on FSR4 in all games** sets up every compatible game in the
  list and **Turn off FSR4 and restore all games** puts every one back as it was. Both show
  their progress and a summary.
- **Online games left alone:** Turn on all skips games Steam lists as online (MMO,
  Cross-Platform Multiplayer, Online PvP, Online Co-op) and games it has no categories for; the
  list marks them, and you can still turn them on one by one.
- **Updates keep your games set up:** the plugin's DLL in each game is brought up to date at
  the next start. **Turn off FSR4 and restore all games** cleans up before you uninstall.
- Anti-cheat games (Easy Anti-Cheat, BattlEye, Vanguard, XIGNCODE, nProtect GameGuard,
  PunkBuster, EQU8) are detected and blocked.
