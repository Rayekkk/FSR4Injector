/*
 * FSR4Injector additions to amdxc64.
 *
 * amdxcffx64.dll picks its FSR4 model from the GPU family/revision it reads out of AMD's kernel driver private data
 * (gdi32!D3DKMTQueryAdapterInfo, KMTQAITYPE_UMDRIVERPRIVATE, family at +0x30, revision at +0x34). Wine has no such
 * data, so the DLL silently falls back to FSR3. We answer that one query with the GPU's real family, observe which
 * model the DLL accepts, and write a per-session status file for the Decky plugin. Nothing on disk is modified.
 *
 * Copyright 2026 FSR4Injector contributors
 *
 * This library is free software; you can redistribute it and/or modify it under the terms of the GNU Lesser
 * General Public License as published by the Free Software Foundation; either version 2.1 of the License, or
 * (at your option) any later version. See COPYING.LIB.
 */
#define COBJMACROS
#include <initguid.h>
#include <dxgi1_4.h>
#include "fsr4i.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef LONG (APIENTRY *qai_fn)(void *);
typedef FARPROC (WINAPI *gpa_fn)(HMODULE, LPCSTR);
typedef unsigned char (*is_supported_fn)(void *provider, void *device);

typedef struct { UINT hAdapter; UINT Type; void *pPrivateDriverData; UINT PrivateDriverDataSize; } QUERYADAPTERINFO;

/* Real values for each GPU, as RADV_DEBUG=info reports them (family_id, chip_external_rev). Lite needs family 150
 * (AMDGPU_FAMILY_GC_11_5_0) with revision 1..0x3F; family 150 with 0xC0..0xCF gets the full INT8 model instead.
 * shortcut: only the Radeon 880M/890M (Strix Point) is verified; add other RDNA 3.5 IDs after testing on them. */
static const struct { USHORT device; UINT family, rev; } gpus[] = {
    { 0x150e, 150, 20 }, /* Strix Point, Legion Go 2: family_id 150, chip_external_rev 20 */
};

/* FFX checks providers in this order and uses the first supported one. */
static const struct { const char *rtti; const char *name; } models[] = {
    { ".?AVffxProvider_FSR4@@", "FP8" },
    { ".?AVffxProvider_FSR4_Int8@@", "INT8" },
    { ".?AVffxProvider_FSR4_Int8_Navi2@@", "INT8_NAVI2" },
    { ".?AVffxProvider_FSR4Lite_Int8@@", "INT8_LITE" },
};
#define NMODELS (sizeof(models) / sizeof(models[0]))
#define IS_SUPPORTED_SLOT 2 /* ffxProvider::IsSupported(void *device), FFX SDK 2.0+ vtable layout */

static HMODULE self_module;
static SRWLOCK lock = SRWLOCK_INIT;
static gpa_fn real_gpa;
static qai_fn real_qai;
static is_supported_fn real_is_supported[NMODELS];

static struct
{
    char started[40];
    UINT vendor, device;
    BOOL have_family;
    UINT family, rev;
    BOOL ffx_requested, dll_loaded, iat_patched, kmd_answered;
    int model_hooks;
    signed char model[NMODELS]; /* -1 not asked, 0 rejected, 1 accepted */
    char provider[64];
    char compat_tool[400]; /* JSON-escaped Proton directory Steam launched us with */
    HRESULT last_hr;
} st = { .model = { -1, -1, -1, -1 } };

static char last_written[2048];

static void update_status(void);

void fsr4i_log(const char *fmt, ...)
{
    char buf[512] = "fsr4i: ";
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf + 7, sizeof(buf) - 8, fmt, ap);
    va_end(ap);
    strcat(buf, "\n");
    OutputDebugStringA(buf);
}

