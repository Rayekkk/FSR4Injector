# FSR4Injector: plan budowy

Cel: plugin Decky, który po kliknięciu sam włącza oficjalny FSR 4.1.2 (model Lite) w grach DX12 z FSR 3.1+, pilnuje działania po aktualizacjach i potrafi wszystko cofnąć.

## Stan (2026-10-24)

| Element | Stan |
|---|---|
| Diagnoza: dlaczego Proton zostaje na FSR3 | ✓ (RESEARCH.md) |
| Pozyskanie DLL AMD bez redystrybucji: 43 MiB z oficjalnej paczki | ✓ prototyp (`tools/find_recipe.py`), przepis dla 26.10.1 |
| Shim `amdxc64.dll` 0.1.0 (`shim/`) | ✓ zbudowany, samotest na Windows przechodzi; **nie testowany na konsoli** |
| Plugin Decky 0.1.0: szkielet | ✓ backend (`fsr4_dll`, `fsr4_games`, `fsr4_install`, `main.py`), 18 testów `npm test`, panel QAM (`src/index.tsx`) się buduje; prawdziwe pobranie z AMD na PC: 3 s, sha OK; **nie uruchamiany w Decky** |

### Test na konsoli 2026-10-24 (Legion Go 2, SteamOS 3.9.5, Decky 3.3.0, Proton 11) ✓
- Instalacja zipa przez instalator Decky (`utilities/install_plugin` + `confirm_plugin_install`, bez sudo).
- Python Decky ma `lzma`, ale **nie ma magazynu CA**: naprawione (`certifi` z Decky → `/etc/ssl/certs/ca-certificates.crt`). Pobranie DLL w pluginie ~2 s, sha OK.
- Skan: 7 gier z FFX (w tym E33 → `Sandfall/Binaries/Win64`).
- Spider-Man przez ścieżkę panelu: status `INT8_LITE`, provider 4.1.2, werdykt `ok`, bez toastu.
- **`WINEDLLOVERRIDES=amdxc64=n,b` jest wymagane** (bez niego Wine bierze wbudowany amdxc64 i shim się nie ładuje).
- Brak cichych awarii: (B) inny plugin usuwa nasz token → wykryte przez znacznik sesji z dokładną przyczyną; (C) DLL odrzuca FSR4 → toast „FSR4 not active” widoczny w Steamie.
- **Aktualizacja pluginu w Decky = uninstall + install** (wywołuje `_uninstall`): `_uninstall` nie rusza już gier; przycisk „Remove from all games”; aktualizacja zachowuje pliki, manifest i DLL.
- Wyłączenie: pliki usunięte, opcje wracają dokładnie (`~/.dlo/run %command%` od decky-launch-options).
- Prawdziwe wartości 890M z `RADV_DEBUG=info`: `family_id 150`, `chip_external_rev 20` → tabela shimu, Lite potwierdzony.

### Pierwotna lista do sprawdzenia
- Czy Python Decky (zamrożony PyInstallerem) ma moduł `lzma`. Jeśli nie, potrzebny plan B do dekodowania (np. dołączony statyczny `xz`).
- Panel: czy `SteamClient.Apps.RegisterForAppDetails` zwraca `strLaunchOptions`, a `SetAppLaunchOptions` i `RegisterForAppLifetimeNotifications` działają w tej wersji Steama.
- Pełny przebieg w Spider-Man: przycisk w panelu → watermark `FSR4L-i8` → po wyjściu z gry brak alarmu; potem zepsucie celowe (np. `FSR4I_FAMILY=1 FSR4I_REV=1`) → toast „FSR4 not active”.

### Paczka
`npm run package` → `FSR4Injector-<wersja>.zip` (powtarzalny). Skrypt sprawdza gotowe archiwum: wymagane pliki (w tym źródło shimu i LGPL), brak plików AMD (`amdxcffx64*`, `amdvkffx64*`), brak `.exe` i cache. README i NOTICE gotowe.

### Zrobione później (2026-10-24)
Ikona (plakietka „4”), wykrywanie zmian SteamOS/Protona („↻ Re-check needed” + powiadomienie po aktualizacji SteamOS, sprawdzone na konsoli), odświeżanie shimu w grach po aktualizacji pluginu, panel bez spinnera przy ponownym otwarciu i z informacją zwrotną „Rescan library”, test panelu (`tests/frontend_panel.cjs`), repo w stylu Companionów, CI tylko z testami.

