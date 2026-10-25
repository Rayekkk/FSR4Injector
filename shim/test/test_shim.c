/* Self-test for the amdxc64 shim. Runs natively on Windows (no AMD GPU needed):
 *   test_shim.exe <path to amdxcffx64.dll>
 * The AMD DLL is mapped as an image without running its code. */
#include <initguid.h>
#include "../src/amd_ext.h"
#include "../src/fsr4i.h"
#include <process.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

HRESULT __cdecl AmdExtD3DCreateInterface(IUnknown *outer, REFIID iid, void **obj);

static int failures;
#define CHECK(c) do { if (!(c)) { printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); failures++; } } while (0)

typedef struct { UINT hAdapter; UINT Type; void *pPrivateDriverData; UINT PrivateDriverDataSize; } QUERYADAPTERINFO;

static char *read_file(const char *path)
{
    FILE *f = fopen(path, "rb");
    static char buf[2048];
    size_t n;
    if (!f) return NULL;
    n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    buf[n] = 0;
    return buf;
}

/* Child process: any module named amdxcffx64.dll that someone else loads (OptiScaler does) must reach the shim
 * through the loader notification. A copy of a harmless system DLL stands in, as running AMD's code needs its GPU. */
static int loader_notification_child(const char *status_path)
{
    char env[MAX_PATH + 16], src[MAX_PATH], dir[MAX_PATH], dst[MAX_PATH];
    snprintf(env, sizeof(env), "FSR4I_STATUS=%s", status_path);
    _putenv(env);
    fsr4i_init(GetModuleHandleW(NULL));
    GetSystemDirectoryA(src, MAX_PATH);
    strcat(src, "\\version.dll");
    GetTempPathA(MAX_PATH, dir);
    strcat(dir, "fsr4i_notify");
    CreateDirectoryA(dir, NULL);
    snprintf(dst, sizeof(dst), "%s\\amdxcffx64.dll", dir);
    if (!CopyFileA(src, dst, FALSE)) return 3;
    HMODULE m = LoadLibraryA(dst);
    char *json = read_file(status_path);
    /* loaded and given the GPU answer, but a build we do not know gets no model hooks */
    int ok = m && json && strstr(json, "\"dll_loaded\":true") && strstr(json, "\"model_hooks\":0") &&
             !strstr(json, "\"ffx_version\":\"2.4.0.4370\"");
    if (!ok) printf("child status: %s\n", json ? json : "(none)");
    /* pinned by the shim, so the copy stays locked until we exit; the parent removes it */
    return ok ? 0 : 1;
}

