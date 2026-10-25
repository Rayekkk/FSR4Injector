/* FSR4Injector additions to amdxc64: GPU family answer, model observation, session status. LGPL-2.1+. */
#pragma once
#include <windows.h>

#define FSR4I_VERSION "1.0.0"

void fsr4i_init(HMODULE self);
void fsr4i_exit(void);
BOOL fsr4i_module_path(const WCHAR *name, WCHAR *out, DWORD len);
void fsr4i_on_ffx_request(LUID luid);
void fsr4i_on_ffx_loaded(HMODULE ffx);
void fsr4i_on_provider(HRESULT hr, const char *version_name);
void fsr4i_log(const char *fmt, ...);

/* Exposed for the self-test. */
BOOL fsr4i_lookup_family(UINT vendor, UINT device, UINT *family, UINT *rev);
int fsr4i_hook_models(HMODULE ffx);
BOOL fsr4i_module_version(HMODULE mod, WORD v[4]);
unsigned char fsr4i_model_allowed(size_t model, unsigned char supported);
BOOL fsr4i_patch_iat(HMODULE mod, const char *dll, const char *func, void *hook, void **orig);
LONG APIENTRY fsr4i_fake_query_adapter_info(void *arg);
int fsr4i_status_json(char *buf, size_t len);
