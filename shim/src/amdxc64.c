/*
 * amdxc64 replacement for FSR4Injector: AMD D3D12 driver extensions for amdxcffx64.dll under Proton.
 *
 * Ported from GE-Proton's dlls/amdxc64/main.c (GE-Proton11-11):
 * Copyright 2023 Etaash Mathamsetty
 * FSR4Injector changes (standalone MinGW build, own-directory amdxcffx64 load, fsr4i hooks):
 * Copyright 2026 FSR4Injector contributors
 *
 * This library is free software; you can redistribute it and/or modify it under the terms of the GNU Lesser
 * General Public License as published by the Free Software Foundation; either version 2.1 of the License, or
 * (at your option) any later version. See COPYING.LIB.
 */
#include <initguid.h>
#include "amd_ext.h"
#include "fsr4i.h"
#include <stdlib.h>
#include <string.h>

/* ---- vkd3d-proton capability queries ---- */

static BOOL supports_ags(IUnknown *ext, int ags)
{
    void **vtbl = *(void ***)ext;
    return ((BOOL (STDMETHODCALLTYPE *)(IUnknown *, int))vtbl[DEVICEEXT3_SUPPORTS_AGS_SLOT])(ext, ags);
}

static void check_intrinsic_support(IUnknown *device, BOOL *fp8, BOOL *p_wmma, ULONG *intrinsics)
{
    IUnknown *ext;
    const char *e;
    BOOL wmma;

    if (!device || FAILED(device->lpVtbl->QueryInterface(device, &IID_ID3D12DeviceExt3, (void **)&ext))) return;

    wmma = supports_ags(ext, AGS_WMMA_FP8);
    *fp8 = supports_ags(ext, AGS_WMMA_FP8_NATIVE);
    if ((e = getenv("DXIL_SPIRV_CONFIG")) && !strcmp(e, "wmma_rdna3_workaround")) *fp8 = wmma;
    if (p_wmma) *p_wmma = wmma;

    for (int i = AGS_INTRINSICS_16; intrinsics && i <= AGS_SHADER_CLOCK; i++)
        if (supports_ags(ext, i)) *intrinsics |= 1u << i;

    ext->lpVtbl->Release(ext);
}

static HRESULT STDMETHODCALLTYPE no_interface(void *iface, REFIID iid, void **out)
{
    if (out) *out = NULL;
    return E_NOINTERFACE;
}

static ULONG STDMETHODCALLTYPE static_addref(void *iface) { return 2; }
static ULONG STDMETHODCALLTYPE static_release(void *iface) { return 1; }

/* Refcounted heap objects: vtable pointer first, then the count. */
typedef struct { void *vtbl; LONG ref; } RefObj;

static ULONG STDMETHODCALLTYPE obj_addref(void *iface) { return InterlockedIncrement(&((RefObj *)iface)->ref); }

static ULONG STDMETHODCALLTYPE obj_release(void *iface)
{
    ULONG ret = InterlockedDecrement(&((RefObj *)iface)->ref);
    if (!ret) free(iface);
    return ret;
}

/* ---- IAmdExtFfxApi: hands the game's FidelityFX API over to amdxcffx64 ---- */

typedef struct
{
    void *vtbl;
    LONG ref;
    BOOL fp8_supported;
    LUID luid;
} FfxApi;

/* SDK 2.0.0 and older */
typedef HRESULT (__stdcall *updateffxapi_pfn)(void *, unsigned int);
/* SDK 2.1.0 and newer */
typedef HRESULT (__stdcall *updateffxapi_pfn_ex)(void *, unsigned int, void *);

struct ffxExternalProvider
{
    ULONG structVersion;     /* 0x0 */
    ULONG64 descType;        /* 0x8 */
    ULONG64 versionId;       /* 0x10 */
    const char *versionName; /* 0x18 */
};

struct unk_data
{
    int unk[4];
    struct unk_data *next;
};

static HMODULE load_amdxcffx64(void)
{
    static HMODULE mod;
    WCHAR path[MAX_PATH];

    if (mod) return mod;
    if (!fsr4i_module_path(L"amdxcffx64.dll", path, MAX_PATH)) return NULL;
    /* Load ours by full path: Proton Experimental also puts an older copy into system32. */
    mod = LoadLibraryW(path);
    if (mod) fsr4i_on_ffx_loaded(mod);
    return mod;
}