int main(int argc, char **argv)
{
    UINT family = 0, rev = 0;
    char status_path[MAX_PATH], env[MAX_PATH + 16], *json;

    if (argc == 3 && !strcmp(argv[1], "--loader-notification")) return loader_notification_child(argv[2]);
    if (argc < 2) { printf("usage: %s <amdxcffx64.dll>\n", argv[0]); return 2; }

    /* status file goes where FSR4I_STATUS says */
    GetTempPathA(MAX_PATH, status_path);
    strcat(status_path, "fsr4i_test_status.json");
    DeleteFileA(status_path);
    snprintf(env, sizeof(env), "FSR4I_STATUS=%s", status_path);
    _putenv(env);

    /* loading alone marks the session, with the Proton dir Steam passed (first entry, JSON-escaped) */
    _wputenv(L"STEAM_COMPAT_TOOL_PATHS=/home/deck/Proton \"11\"\\x \u017b\u00f3\u0142w:/second"); /* "Żółw" */
    fsr4i_init(GetModuleHandleW(NULL));
    json = read_file(status_path);
    CHECK(json && strstr(json, "\"ffx_requested\":false") && strstr(json, "\"started\":\"20"));
    /* written as UTF-8 whatever code page Wine uses for the system language */
    CHECK(json && strstr(json, "\"compat_tool\":\"/home/deck/Proton \\\"11\\\"\\\\x \xc5\xbb\xc3\xb3\xc5\x82w\""));

    /* GPU table: only verified RDNA 3.5 parts get an answer */
    CHECK(fsr4i_lookup_family(0x1002, 0x150e, &family, &rev) && family == 150 && rev == 20);
    CHECK(!fsr4i_lookup_family(0x1002, 0x744c, &family, &rev)); /* RDNA3 dGPU: real driver data not ours to invent */
    CHECK(!fsr4i_lookup_family(0x10de, 0x150e, &family, &rev));

    /* values from the plugin's file win over the table, but only for the GPU they describe */
    WCHAR gpu_path[MAX_PATH];
    CHECK(fsr4i_module_path(L"fsr4injector.gpu", gpu_path, MAX_PATH));
    FILE *g = _wfopen(gpu_path, L"w");
    fprintf(g, "5695 144 3\n"); /* 0x163f Van Gogh */
    fclose(g);
    CHECK(fsr4i_lookup_family(0x1002, 0x163f, &family, &rev) && family == 144 && rev == 3);
    CHECK(fsr4i_lookup_family(0x1002, 0x150e, &family, &rev) && family == 150 && rev == 20); /* file is for 0x163f */
    CHECK(!fsr4i_lookup_family(0x1002, 0x744c, &family, &rev));
    _wremove(gpu_path);

    /* explicit override path makes the KMD answer available without an AMD GPU. No fsr4i_on_ffx_request first:
     * like under OptiScaler, the first driver query has to look the GPU up itself. */
    _putenv("FSR4I_FAMILY=150");
    _putenv("FSR4I_REV=0x1");
    BYTE blob[0x260];
    memset(blob, 0xcc, sizeof(blob));
    QUERYADAPTERINFO q = { 1, 0 /* UMDRIVERPRIVATE */, blob, sizeof(blob) };
    CHECK(fsr4i_fake_query_adapter_info(&q) == 0);
    CHECK(*(UINT *)(blob + 0x30) == 150 && *(UINT *)(blob + 0x34) == 1 && blob[0] == 0);
    QUERYADAPTERINFO small = { 1, 0, blob, 0x20 }; /* too small: not ours to answer */
    CHECK(fsr4i_fake_query_adapter_info(&small) != 0);
    json = read_file(status_path);
    CHECK(json && strstr(json, "\"ffx_requested\":true"));

    /* FP8 only where the hardware has it (family 152), whatever another tool's Device8 claims */
    CHECK(fsr4i_model_allowed(0, 1) == 0 && fsr4i_model_allowed(3, 1) == 1 && fsr4i_model_allowed(0, 0) == 0);
    _putenv("DXIL_SPIRV_CONFIG=wmma_rdna3_workaround"); /* deliberate FP8 emulation stays possible */
    CHECK(fsr4i_model_allowed(0, 1) == 1);
    _putenv("DXIL_SPIRV_CONFIG=");

    /* real AMD DLL: imports and all four FSR4 model providers must be found */
    HMODULE ffx = LoadLibraryExA(argv[1], NULL, DONT_RESOLVE_DLL_REFERENCES);
    CHECK(ffx != NULL);
    if (ffx)
    {
        DWORD t = GetTickCount();
        fsr4i_on_ffx_loaded(ffx); /* the loader skips notifications for DONT_RESOLVE_DLL_REFERENCES; see below */
        printf("hooking took %lu ms\n", GetTickCount() - t);
        json = read_file(status_path);
        CHECK(json != NULL);
        if (json)
        {
            printf("status: %s", json);
            CHECK(strstr(json, "\"dll_loaded\":true") != NULL);
            CHECK(strstr(json, "\"iat_patched\":true") != NULL);
            CHECK(strstr(json, "\"model_hooks\":4") != NULL);
            CHECK(strstr(json, "\"ffx_version\":\"2.4.0.4370\"") != NULL); /* the build the hooks are made for */
            CHECK(strstr(json, "\"kmd_answered\":true") != NULL);
            CHECK(strstr(json, "\"family\":150") != NULL);
            CHECK(strstr(json, "\"active\":null") != NULL); /* no model asked yet */
        }
    }

    /* AMD extension objects */
    AmdObj *factory = NULL;
    CHECK(AmdExtD3DCreateInterface(NULL, &IID_IAmdExtD3DFactory, (void **)&factory) == S_OK && factory);
    if (factory)
    {
        AmdObj *dev8 = NULL;
        IAmdExtD3DFactoryVtbl *fv = factory->vtbl;
        CHECK(fv->CreateInterface(factory, NULL, &IID_IAmdExtD3DDevice8, (void **)&dev8) == S_OK && dev8);
        if (dev8)
        {
            IAmdExtD3DDevice8Vtbl *dv = dev8->vtbl;
            SIZE_T count = 4;
            AmdExtWaveMatrixProperties props[4];
            CHECK(dv->GetWaveMatrixProperties(dev8, &count, props) == S_OK && count == 0); /* no FP8 without vkd3d */
            CHECK(((HRESULT (STDMETHODCALLTYPE *)(void))dv->unimplemented[5])() == E_NOTIMPL);
            dv->Release(dev8);
        }
        void *unknown = (void *)1;
        CHECK(fv->CreateInterface(factory, NULL, &IID_IAmdExtD3DDevice1, &unknown) == E_NOINTERFACE && !unknown);
    }
    void *nothing = (void *)1;
    CHECK(AmdExtD3DCreateInterface(NULL, &IID_ID3D12DeviceExt3, &nothing) == E_NOINTERFACE && !nothing);

    /* loader notification, in a fresh process (this one already hooked the AMD DLL) */
    char exe[MAX_PATH], quoted[MAX_PATH + 2], child_status[MAX_PATH], copy[MAX_PATH];
    GetModuleFileNameA(NULL, exe, MAX_PATH);
    snprintf(quoted, sizeof(quoted), "\"%s\"", exe);
    GetTempPathA(MAX_PATH, child_status);
    strcat(child_status, "fsr4i_test_child.json");
    CHECK(_spawnl(_P_WAIT, exe, quoted, "--loader-notification", child_status, NULL) == 0);
    GetTempPathA(MAX_PATH, copy);
    strcat(copy, "fsr4i_notify\\amdxcffx64.dll");
    DeleteFileA(copy);
    DeleteFileA(child_status);

    DeleteFileA(status_path);
    printf(failures ? "%d FAILED\n" : "all passed\n", failures);
    return failures != 0;
}