/* JSON string body of s up to the first ':' (STEAM_COMPAT_TOOL_PATHS is a ':'-separated list). */
static void json_escape_first_path(const char *s, char *out, size_t len)
{
    size_t o = 0;
    for (; s && *s && *s != ':' && o + 7 < len; s++)
    {
        unsigned char c = *s;
        if (c == '"' || c == '\\') { out[o++] = '\\'; out[o++] = c; }
        else if (c < 0x20) o += snprintf(out + o, len - o, "\\u%04x", c);
        else out[o++] = c;
    }
    out[o] = 0;
}

void fsr4i_init(HMODULE self)
{
    SYSTEMTIME t;
    self_module = self;
    /* lets the plugin notice a Proton update since FSR4 was last confirmed */
    json_escape_first_path(getenv("STEAM_COMPAT_TOOL_PATHS"), st.compat_tool, sizeof(st.compat_tool));
    GetSystemTime(&t);
    snprintf(st.started, sizeof(st.started), "%04u-%02u-%02uT%02u:%02u:%02uZ",
             t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond);
    /* Mark the session right away: vkd3d loads us in every D3D12 game, so a status older than the session means
     * we were not loaded at all (e.g. another tool rewrote the launch options). Plain file I/O, safe at attach. */
    update_status();
}

BOOL fsr4i_module_path(const WCHAR *name, WCHAR *out, DWORD len)
{
    DWORD n = GetModuleFileNameW(self_module, out, len);
    if (!n || n >= len) return FALSE;
    while (n && out[n - 1] != L'\\' && out[n - 1] != L'/') n--;
    if (n + wcslen(name) + 1 > len) return FALSE;
    wcscpy(out + n, name);
    return TRUE;
}

/* ---- status file ---- */

static const char *tri(signed char v) { return v < 0 ? "null" : v ? "true" : "false"; }

int fsr4i_status_json(char *buf, size_t len)
{
    char models_json[256] = "";
    const char *active = NULL;
    size_t o = 0;

    int pending = 0;

    for (size_t i = 0; i < NMODELS; i++)
    {
        o += snprintf(models_json + o, sizeof(models_json) - o, "%s\"%s\":%s", i ? "," : "", models[i].name, tri(st.model[i]));
        if (!active && st.model[i] == 1) active = models[i].name;
        pending += st.model[i] < 0;
    }
    /* FFX asks every provider until one accepts, so no acceptance after all answered means its FSR3 fallback */
    if (!active && st.model_hooks == (int)NMODELS && !pending) active = "FSR3";
    if (!active && st.dll_loaded && st.model_hooks < (int)NMODELS) active = "unknown";

    return snprintf(buf, len,
        "{\"shim\":\"" FSR4I_VERSION "\",\"pid\":%lu,\"started\":\"%s\",\"gpu\":\"%04x:%04x\","
        "\"ffx_requested\":%s,\"dll_loaded\":%s,\"iat_patched\":%s,\"model_hooks\":%d,"
        "\"kmd_answered\":%s,\"family\":%u,\"rev\":%u,\"models\":{%s},\"provider\":\"%s\","
        "\"compat_tool\":\"%s\",\"last_hr\":\"0x%08lx\",\"active\":%s%s%s}\n",
        GetCurrentProcessId(), st.started, st.vendor, st.device,
        st.ffx_requested ? "true" : "false", st.dll_loaded ? "true" : "false", st.iat_patched ? "true" : "false",
        st.model_hooks, st.kmd_answered ? "true" : "false", st.family, st.rev, models_json, st.provider,
        st.compat_tool, (unsigned long)st.last_hr, active ? "\"" : "", active ? active : "null", active ? "\"" : "");
}