static HRESULT STDMETHODCALLTYPE ffx_update_provider(void *iface, void *_data, unsigned int size)
{
    FfxApi *this = iface;
    struct ffxExternalProvider *data = _data;
    /* required to expose MLFG support */
    struct unk_data unk_data[1] = {{{0, 1, 0, 0}, NULL}};
    const char *env;
    updateffxapi_pfn_ex pfn_ex;
    updateffxapi_pfn pfn;
    HMODULE amdffx;
    HRESULT ret;

    if (!data) return E_INVALIDARG;

    env = getenv("MLFG_UPGRADE");
    if (this->fp8_supported || (env && !strcmp(env, "1")))
        unk_data->unk[2] = !env || strcmp(env, "0");

    /* Installed means enabled; FSR4_UPGRADE=0 is the per-launch kill switch. */
    if ((env = getenv("FSR4_UPGRADE")) && !strcmp(env, "0")) return E_NOTIMPL;

    fsr4i_on_ffx_request(this->luid);

    if (!(amdffx = load_amdxcffx64()))
    {
        fsr4i_log("amdxcffx64.dll not found next to amdxc64.dll");
        return E_NOINTERFACE;
    }

    pfn_ex = (updateffxapi_pfn_ex)GetProcAddress(amdffx, "UpdateFfxApiProviderEx");
    pfn = (updateffxapi_pfn)GetProcAddress(amdffx, "UpdateFfxApiProvider");

    if (pfn_ex)
        ret = pfn_ex(data, size, unk_data);
    else if (pfn && this->fp8_supported) /* legacy amdxcffx64 only ships the FP8 model */
        ret = pfn(data, size);
    else
        return E_NOINTERFACE;

    fsr4i_on_provider(ret, ret == S_OK ? data->versionName : NULL);
    return ret;
}

static const IAmdExtFfxApiVtbl ffx_vtbl = { no_interface, obj_addref, obj_release, ffx_update_provider };

/* ---- IAmdExtD3DShaderIntrinsics ---- */

typedef struct
{
    void *vtbl;
    LONG ref;
    BOOL supports_wmma, supports_fp8;
    ULONG intrinsics;
} ShaderIntrinsics;

static HRESULT STDMETHODCALLTYPE intr_get_info(void *iface, void *info) { return S_OK; }

static HRESULT STDMETHODCALLTYPE intr_check_support(void *iface, UINT op)
{
    ShaderIntrinsics *this = iface;
    ULONG in = this->intrinsics;

    if (op == Intr_Float8Conversion) return this->supports_fp8 ? S_OK : E_NOTIMPL;
    if (op == Intr_WaveMatrix) return this->supports_wmma ? S_OK : E_NOTIMPL;
    if (op >= Intr_Readfirstlane && op <= Intr_Barycentrics) return in & (1u << AGS_INTRINSICS_16) ? S_OK : E_NOTIMPL;
    if (op >= Intr_WaveReduce && op <= Intr_WaveScan) return in & (1u << AGS_INTRINSICS_17) ? S_OK : E_NOTIMPL;
    if (op >= Intr_DrawIndex && op <= Intr_AtomicU64) return in & (1u << AGS_INTRINSICS_19) ? S_OK : E_NOTIMPL;
    if (op >= Intr_ShaderClock && op <= Intr_ShaderRealtimeClock) return in & (1u << AGS_SHADER_CLOCK) ? S_OK : E_NOTIMPL;
    if (op == Intr_BaseInstance) return in & (1u << AGS_BASE_INSTANCE) ? S_OK : E_NOTIMPL;
    if (op == Intr_BaseVertex) return in & (1u << AGS_BASE_VERTEX) ? S_OK : E_NOTIMPL;
    if (op == Intr_GetWaveSize) return in & (1u << AGS_GET_WAVE_SIZE) ? S_OK : E_NOTIMPL;
    if (op == Intr_FloatConversion) return in & (1u << AGS_FLOAT_CONVERSION) ? S_OK : E_NOTIMPL;
    if (op == Intr_ReadlaneAt) return in & (1u << AGS_READ_LANE_AT) ? S_OK : E_NOTIMPL;
    if (op == Intr_RayTraceHitToken) return in & (1u << AGS_RAY_HIT_TOKEN) ? S_OK : E_NOTIMPL;
    return E_NOTIMPL;
}

/* shader intrinsics are always handled by vkd3d-proton */
static HRESULT STDMETHODCALLTYPE intr_enable(void *iface) { return S_OK; }

static const IAmdExtD3DShaderIntrinsicsVtbl intr_vtbl =
    { no_interface, obj_addref, obj_release, intr_get_info, intr_check_support, intr_enable };

/* ---- IAmdExtD3DDevice8: only GetWaveMatrixProperties matters to FSR4 ---- */

typedef struct
{
    void *vtbl;
    LONG ref;
    BOOL fp8_supported;
} Device8;

/* x64 has one calling convention, so one stub serves every unimplemented method. */
static HRESULT STDMETHODCALLTYPE dev8_unimplemented(void) { return E_NOTIMPL; }

static HRESULT STDMETHODCALLTYPE dev8_wave_matrix_props(void *iface, SIZE_T *count, AmdExtWaveMatrixProperties *props)
{
    static const AmdExtWaveMatrixProperties fp8 =
        { 16, 16, 16, AMD_EXT_WMMA_TYPE_FP8, AMD_EXT_WMMA_TYPE_FP8, AMD_EXT_WMMA_TYPE_FP32, AMD_EXT_WMMA_TYPE_FP32, FALSE };

    if (!count) return E_INVALIDARG;
    if (!((Device8 *)iface)->fp8_supported)
    {
        *count = 0;
        return S_OK;
    }
    if (*count < 1) return E_NOT_SUFFICIENT_BUFFER;
    *count = 1;
    props[0] = fp8;
    return S_OK;
}

