/*
 * AMD D3D12 driver extension interfaces used by amdxcffx64.dll, and the vkd3d-proton extension we query.
 * Layouts follow dlls/amdxc64/amdxc_interfaces.idl from GE-Proton (Etaash Mathamsetty, LGPL-2.1+) and
 * include/vkd3d_device_vkd3d_ext.idl from vkd3d-proton.
 *
 * This library is free software; you can redistribute it and/or modify it under the terms of the GNU Lesser
 * General Public License as published by the Free Software Foundation; either version 2.1 of the License, or
 * (at your option) any later version. See COPYING.LIB.
 */
#pragma once
#define COBJMACROS
#include <windows.h>
#include <d3d12.h>

DEFINE_GUID(IID_IAmdExtFfxApi,              0xb58d6601, 0x7401, 0x4234, 0x81, 0x80, 0x6f, 0xeb, 0xfc, 0x0e, 0x48, 0x4c);
DEFINE_GUID(IID_IAmdExtAntiLagApi,          0x44085fbe, 0xe839, 0x40c5, 0xbf, 0x38, 0x0e, 0xbc, 0x5a, 0xb4, 0xd0, 0xa6);
DEFINE_GUID(IID_IAmdExtD3DFactory,          0x014937ec, 0x9288, 0x446f, 0xa9, 0xac, 0xd7, 0x5a, 0x8e, 0x3a, 0x98, 0x4f);
DEFINE_GUID(IID_IAmdExtD3DShaderIntrinsics, 0xba019d53, 0xccab, 0x4cbd, 0xb5, 0x6a, 0x72, 0x30, 0xed, 0x43, 0x30, 0xad);
DEFINE_GUID(IID_IAmdExtD3DDevice,           0x8104c0fc, 0x7413, 0x410f, 0x8e, 0x83, 0xaa, 0x61, 0x7e, 0x90, 0x86, 0x48);
DEFINE_GUID(IID_IAmdExtD3DDevice1,          0x4bbcaf68, 0xeaf7, 0x4fa4, 0xb6, 0x53, 0xcb, 0x45, 0x8c, 0x33, 0x4a, 0x4e);
DEFINE_GUID(IID_IAmdExtD3DDevice8,          0xf714e11a, 0xb54e, 0x4e0f, 0xab, 0xc5, 0xdf, 0x58, 0xb1, 0x81, 0x33, 0xd1);
DEFINE_GUID(IID_IAmdExtD3DCreateDevice,     0xc4200955, 0xfd57, 0x481a, 0xbd, 0x22, 0x94, 0x71, 0x74, 0xc6, 0xc6, 0x98);
DEFINE_GUID(IID_ID3D12DeviceExt3,           0x3aefa75c, 0xc9f3, 0x4b7f, 0xa1, 0x80, 0x5d, 0xf6, 0x95, 0xd0, 0x83, 0xbf);

/* vkd3d-proton D3D12_AGS_EXTENSION */
enum
{
    AGS_INTRINSICS_16 = 0, AGS_INTRINSICS_17, AGS_USER_MARKERS, AGS_APP_REGISTRATION, AGS_UAV_BIND_SLOT,
    AGS_INTRINSICS_19, AGS_BASE_VERTEX, AGS_BASE_INSTANCE, AGS_GET_WAVE_SIZE, AGS_FLOAT_CONVERSION,
    AGS_READ_LANE_AT, AGS_RAY_HIT_TOKEN, AGS_SHADER_CLOCK, /* "SHADER_TOKEN" in vkd3d-proton */
    AGS_WMMA_FP8 = 100, AGS_WMMA_FP8_NATIVE,
};
/* ID3D12DeviceExt3::SupportsAGSExtension: IUnknown(3) + DeviceExt(7) + Ext1(2) + Ext2(4) */
#define DEVICEEXT3_SUPPORTS_AGS_SLOT 16