### Dalej
- **FSR4 dla gier bez FSR 3.1** (FSR 2 / 3.0 / DLSS / XeSS): przez OptiScaler z naszym DLL 4.1.2 jako providerem; plan i zgoda przed budową.
- Grafika repo (`FSR4Injector.png`) i zrzuty do `docs/screenshots/` – od autora.
- Sprawdzanie aktualizacji pluginu z panelu (jak w Companionach).

## Shim (`shim/`, LGPL-2.1+)
- Port `dlls/amdxc64` z GE-Proton11-11 (Etaash Mathamsetty): FfxApi (UpdateFfxApiProvider[Ex]), Factory, Device8, ShaderIntrinsics (przez vkd3d `ID3D12DeviceExt3`), CreateDevice, AntiLag, watermark.
- Dodatki: `amdxcffx64.dll` ładowany z katalogu shimu; odpowiedź `D3DKMTQueryAdapterInfo(UMDRIVERPRIVATE)` z tabeli PCI ID → family/rev (na razie tylko `1002:150e` → 150/1; zmienne `FSR4I_FAMILY`/`FSR4I_REV` do testów); obserwacja `IsSupported` 4 modeli przez RTTI; status w `fsr4injector.status.json` obok DLL (albo `FSR4I_STATUS`), zapis atomowy i tylko przy zmianie.
- `FSR4_UPGRADE=0` wyłącza na jedno uruchomienie.
- Build: `shim/build.sh [amdxcffx64.dll]` (MinGW-w64; tu: Strawberry Perl gcc 13.2).

## Testy na konsoli (gdy Legion wolny)
1. Shim zamiast proby w Spider-Man Remastered: watermark `FSR4L-i8`, status `"active":"INT8_LITE"`, `"kmd_answered":true`.
2. To samo **bez** `WINEDLLOVERRIDES=amdxc64=n,b`: jeśli Wine sam wybierze nasz DLL, plugin nie musi w ogóle zmieniać opcji uruchamiania.
3. `FSR4_UPGRADE=0` → FSR3 i status bez `dll_loaded`.
4. Expedition 33 (SDK 2.x, zapytania co klatkę): brak spadku wydajności przez shim, status zapisany raz.
5. Prawdziwe family/rev 890M: `RADV_DEBUG=info vulkaninfo` (lub `AMD_DEBUG=info`), żeby tabela nie opierała się na założeniu rev=1.

## Plugin Decky (do zbudowania)
Backend Python (bez roota) + panel QAM (React), wzorem DeckyVibranceHDR / LegionGo2Companion.

1. **Pozyskanie DLL**: ekran z informacją o licencji AMD → przycisk „Pobierz z AMD” → ranged download wg przepisu (URL, Referer, offsety, sha256) → dekodowanie LZMA2+BCJ (`lzma` ze stdlib) → zapis w katalogu danych pluginu. Przy złym hashu nic nie zapisujemy.
2. **Wykrywanie gier**: `libraryfolders.vdf` + `appmanifest_*.acf`, w katalogu gry szukamy `amd_fidelityfx_dx12.dll` / `amd_fidelityfx_upscaler_dx12.dll` / `amd_fidelityfx_loader_dx12.dll` → katalog docelowy. Foldery EAC/BattlEye → ostrzeżenie i domyślnie blokada.
3. **Włączenie**: kopiujemy `amdxc64.dll` + `amdxcffx64.dll` (nigdy nie nadpisujemy cudzych plików), ewentualnie opcje uruchamiania przez `SteamClient.Apps.SetAppLaunchOptions` (zależnie od testu 2). Manifest: pliki + sha256, oryginalne opcje.
4. **Wyłączenie / rollback**: usuwamy tylko pliki o zgodnym hashu i tylko nasze tokeny w opcjach; „Usuń wszystko”; sprzątanie przy odinstalowaniu pluginu.
5. **Brak cichych awarii**: po zakończeniu gry odczyt statusu → toast: ✓ FSR4 Lite / ℹ gra nie użyła FSR / ⚠ FSR4 odrzucony (z przyczyną). Zapamiętujemy zweryfikowaną kombinację (BUILD_ID SteamOS, wersja Protona z `compatdata/<id>/version`, sha DLL, wersja shimu); po zmianie oznaczamy „niezweryfikowane po aktualizacji”.
6. **Później**: tryb OptiScaler dla gier bez FSR 3.1, Vulkan (`amdvkffx64.dll` z tej samej paczki), kolejne przepisy dla nowych sterowników AMD i sprawdzanie CDN / FidelityFX SDK 2.4 (MIT).