/* Call with the lock held. Rewrites the file only when the content changed. */
static void write_status_locked(void)
{
    char json[2048];
    WCHAR path[MAX_PATH], tmp[MAX_PATH + 4];
    const char *env = getenv("FSR4I_STATUS");
    HANDLE f;
    DWORD written;
    int n = fsr4i_status_json(json, sizeof(json));

    if (n <= 0 || n >= (int)sizeof(json) || !strcmp(json, last_written)) return;
    if (env && *env) MultiByteToWideChar(CP_UTF8, 0, env, -1, path, MAX_PATH);
    else if (!fsr4i_module_path(L"fsr4injector.status.json", path, MAX_PATH)) return;
    swprintf(tmp, MAX_PATH + 4, L"%ls.tmp", path);

    f = CreateFileW(tmp, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (f == INVALID_HANDLE_VALUE) return;
    BOOL ok = WriteFile(f, json, n, &written, NULL) && written == (DWORD)n;
    CloseHandle(f);
    if (ok && MoveFileExW(tmp, path, MOVEFILE_REPLACE_EXISTING)) strcpy(last_written, json);
    else DeleteFileW(tmp);
}

static void update_status(void)
{
    AcquireSRWLockExclusive(&lock);
    write_status_locked();
    ReleaseSRWLockExclusive(&lock);
}

/* ---- GPU family answer ---- */

BOOL fsr4i_lookup_family(UINT vendor, UINT device, UINT *family, UINT *rev)
{
    const char *f = getenv("FSR4I_FAMILY"), *r = getenv("FSR4I_REV");

    if (f && *f && r && *r) /* explicit override, for testing other GPUs */
    {
        *family = strtoul(f, NULL, 0);
        *rev = strtoul(r, NULL, 0);
        return TRUE;
    }
    if (vendor != 0x1002) return FALSE;
    for (size_t i = 0; i < sizeof(gpus) / sizeof(gpus[0]); i++)
        if (gpus[i].device == device)
        {
            *family = gpus[i].family;
            *rev = gpus[i].rev;
            return TRUE;
        }
    return FALSE;
}

LONG APIENTRY fsr4i_fake_query_adapter_info(void *arg)
{
    QUERYADAPTERINFO *q = arg;

    if (st.have_family && q && q->Type == 0 /* KMTQAITYPE_UMDRIVERPRIVATE */ && q->pPrivateDriverData &&
        q->PrivateDriverDataSize >= 0x38)
    {
        BYTE *p = q->pPrivateDriverData;
        memset(p, 0, q->PrivateDriverDataSize);
        *(UINT *)(p + 0x30) = st.family;
        *(UINT *)(p + 0x34) = st.rev;
        if (!st.kmd_answered)
        {
            st.kmd_answered = TRUE;
            update_status();
        }
        return 0; /* STATUS_SUCCESS */
    }
    return real_qai ? real_qai(arg) : (LONG)0xC00000BB; /* STATUS_NOT_SUPPORTED */
}

static FARPROC WINAPI hook_get_proc_address(HMODULE m, LPCSTR name)
{
    FARPROC r = real_gpa(m, name);
    if (HIWORD(name) && !strcmp(name, "D3DKMTQueryAdapterInfo"))
    {
        real_qai = (qai_fn)r;
        return (FARPROC)fsr4i_fake_query_adapter_info;
    }
    return r;
}

/* Replace one import of a loaded module, in memory only. */
BOOL fsr4i_patch_iat(HMODULE mod, const char *dll, const char *func, void *hook, void **orig)
{
    BYTE *base = (BYTE *)mod;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];

    if (!dir.VirtualAddress) return FALSE;
    for (IMAGE_IMPORT_DESCRIPTOR *imp = (void *)(base + dir.VirtualAddress); imp->Name; imp++)
    {
        if (_stricmp((char *)(base + imp->Name), dll) || !imp->OriginalFirstThunk) continue;
        IMAGE_THUNK_DATA *names = (void *)(base + imp->OriginalFirstThunk);
        IMAGE_THUNK_DATA *iat = (void *)(base + imp->FirstThunk);
        for (; names->u1.AddressOfData; names++, iat++)
        {
            DWORD old;
            if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal)) continue;
            if (strcmp((char *)((IMAGE_IMPORT_BY_NAME *)(base + names->u1.AddressOfData))->Name, func)) continue;
            if (!VirtualProtect(&iat->u1.Function, sizeof(void *), PAGE_READWRITE, &old)) return FALSE;
            *orig = (void *)iat->u1.Function;
            iat->u1.Function = (ULONG_PTR)hook;
            VirtualProtect(&iat->u1.Function, sizeof(void *), old, &old);
            return TRUE;
        }
    }
    return FALSE;
}

