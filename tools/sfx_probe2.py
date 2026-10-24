"""Fill the sparse copy with the packed (encoded) 7z header so 7-Zip can list the archive.
The 39-byte end header is kEncodedHeader: PackInfo(packPos, size) + folder coders; we only need packPos/size."""
import struct, sys, urllib.request

url, out, arc_off, hdr_at, hdr_size = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:6])
HDR = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.amd.com/'}

def get(a, b):
    req = urllib.request.Request(url, headers={**HDR, 'Range': f'bytes={a}-{b}'})
    with urllib.request.urlopen(req, timeout=120) as r:
        assert r.status == 206, r.status
        return r.read()

def read_num(b, i):  # 7z variable-length UINT64
    first = b[i]; mask = 0x80; val = 0
    for n in range(8):
        if not first & mask:
            hi = first & (mask - 1)
            return val | (hi << (8 * n)), i + 1 + n
        val |= b[i + 1 + n] << (8 * n); mask >>= 1
    return val, i + 9

h = get(hdr_at, hdr_at + hdr_size - 1)
assert h[0] == 0x17, f'not an encoded header: {h[0]:#x}'
assert h[1] == 0x06, 'expected PackInfo'
pack_pos, i = read_num(h, 2)
num_streams, i = read_num(h, i)
assert h[i] == 0x09; i += 1  # kSize
size, i = read_num(h, i)
start = arc_off + 32 + pack_pos
print(f'packed header at {start} size {size}')
data = get(start, start + size - 1)
with open(out, 'r+b') as f:
    f.seek(start); f.write(data)
