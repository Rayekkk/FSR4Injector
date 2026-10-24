# FSR4Injector — research (2026-10-24)

## Werdykt (po testach na Legion Go 2, 2026-10-24)

**Tak, jest nad czym pracować. Oficjalny FSR 4.1.2 Lite działa na 890M pod zwykłym Protonem 11 od Valve** (watermark `FSR4L-i8 Upscale 4.1.2`, Spider-Man Remastered i Spider-Man 2). Wymaga to jednak własnego shimu `amdxc64.dll`. Sam `FSR4_UPGRADE=1` (wniosek z wcześniejszego researchu poniżej) **nie wystarcza**.

### Wyniki testów (SteamOS 3.9.5, Mesa 26.2-devel, Proton 11.0-2e, 890M `1002:150e`)
| Wariant | Wynik (watermark) |
|---|---|
| DLL 4.1.2 obok exe + `FSR4_UPGRADE=1` (shim Valve) | **FSR3** (DLL się ładuje, ale odrzuca GPU) |
| DLL 4.1.1 (Proton Experimental) + `FSR4_UPGRADE=1` | **FSR3** |
| 4.1.2 + `amdxc64` z GE-Proton11-11 | **FSR3** |
| 4.1.2 + amdxc64 GE + **nasz hook odpowiedzi KMD** (`poc/amdxc64_proxy.c`) | **FSR4L-i8 4.1.2** ✓ |
| Podmiana DeviceID w DXVK | gra nie startuje („nie wykryto karty”) |
| Shim + 4.1.2 na **Proton Experimental** (11.0-20261014) | **FSR4L-i8 4.1.2** ✓ (nasz DLL z katalogu gry wygrywa z contrib 4.1.1) |
| Shim + 4.1.2 w **Clair Obscur: Expedition 33** (UE5, FFX SDK 2.0, upscaler 4.0.2) | **FSR4L-i8 4.1.2 PERFORMANCE** ✓ (tylko ekran tytułowy) |
| Shim + 4.1.2 w Spider-Man 2 (Nixxes) | **FSR4L-i8 4.1.2 PERFORMANCE** ✓ |

Wydajność (menu Spider-Man Remastered, 1920×1200, Quality 1.5×, FG FSR3 włączony, ~24 W, jeden przebieg na wariant):
FSR3 13,7 ms, **FSR4 Lite 14,1 ms (~-3%)**, FSR4 INT8 (model dGPU, wymuszony) 15,1 ms (~-10%). Lite daje wyraźnie ostrzejszy obraz niż FSR3, bez widocznych artefaktów.