/* ---- model observation through MSVC RTTI ---- */

static void record_model(size_t i, void *device, unsigned char supported)
{
    if (!device) return; /* FFX also probes without a device; that answer means nothing */
    if (st.model[i] == (signed char)!!supported) return;
    AcquireSRWLockExclusive(&lock);
    st.model[i] = !!supported;
    write_status_locked();
    ReleaseSRWLockExclusive(&lock);
}

#define IS_SUPPORTED_HOOK(i) \
    static unsigned char is_supported_##i(void *p, void *d) \
    { unsigned char r = real_is_supported[i](p, d); record_model(i, d, r); return r; }
IS_SUPPORTED_HOOK(0) IS_SUPPORTED_HOOK(1) IS_SUPPORTED_HOOK(2) IS_SUPPORTED_HOOK(3)
static const is_supported_fn is_supported_hooks[NMODELS] = { is_supported_0, is_supported_1, is_supported_2, is_supported_3 };

/* Next match of needle in [p, hi) at the given alignment (relative to base), or NULL. */
static BYTE *find(BYTE *base, BYTE *p, BYTE *hi, const void *needle, size_t n, size_t align)
{
    p = base + ((p - base + align - 1) / align) * align;
    while (p + n <= hi)
    {
        BYTE *c = memchr(p, *(const BYTE *)needle, hi - p - n + 1);
        if (!c) return NULL;
        if ((size_t)(c - base) % align) p = c + 1;
        else if (!memcmp(c, needle, n)) return c;
        else p = c + 1;
    }
    return NULL;
}

/* First match in any section of the module. */
static BYTE *find_in_image(BYTE *base, IMAGE_NT_HEADERS *nt, const void *needle, size_t n, size_t align,
                           BOOL (*accept)(BYTE *base, BYTE *hit))
{
    IMAGE_SECTION_HEADER *sec = IMAGE_FIRST_SECTION(nt);
    for (int i = 0; i < nt->FileHeader.NumberOfSections; i++)
    {
        BYTE *lo = base + sec[i].VirtualAddress, *hi = lo + sec[i].Misc.VirtualSize;
        for (BYTE *p = lo; (p = find(base, p, hi, needle, n, align)); p++)
            if (!accept || accept(base, p)) return p;
    }
    return NULL;
}

/* CompleteObjectLocator: signature 1, offset 0, cdOffset, pTypeDescriptor, pClassDescriptor, pSelf */
static BOOL is_col(BYTE *base, BYTE *td_field)
{
    DWORD *c = (DWORD *)(td_field - 12);
    return (BYTE *)c >= base && c[0] == 1 && c[1] == 0 && c[5] == (DWORD)((BYTE *)c - base);
}

/* Returns the vtable of an RTTI class in a loaded MSVC x64 module, or NULL. */
static void **find_vtable(HMODULE mod, const char *rtti)
{
    BYTE *base = (BYTE *)mod, *name, *td_field, *slot;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    DWORD td_rva;
    ULONG_PTR col_va;

    /* TypeDescriptor: pVFTable, spare, then the mangled name */
    if (!(name = find_in_image(base, nt, rtti, strlen(rtti) + 1, 1, NULL))) return NULL;
    td_rva = (DWORD)(name - 0x10 - base);
    if (!(td_field = find_in_image(base, nt, &td_rva, 4, 4, is_col))) return NULL;
    col_va = (ULONG_PTR)(td_field - 12);
    /* vtable[-1] points at the COL */
    slot = find_in_image(base, nt, &col_va, sizeof(col_va), sizeof(col_va), NULL);
    return slot ? (void **)(slot + sizeof(void *)) : NULL;
}

