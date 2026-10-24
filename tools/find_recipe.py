"""Maintainer tool: find an LZMA2 dictionary-reset point before amdxcffx64.dll inside block 1 of the Adrenalin 7z,
locate the DLL in the decoded stream, and print a download "recipe" (offsets only, no AMD bytes)."""
import hashlib, lzma, struct, sys, urllib.request

url, packed_start, dll_off, dll_size, want_sha = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
reset_rel = int(sys.argv[6])  # packed offset of a verified reset chunk, relative to block start
HDR = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.amd.com/'}
LZ = {'id': lzma.FILTER_LZMA2, 'dict_size': 2**24}

def stream(pos):
    req = urllib.request.Request(url, headers={**HDR, 'Range': f'bytes={pos}-'})
    return urllib.request.urlopen(req, timeout=120)

def find_pe(buf, start):
    i = buf.find(b'MZ', start)
    while i >= 0:
        if i + 0x400 <= len(buf):
            pe = struct.unpack_from('<I', buf, i + 0x3C)[0]
            if pe < 0x400 and buf[i + pe:i + pe + 4] == b'PE\0\0' and struct.unpack_from('<H', buf, i + pe + 4)[0] == 0x8664:
                soi = struct.unpack_from('<I', buf, i + pe + 24 + 56)[0]
                if soi == 0x504a000:
                    return i
        i = buf.find(b'MZ', i + 1)
    return -1

# pass 1: decode without BCJ, find our DLL (SizeOfImage from its PE header) and how far it is from the reset point
comp = bytearray(); out = bytearray(); d = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[LZ])
r = stream(packed_start + reset_rel); local = -1; scanned = 0
while True:
    chunk = r.read(1 << 20)
    if not chunk: sys.exit('stream ended before DLL found')
    comp += chunk; out += d.decompress(chunk)
    if local < 0:
        local = find_pe(out, max(0, scanned - 0x400)); scanned = len(out)
        if local < 0 and len(out) > 400 * 2**20: sys.exit('DLL not found within 400 MiB: reset point is after it')
    if local >= 0 and len(out) >= local + dll_size:
        break
r.close()
reset_abs = dll_off - local
print(f'DLL found {local} bytes after reset; reset unpacked offset {reset_abs}; downloaded {len(comp)/2**20:.1f} MiB')

# pass 2: decode the same bytes with BCJ x86 at the right stream position and check the hash
d2 = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[{'id': lzma.FILTER_X86, 'start_offset': reset_abs % 2**32}, LZ])
out2 = d2.decompress(bytes(comp), max_length=local + dll_size)
dll = out2[local:local + dll_size]
sha = hashlib.sha256(dll).hexdigest()
print('sha256', sha, 'OK' if sha == want_sha else 'MISMATCH')
# packed bytes actually needed: re-run counting input until output covers the DLL
print(f'RECIPE packed_offset={packed_start + reset_rel} unpacked_offset={reset_abs} dll_local={local} dll_size={dll_size} sha256={sha}')
