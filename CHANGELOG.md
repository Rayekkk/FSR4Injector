# Changelog

All notable changes to FSR4 Injector, newest first.

## [1.0.1] - 2026-10-25

### Added

- **Repair FSR4 in all games:** re-checks AMD's library and puts the plugin's files and launch
  option back in every game that has FSR 4 on, for example after a game update or Steam's file
  check. If AMD's library itself is damaged or missing, it tells you to download it again first.

### Changed

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