typedef enum
{
    Intr_Readfirstlane = 0x1, Intr_Barycentrics = 0x8, Intr_WaveReduce = 0x9, Intr_WaveScan = 0xA,
    Intr_DrawIndex = 0xE, Intr_AtomicU64 = 0xF, Intr_BaseInstance = 0x10, Intr_BaseVertex = 0x11,
    Intr_FloatConversion = 0x12, Intr_GetWaveSize = 0x13, Intr_ReadlaneAt = 0x14, Intr_RayTraceHitToken = 0x15,
    Intr_ShaderClock = 0x16, Intr_ShaderRealtimeClock = 0x17, Intr_WaveMatrix = 0x1F, Intr_Float8Conversion = 0x20,
} AmdIntrinsic;

#define AMD_EXT_WMMA_TYPE_FP32 1
#define AMD_EXT_WMMA_TYPE_FP8 11

typedef struct
{
    SIZE_T mSize, nSize, kSize;
    ULONG aType, bType, cType, resultType, saturatingAccumulation;
} AmdExtWaveMatrixProperties;

typedef struct AmdExtD3DCreateDeviceInfo
{
    UINT type; /* AmdExtD3DStructTypeAppRegId = 1, ... */
    struct AmdExtD3DCreateDeviceInfo *pNext;
} AmdExtD3DCreateDeviceInfo;

/* Interfaces are plain C objects whose first member is the vtable pointer. */
typedef struct { void *vtbl; } AmdObj;

typedef struct
{
    HRESULT (STDMETHODCALLTYPE *QueryInterface)(void *, REFIID, void **);
    ULONG (STDMETHODCALLTYPE *AddRef)(void *);
    ULONG (STDMETHODCALLTYPE *Release)(void *);
    HRESULT (STDMETHODCALLTYPE *UpdateFfxApiProvider)(void *, void *data, unsigned int size);
} IAmdExtFfxApiVtbl;

typedef struct
{
    HRESULT (STDMETHODCALLTYPE *QueryInterface)(void *, REFIID, void **);
    ULONG (STDMETHODCALLTYPE *AddRef)(void *);
    ULONG (STDMETHODCALLTYPE *Release)(void *);
    HRESULT (STDMETHODCALLTYPE *CreateInterface)(void *, IUnknown *outer, REFIID, void **);
} IAmdExtD3DFactoryVtbl;

typedef struct
{
    HRESULT (STDMETHODCALLTYPE *QueryInterface)(void *, REFIID, void **);
    ULONG (STDMETHODCALLTYPE *AddRef)(void *);
    ULONG (STDMETHODCALLTYPE *Release)(void *);
    HRESULT (STDMETHODCALLTYPE *GetInfo)(void *, void *info);
    HRESULT (STDMETHODCALLTYPE *CheckSupport)(void *, UINT opcode);
    HRESULT (STDMETHODCALLTYPE *Enable)(void *);
} IAmdExtD3DShaderIntrinsicsVtbl;

/* IAmdExtD3DDevice8: 13 methods we never implement, then GetWaveMatrixProperties. */
typedef struct
{
    HRESULT (STDMETHODCALLTYPE *QueryInterface)(void *, REFIID, void **);
    ULONG (STDMETHODCALLTYPE *AddRef)(void *);
    ULONG (STDMETHODCALLTYPE *Release)(void *);
    void *unimplemented[13];
    HRESULT (STDMETHODCALLTYPE *GetWaveMatrixProperties)(void *, SIZE_T *count, AmdExtWaveMatrixProperties *props);
} IAmdExtD3DDevice8Vtbl;

typedef struct
{
    HRESULT (STDMETHODCALLTYPE *QueryInterface)(void *, REFIID, void **);
    ULONG (STDMETHODCALLTYPE *AddRef)(void *);
    ULONG (STDMETHODCALLTYPE *Release)(void *);
    HRESULT (STDMETHODCALLTYPE *AmdD3D12CreateDevice)(void *, IUnknown *adapter, D3D_FEATURE_LEVEL minLevel,
                                                      REFIID, void **device, AmdExtD3DCreateDeviceInfo *ext);
} IAmdExtD3DCreateDeviceVtbl;
