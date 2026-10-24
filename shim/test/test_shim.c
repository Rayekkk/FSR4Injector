/* Self-test for the amdxc64 shim. Runs natively on Windows (no AMD GPU needed):
 *   test_shim.exe <path to amdxcffx64.dll>
 * The AMD DLL is mapped as an image without running its code. */
#include <initguid.h>
#include "../src/amd_ext.h"
#include "../src/fsr4i.h"
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

int main(int argc, char **argv)
{
    UINT family = 0, rev = 0;
    char status_path[MAX_PATH], env[MAX_PATH + 16], *json;

    if (argc < 2) { printf("usage: %s <amdxcffx64.dll>\n", argv[0]); return 2; }

    /* status file goes where FSR4I_STATUS says */
    GetTempPathA(MAX_PATH, status_path);
    strcat(status_path, "fsr4i_test_status.json");
    DeleteFileA(status_path);
    snprintf(env, sizeof(env), "FSR4I_STATUS=%s", status_path);
    _putenv(env);

    /* loading alone marks the session, with the Proton dir Steam passed (first entry, JSON-escaped) */
    _putenv("STEAM_COMPAT_TOOL_PATHS=/home/deck/Proton \"11\"\\x:/second");
    fsr4i_init(GetModuleHandleW(NULL));
    json = read_file(status_path);
    CHECK(json && strstr(json, "\"ffx_requested\":false") && strstr(json, "\"started\":\"20"));
    CHECK(json && strstr(json, "\"compat_tool\":\"/home/deck/Proton \\\"11\\\"\\\\x\""));

    /* GPU table: only verified RDNA 3.5 parts get an answer */
    CHECK(fsr4i_lookup_family(0x1002, 0x150e, &family, &rev) && family == 150 && rev == 20);
    CHECK(!fsr4i_lookup_family(0x1002, 0x744c, &family, &rev)); /* RDNA3 dGPU: real driver data not ours to invent */
    CHECK(!fsr4i_lookup_family(0x10de, 0x150e, &family, &rev));

    /* explicit override path makes the KMD answer available without an AMD GPU */
    _putenv("FSR4I_FAMILY=150");
    _putenv("FSR4I_REV=0x1");
    LUID luid = {0};
    fsr4i_on_ffx_request(luid);
    BYTE blob[0x260];
    memset(blob, 0xcc, sizeof(blob));
    QUERYADAPTERINFO q = { 1, 0 /* UMDRIVERPRIVATE */, blob, sizeof(blob) };
    CHECK(fsr4i_fake_query_adapter_info(&q) == 0);
    CHECK(*(UINT *)(blob + 0x30) == 150 && *(UINT *)(blob + 0x34) == 1 && blob[0] == 0);
    QUERYADAPTERINFO small = { 1, 0, blob, 0x20 }; /* too small: not ours to answer */
    CHECK(fsr4i_fake_query_adapter_info(&small) != 0);

    /* real AMD DLL: imports and all four FSR4 model providers must be found */
    HMODULE ffx = LoadLibraryExA(argv[1], NULL, DONT_RESOLVE_DLL_REFERENCES);
    CHECK(ffx != NULL);
    if (ffx)
    {
        DWORD t = GetTickCount();
        fsr4i_on_ffx_loaded(ffx);
        printf("hooking took %lu ms\n", GetTickCount() - t);
        json = read_file(status_path);
        CHECK(json != NULL);
        if (json)
        {
            printf("status: %s", json);
            CHECK(strstr(json, "\"iat_patched\":true") != NULL);
            CHECK(strstr(json, "\"model_hooks\":4") != NULL);
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

    DeleteFileA(status_path);
    printf(failures ? "%d FAILED\n" : "all passed\n", failures);
    return failures != 0;
}