int fsr4i_hook_models(HMODULE ffx)
{
    int hooked = 0;

    for (size_t i = 0; i < NMODELS; i++)
    {
        void **vt = find_vtable(ffx, models[i].rtti);
        DWORD old;

        if (!vt || !VirtualProtect(&vt[IS_SUPPORTED_SLOT], sizeof(void *), PAGE_READWRITE, &old)) continue;
        real_is_supported[i] = (is_supported_fn)vt[IS_SUPPORTED_SLOT];
        vt[IS_SUPPORTED_SLOT] = (void *)is_supported_hooks[i];
        VirtualProtect(&vt[IS_SUPPORTED_SLOT], sizeof(void *), old, &old);
        hooked++;
    }
    return hooked;
}

/* ---- callbacks from amdxc64.c ---- */

static void query_gpu(LUID luid)
{
    typedef HRESULT (WINAPI *create_factory_fn)(REFIID, void **);
    HMODULE dxgi = LoadLibraryW(L"dxgi.dll");
    create_factory_fn create = dxgi ? (create_factory_fn)GetProcAddress(dxgi, "CreateDXGIFactory1") : NULL;
    IDXGIFactory4 *factory;
    IDXGIAdapter *adapter;
    DXGI_ADAPTER_DESC desc;

    if (create && SUCCEEDED(create(&IID_IDXGIFactory4, (void **)&factory)))
    {
        if (SUCCEEDED(IDXGIFactory4_EnumAdapterByLuid(factory, luid, &IID_IDXGIAdapter, (void **)&adapter)))
        {
            if (SUCCEEDED(IDXGIAdapter_GetDesc(adapter, &desc)))
            {
                st.vendor = desc.VendorId;
                st.device = desc.DeviceId;
            }
            IDXGIAdapter_Release(adapter);
        }
        IDXGIFactory4_Release(factory);
    }
    if (dxgi) FreeLibrary(dxgi);
}

void fsr4i_on_ffx_request(LUID luid)
{
    if (st.ffx_requested) return; /* SDK 2.x games call this every frame */
    AcquireSRWLockExclusive(&lock);
    if (!st.ffx_requested)
    {
        query_gpu(luid);
        st.have_family = fsr4i_lookup_family(st.vendor, st.device, &st.family, &st.rev);
        if (!st.have_family) fsr4i_log("GPU %04x:%04x is not in the RDNA 3.5 table; FSR4 stays off", st.vendor, st.device);
        st.ffx_requested = TRUE;
        write_status_locked();
    }
    ReleaseSRWLockExclusive(&lock);
}

void fsr4i_on_ffx_loaded(HMODULE ffx)
{
    static LONG done;
    if (InterlockedExchange(&done, 1)) return;

    AcquireSRWLockExclusive(&lock);
    st.dll_loaded = TRUE;
    st.iat_patched = fsr4i_patch_iat(ffx, "KERNEL32.dll", "GetProcAddress", hook_get_proc_address, (void **)&real_gpa);
    st.model_hooks = fsr4i_hook_models(ffx);
    fsr4i_log("amdxcffx64 loaded, iat_patched=%d model_hooks=%d", st.iat_patched, st.model_hooks);
    write_status_locked();
    ReleaseSRWLockExclusive(&lock);
}

void fsr4i_on_provider(HRESULT hr, const char *version_name)
{
    if (st.last_hr == hr && (!version_name || st.provider[0])) return;
    AcquireSRWLockExclusive(&lock);
    st.last_hr = hr;
    if (version_name && !st.provider[0])
        for (size_t i = 0; version_name[i] && i < sizeof(st.provider) - 1; i++)
            st.provider[i] = (version_name[i] >= 0x20 && version_name[i] < 0x7f && version_name[i] != '"' &&
                              version_name[i] != '\\') ? version_name[i] : '?';
    write_status_locked();
    ReleaseSRWLockExclusive(&lock);
}