static const IAmdExtD3DDevice8Vtbl dev8_vtbl =
    { no_interface, obj_addref, obj_release, { [0 ... 12] = (void *)dev8_unimplemented }, dev8_wave_matrix_props };

/* ---- IAmdExtD3DFactory (singleton) ---- */

static HRESULT STDMETHODCALLTYPE factory_create(void *iface, IUnknown *outer, REFIID iid, void **out)
{
    if (!out) return E_INVALIDARG;
    *out = NULL;

    if (IsEqualGUID(iid, &IID_IAmdExtD3DShaderIntrinsics))
    {
        ShaderIntrinsics *o = calloc(1, sizeof(*o));
        if (!o) return E_OUTOFMEMORY;
        o->vtbl = (void *)&intr_vtbl;
        o->ref = 1;
        check_intrinsic_support(outer, &o->supports_fp8, &o->supports_wmma, &o->intrinsics);
        *out = o;
        return S_OK;
    }
    if (IsEqualGUID(iid, &IID_IAmdExtD3DDevice8))
    {
        Device8 *o = calloc(1, sizeof(*o));
        if (!o) return E_OUTOFMEMORY;
        o->vtbl = (void *)&dev8_vtbl;
        o->ref = 1;
        check_intrinsic_support(outer, &o->fp8_supported, NULL, NULL);
        *out = o;
        return S_OK;
    }
    return E_NOINTERFACE;
}

static const IAmdExtD3DFactoryVtbl factory_vtbl = { no_interface, static_addref, static_release, factory_create };
static const AmdObj factory = { (void *)&factory_vtbl };

/* ---- IAmdExtD3DCreateDevice (singleton) ---- */

typedef HRESULT (WINAPI *create_device_fn)(IUnknown *, D3D_FEATURE_LEVEL, REFIID, void **);

static HRESULT STDMETHODCALLTYPE create_device(void *iface, IUnknown *adapter, D3D_FEATURE_LEVEL min_level,
                                               REFIID iid, void **device, AmdExtD3DCreateDeviceInfo *ext)
{
    HMODULE d3d12 = LoadLibraryW(L"d3d12.dll");
    create_device_fn fn;
    HRESULT ret = E_FAIL;

    if (!d3d12) return E_FAIL;
    if ((fn = (create_device_fn)GetProcAddress(d3d12, "D3D12CreateDevice")))
        ret = fn(adapter, min_level, iid, device); /* ext structs (app registration) are informational */
    FreeLibrary(d3d12);
    return ret;
}

static const IAmdExtD3DCreateDeviceVtbl create_vtbl = { no_interface, static_addref, static_release, create_device };
static const AmdObj creator = { (void *)&create_vtbl };

/* ---- exports ---- */

__declspec(dllexport) HRESULT __cdecl AmdExtD3DCreateInterface(IUnknown *outer, REFIID iid, void **obj)
{
    if (!obj) return E_INVALIDARG;
    *obj = NULL;

    if (IsEqualGUID(iid, &IID_IAmdExtFfxApi))
    {
        ID3D12Device *device = NULL;
        FfxApi *ffx = calloc(1, sizeof(*ffx));

        if (!ffx) return E_OUTOFMEMORY;
        ffx->vtbl = (void *)&ffx_vtbl;
        ffx->ref = 1;
        check_intrinsic_support(outer, &ffx->fp8_supported, NULL, NULL);
        if (outer && SUCCEEDED(outer->lpVtbl->QueryInterface(outer, &IID_ID3D12Device, (void **)&device)))
        {
            device->lpVtbl->GetAdapterLuid(device, &ffx->luid); /* COM returns structs through a hidden pointer */
            ID3D12Device_Release(device);
        }
        *obj = ffx;
        return S_OK;
    }
    if (IsEqualGUID(iid, &IID_IAmdExtAntiLagApi))
        return outer ? outer->lpVtbl->QueryInterface(outer, &IID_IAmdExtAntiLagApi, obj) : E_INVALIDARG;
    if (IsEqualGUID(iid, &IID_IAmdExtD3DFactory))
    {
        *obj = (void *)&factory;
        return S_OK;
    }
    if (IsEqualGUID(iid, &IID_IAmdExtD3DCreateDevice))
    {
        *obj = (void *)&creator;
        return S_OK;
    }
    return E_NOINTERFACE;
}

__declspec(dllexport) HMODULE WINAPI AmdGetDxcModuleHandle(void)
{
    return GetModuleHandleA(NULL);
}

#ifndef FSR4I_NO_DLLMAIN
BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, void *reserved)
{
    const char *env;

    if (reason == DLL_PROCESS_ATTACH)
    {
        fsr4i_init(inst);
        /* watermark for driver-side FSR as well */
        if ((env = getenv("FSR_WATERMARK")) && !strcmp(env, "1")) _putenv("MLSR-WATERMARK=1");
        if ((env = getenv("FSR_FG_WATERMARK")) && !strcmp(env, "1")) _putenv("MLFI-WATERMARK=1");
    }
    return TRUE;
}
#endif