### Dlaczego Valve/GE zostaje na FSR3 (ustalone deasemblacją DLL 2.4.0.4370)
- Każdy model ma `IsSupported(device)`. FFX sprawdza je w kolejności FP8 → INT8 → INT8 Navi2 → **INT8 Lite**.
- Lite wymaga `family == 150` (`AMDGPU_FAMILY_GC_11_5_0`, RDNA 3.5) i rewizji 1–0x3F. INT8 wymaga `family == 145` (RDNA3 dGPU) albo 150 z rewizją 0xC0–0xCF.
- `family` i rewizję DLL czyta z **prywatnych danych sterownika jądra AMD**: `gdi32!D3DKMTEnumAdapters` + `D3DKMTQueryAdapterInfo(KMTQAITYPE_UMDRIVERPRIVATE)`, offsety 0x30/0x34. Wine ich nie dostarcza, więc `family=0`, żaden model nie przechodzi i zostaje FSR3 (bez błędu i bez crasha).
- Proba w `poc/amdxc64_proxy.c` patchuje w pamięci import `GetProcAddress` w `amdxcffx64` i odpowiada prawdziwym `family=150`. Pliki AMD zostają nietknięte, podpis jest zachowany.
- Proton 11.0 stable: shim `amdxc64` bez whitelisty (tylko `FSR4_UPGRADE`), bez `contrib/amdxcffx64.dll`. Proton Experimental: whitelista dGPU i DLL 4.1.1.
- DLL 4.1.2 nie jest na CDN AMD (404). Jedyne źródło to paczka Adrenalin 26.10.1 (`Packages\Drivers\Display\WT6A_INF\B026676\`). Jest tam też **`amdvkffx64.dll` 2.4.0.4370 (FSR dla Vulkana)**.

### Co trzeba zbudować
1. Własny `amdxc64.dll` (LGPL, na bazie łatek Etaasha z GE: Device8 / CheckSupport / FFX override) + odpowiedź `UMDRIVERPRIVATE` + zapis statusu sesji (patrz wymaganie „brak cichych awarii”).
2. Plugin Decky: pozyskanie DLL z paczki AMD, kopiowanie 2 plików obok exe, opcje uruchamiania `FSR4_UPGRADE=1 WINEDLLOVERRIDES=amdxc64=n,b %command%`, rollback z manifestu, weryfikacja po każdej sesji.

### Nie sprawdzone
Forza Horizon 6 (loader FFX SDK 2.1; pominięta, bo to gra online), rozgrywka poza menu i ekranem tytułowym (do tego potrzebny jest pad), MLFG, długie sesje i stabilność, anti-cheat, dokładność pomiaru (jeden przebieg, scena menu). Shim na bazie amdxc64 z GE: w produkcie trzeba zbudować własny.

---
## Pierwotny research (sprzed testów; wniosek o samym `FSR4_UPGRADE=1` okazał się błędny)

## Fakty

### 1. Status u AMD
- 20.10.2026: Adrenalin 26.10.1 włącza FSR 4.1 m.in. dla Ryzen AI 9 (Strix Point, 890M), Strix Halo, Z2 Extreme / Z2 A (na handheldach przez sterownik OEM) i RX 6000.
- Jeden `amdxcffx64.dll` zawiera wszystkie modele: FP8 (RDNA4), INT8 (RDNA3 dGPU), RDNA2 oraz **INT8 Lite (APU)**. Model wybiera **sam DLL na podstawie GPU**. Nazwa „4.1.2 Lite” pochodzi od społeczności.
- Na razie tylko DX12. Vulkan ma przyjść w FSR SDK 2.4; na 23.10 najnowsze jest SDK 2.3.0.

### 2. Jak FSR4 działa w Protonie
- Proton przy **każdym uruchomieniu** kopiuje `contrib/amdxcffx64.dll` do `pfx/drive_c/windows/system32` (`proton`, `try_copy(... "amdxcffx64.dll" ...)`, gałąź `experimental_11.0`). Ręczna podmiana w system32 zostanie więc nadpisana.
- Wine od Valve ma własne `amdxc64.dll` (`ValveSoftware/wine`, `dlls/amdxc64/main.c`). Gra z FSR 3.1+ (FFX API) woła `UpdateFfxApiProvider`, a shim robi `LoadLibraryA("amdxcffx64")`, **tylko jeśli**:
  - zmienna `FSR4_UPGRADE` nie jest ustawiona, a GPU jest na whiteliście: `0x1002` i `0x73f0` lub `0x7440–0x749f` (tylko dyskretne Navi3x), **albo**
  - **`FSR4_UPGRADE=1`**, wtedy bez żadnego sprawdzania GPU.
- 890M (Strix Point) nie jest na whiteliście. To jest cała „blokada RDNA3.5”.
- `LoadLibraryA` najpierw przeszukuje **katalog exe gry**, dopiero potem system32. DLL położony obok exe wygrywa z kopią Protona i nie jest nadpisywany.

### 3. Dowody, że to działa na iGPU pod Linuksem
- 06.2026: na Z1 Extreme (RDNA3 iGPU) FSR 4.1.1 działa przez `FSR4_UPGRADE=1` i DLL w prefiksie/obok exe (Proton-EM). Watermark pokazuje `fsr4-i8`. Koszt to około -25% FPS względem FSR3.
- 06.2026: wyciekły DLL 4.1.1 INT8 z depotu Proton Experimental działał na 890M (zrzut z igorslab).
- 10.2026 (Stella, Bazzite, Z1E, Control, 1080p, Quality): Lite 75 FPS, INT8 64 FPS, FSR3 85 FPS. Lite jest więc około 18% szybszy od INT8 przy podobnej jakości. Lite był tam wymuszany przez OptiScaler 10-dev, bo Z1E nie jest oficjalnie wspierany. **890M jest wspierany oficjalnie, więc DLL powinien sam wybrać Lite. To trzeba potwierdzić na konsoli.**

### 4. Źródło DLL 4.1.2
- CDN AMD (`download.amd.com/dir/bin/amdxcffx64.dll/<PE timestamp><SizeOfImage>/amdxcffx64.dll`) publicznie znany jest tylko do 4.1.0. AMD już wcześniej kasowało tam wersje.
- 4.1.1: `contrib/` w Proton Experimental.
- **4.1.2**: paczka Adrenalin 26.10.1, ścieżka `Packages\Drivers\Display\WT6A_INF\B*\amdxcffx64.dll` (paczka to archiwum 7z SFX). Drugie źródło: sterownik Lenovo dla Legion Go 2, gdy się pojawi.
- Redystrybucja DLL AMD w pluginie to szara strefa licencyjna. Bezpieczniej, żeby plugin pobierał lub wyciągał plik na urządzeniu z oficjalnego źródła albo importował plik dostarczony przez użytkownika.

### 5. Istniejące narzędzia
- **Decky Framegen** (xXJSONDeruloXx, ~1.5k★): OptiScaler 0.9.4 + warianty FSR 4.1.1 (SDK, sterownik, Valve RDNA2). Nie ma ścieżki „czysty FSR4_UPGRADE bez OptiScalera” ani wersji 4.1.2 Lite.
- Proton-CachyOS i Proton-EM mają poluzowane `amdxc64`, ale na SteamOS to dodatkowy kompatybilny tool do zainstalowania.
- Valve prawdopodobnie wkrótce dopisze iGPU do whitelisty i zaktualizuje DLL w `contrib/`. Wtedy plugin w trybie natywnym stanie się zbędny, a tryb OptiScaler dalej będzie miał sens.

## Proponowany produkt (Decky)

**Tryb 1: natywny (główny cel, bez OptiScalera).** Dla gier z FSR 3.1+ / FSR4 w DX12:
1. Jednorazowo: pozyskać oficjalny DLL 4.1.2, czyli import z pliku albo pobranie i rozpakowanie paczki Adrenalin 26.10.1 (7z). Sprawdzić podpis Authenticode i wersję pliku.
2. Dla gry: znaleźć katalog exe (tam, gdzie leży `amd_fidelityfx_dx12.dll` / `amd_fidelityfx_upscaler_dx12.dll`; to zarazem wykrycie wsparcia FSR 3.1+) i skopiować do niego `amdxcffx64.dll`.
3. Ustawić `FSR4_UPGRADE=1 %command%` przez `SteamClient.Apps.SetAppLaunchOptions` oraz Proton Experimental / 11 przez `SpecifyCompatTool`.
4. Cofnięcie: usunąć DLL i zmienną. Usuwamy tylko to, co plugin dodał.

Zaletą jest to, że w grze działa oficjalny, podpisany DLL AMD, który sam wybiera model, wpięty oficjalną ścieżką FFX API. Żadnych hooków.

**Tryb 2: bonus dla FSR2 / FSR3.0 / DLSS / XeSS → FSR4.** Bez wstrzykiwania się nie obejdzie, bo te gry nie korzystają z FFX API. Tu potrzebny jest OptiScaler (który umie użyć `amdxcffx64.dll` jako providera „driver”) z naszym DLL 4.1.2. Albo integracja z Decky Framegen, albo własny, minimalny wariant.

## Ryzyka i niewiadome (do testu na konsoli przed pisaniem kodu)
1. Czy DLL 4.1.2 z Adrenalin 26.10.1 ładuje się pod shimem Valve `amdxc64` (mogą być wymagane nowe interfejsy)? Pośrednio tak, bo OptiScaler 10-dev uruchamiał Lite pod Protonem. Ścieżka przez shim nie jest jednak potwierdzona.
2. Czy pod Linuksem DLL wybiera Lite dla 890M (vkd3d raporuje prawdziwe PCI ID)? Do sprawdzenia watermarkiem i FPS.
3. Czy dxil-spirv i RADV (gfx1150) poprawnie tłumaczą shadery Lite (artefakty, czarny ekran)?
4. Anti-cheat: obcy DLL w katalogu gry może wywołać reakcję w grach MP (podpis AMD pomaga, ale gwarancji nie ma).
5. Tylko DX12. Vulkan dopiero po SDK 2.4.

## Test walidacyjny (ręczny, ~30 min)
1. Na PC rozpakować `amdxcffx64.dll` z Adrenalin 26.10.1 (7-Zip).
2. Skopiować go na Legion Go 2 obok exe gry z FSR 3.1 (np. Cyberpunk 2077 `bin/x64`).
3. Gra na Proton Experimental, launch options: `FSR4_UPGRADE=1 PROTON_LOG=1 %command%`.
4. W grze włączyć FSR 3.1/4. Sprawdzić w `steam-<appid>.log` linię `Replaced FSR3 with FSR4!`, watermark lub wygląd obrazu i FPS względem FSR3 i DLL 4.1.1.

## Źródła
- Valve wine `dlls/amdxc64/main.c` (experimental_11.0): https://github.com/ValveSoftware/wine/blob/experimental_11.0/dlls/amdxc64/main.c
- Proton `proton` script (experimental_11.0): https://github.com/ValveSoftware/Proton/blob/experimental_11.0/proton
- https://www.gamingonlinux.com/2026/10/amd-fsr-upscaling-4-1-expands-support-to-older-desktops-laptops-handhelds-consoles-and-vulkan/
- https://framesgames.com/fsr-4-1-2-lite/
- https://github.com/dumbie/Contact/issues/88
- https://www.gamingonlinux.com/2026/06/amd-fsr-4-lands-on-rdna3-dgpus-for-linux-steamos-and-steam-machine-via-proton-experimental/
- https://www.gamingonlinux.com/2026/07/proton-cachyos-version-11-0-20260702-brings-amd-fsr4-upgrades-pipewire-changes/
- https://en.gamegpu.com/news/zhelezo/opublikovan-metod-obkhoda-ogranichenij-amd-dlya-zapuska-fsr-4-1-1-na-linux
- https://www.igorslab.de/en/valve-fsr-4-1-proton-experimental-rdna-3-3-5/
- https://discuss.cachyos.org/t/fsr-4-1-dll-is-now-available-in-amd-official-website/24604
- https://github.com/loathingKernel/proton-upscalers
- https://github.com/xXJSONDeruloXx/Decky-Framegen
