# Changelog

All notable changes to FSR4 Injector, newest first.

## [Unreleased]

### ✨ Added
- **Repair:** re-checks AMD's library and puts the plugin's files and launch option back in every game that has
  FSR 4 on, for example after a game update or Steam's file check.
- **Repair:** if AMD's library itself is damaged or missing, it tells you to download it again first.
- **Decky Launch Options:** with [Decky Launch Options](https://github.com/Rayekkk/DeckyLaunchOptions) installed,
  **Add to Decky Launch Options** offers the FSR4 launch option and AMD's watermark to it, to switch per game there.
- **About:** **Use Rayek's store** makes Rayek's store Decky's store channel after you confirm, so Decky's Store
  tab lists Rayek's plugins and offers their updates.

### 🔧 Changed

**Panel**
- The About and Updates sections moved to an About page, opened from the last row of the panel; Updates
  is at the bottom of that page.
- When the plugin cannot start, the panel says "FSR4 Injector unavailable" with a Try again button, and
  you can still check for updates below it.
- When turning FSR 4 on or off, a setting or a rescan fails, the reason now also stays under that control
  until it next succeeds, not only in a message.
- An untested GPU gets its own "Beta" row; download sizes are in MB; an empty game list says what to do.

**Updates**
- A downloaded update shows its folder as `~/Downloads/…`, and the update texts match the other plugins
  (for example "Checking GitHub…").

**Launch options**
- Games that already set `WINEDLLOVERRIDES` (your own overrides, or another tool such as ReShade
  or OptiScaler) no longer refuse FSR 4; the plugin adds `amdxc64=n,b` to that variable.
- Turning FSR 4 off takes out only the plugin's own entry from `WINEDLLOVERRIDES`.

**Games**
- Games on the same drive share one copy of AMD's library instead of 82 MB each.

**Status**
- "DLL was not loaded" is shown only when it happens in two sessions in a row, so closing a game in its
  launcher no longer raises a warning.

### 🐛 Fixed

**AMD download**
- An unexpected error no longer leaves the panel stuck on "Downloading from AMD"; you can try
  again at once.
- It fetches exactly the part of AMD's package it needs (about 43 MB, which the progress now
  counts) and checks it before decoding.
- A slow connection gets up to 30 minutes, and Cancel stops the download at once.

**Launch options**
- After turning a game on, the plugin checks what Steam actually kept. If Steam did not keep the
  new launch options you are told, and turning FSR 4 off still restores your own options exactly.

**Settings**
- A switch that cannot be saved (for example on a full disk) stays as it was and says why, instead of
  looking changed until the next restart.
- Two switches changed in quick succession are both kept; before, the second could undo the first.

**Watermark**
- A game whose launch options could not be updated for the watermark is named in a message instead
  of being skipped silently.

**Game list**
- A damaged list of games set up is restored from its backup copy. If that is impossible, the panel
  says so and no game can be changed, instead of forgetting which files are the plugin's.

**Updates**
- "Check for updates" says when no release has been published yet instead of "Up to date", and a
  second download at the same time is refused.
- Updates are saved to your Downloads folder as the desktop names it in your language (for example
  `~/Pobrane`), instead of always `~/Downloads`.

**Files**
- Files written to game folders and the plugin's settings are flushed to disk, so a power loss cannot
  leave half a file.

**Errors**
- Error messages no longer show file paths.

**Status**
- The plugin's status file is written as UTF-8 whatever the system language, so a Proton folder with
  non-English letters no longer confuses the check after a Proton update.

## [1.0.0] - 2026-10-25

### ✨ Added

**Plugin**
- First release.

**Install**
- Install from the release ZIP: in Decky Settings turn on **Developer mode**, then choose
  **Developer → Install Plugin from ZIP** and select `FSR4Injector-1.0.0.zip`.

**AMD download**
- **Accept and download** fetches AMD's FSR 4 library from AMD's official driver package (about
  43 MB).

**Games**
- Turn FSR 4 on per game under **Games with FSR 3.1+**; in the game, choose **AMD FSR** as the upscaler.

**Status**
- After you quit the game, the panel shows "FSR4 active", or a notification says what went wrong.
