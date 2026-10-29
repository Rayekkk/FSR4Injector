# Changelog

All notable changes to FSR4 Injector, newest first.

## [Unreleased]

### Changed

- **Panel:** the About and Updates sections moved to an About page, opened from the last row of
  the panel; Updates is at the bottom of that page. A downloaded update shows its folder as
  `~/Downloads/…`, and the update texts match the other plugins (for example "Checking GitHub…").
- **Panel:** when the plugin cannot start, the panel says "FSR4 Injector unavailable" with a Try
  again button, and you can still check for updates below it.
- **Panel:** when turning FSR 4 on or off, a setting or a rescan fails, the reason now also stays
  under that control until it next succeeds, not only in a message.
- **Panel:** an untested GPU gets its own "Beta" row; download sizes are in MB; an empty game list
  says what to do.

### Fixed

- **AMD download:** an unexpected error no longer leaves the panel stuck on "Downloading from AMD";
  you can try again at once. The download fetches exactly the part of AMD's package it needs (about
  43 MB, which the progress now counts) and checks it before decoding; a slow connection gets up to
  30 minutes, and Cancel stops the download at once.
- **Launch options:** after turning a game on, the plugin checks what Steam actually kept. If Steam
  did not keep the new launch options you are told, and turning FSR 4 off still restores your own
  options exactly.
- **Settings:** a switch that cannot be saved (for example on a full disk) stays as it was and says
  why, instead of looking changed until the next restart. Two switches changed in quick succession
  are both kept; before, the second could undo the first.
- **Watermark:** a game whose launch options could not be updated for the watermark is named in a
  message instead of being skipped silently.
- **List of games set up:** a damaged list is restored from its backup copy. If that is impossible,
  the panel says so and no game can be changed, instead of forgetting which files are the plugin's.
- **Plugin updates:** "Check for updates" says when no release has been published yet instead of
  "Up to date", and a second download at the same time is refused.
- Files written to game folders and the plugin's settings are flushed to disk, so a power loss
  cannot leave half a file, and error messages no longer show file paths.

## [1.0.1] - 2026-10-25

### Added

- **Repair FSR4 in all games:** re-checks AMD's library and puts the plugin's files and launch
  option back in every game that has FSR 4 on, for example after a game update or Steam's file
  check. If AMD's library itself is damaged or missing, it tells you to download it again first.

- **Decky Launch Options integration:** with
  [Decky Launch Options](https://github.com/Rayekkk/DeckyLaunchOptions) installed, **Add to Decky
  Launch Options** offers the FSR4 launch option and AMD's watermark to it, to switch per game there.

### Changed

- Games that already set `WINEDLLOVERRIDES` (your own overrides, or another tool such as ReShade or
  OptiScaler) no longer refuse FSR 4: the plugin adds `amdxc64=n,b` to that variable and takes only
  its own entry out again when you turn FSR 4 off.
- Games on the same drive share one copy of AMD's library instead of 82 MB each.
- "DLL was not loaded" is shown only when it happens in two sessions in a row, so closing a game
  in its launcher no longer raises a warning.

### Fixed

- Updates are saved to your Downloads folder as the desktop names it in your language (for
  example `~/Pobrane`), instead of always `~/Downloads`.
- The plugin's status file is written as UTF-8 whatever the system language, so a Proton folder
  with non-English letters no longer confuses the check after a Proton update.

## [1.0.0] - 2026-10-25

Initial release.

### Install

1. Download `FSR4Injector-1.0.0.zip` from this release.
2. In Gaming Mode open **Quick Access Menu → Decky → Settings**, turn on **Developer mode**, then
   choose **Developer → Install Plugin from ZIP** and select the archive.

### Use

1. Open **FSR4 Injector** and press **Accept and download**. It fetches AMD's FSR 4 library from
   AMD's official driver package (about 43 MB).
2. Turn on a game under **Games with FSR 3.1+**.
3. Start the game and choose **AMD FSR** as its upscaler. After you quit, the panel shows
   **✓ FSR4 active**, or a notification says what went wrong.
