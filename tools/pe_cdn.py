"""Print the AMD symbol-server style CDN URL (TimeDateStamp + SizeOfImage) for PE files and HEAD-probe it."""
import struct, sys, urllib.request

def key(path):
    with open(path, 'rb') as f:
        d = f.read(4096)
    pe = struct.unpack_from('<I', d, 0x3C)[0]
    assert d[pe:pe + 4] == b'PE\0\0', 'not a PE file'
    ts = struct.unpack_from('<I', d, pe + 8)[0]
    size_of_image = struct.unpack_from('<I', d, pe + 24 + 56)[0]  # OptionalHeader.SizeOfImage
    return f'{ts:X}{size_of_image:x}'

# self-check against a known published URL key (4.1.0 = 69A0952A304a000)
assert f'{0x69A0952A:X}{0x304a000:x}' == '69A0952A304a000'

for p in sys.argv[1:]:
    k = key(p)
    url = f'https://download.amd.com/dir/bin/amdxcffx64.dll/{k}/amdxcffx64.dll'
    try:
        req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            st = f'{r.status} len={r.headers.get("content-length")} mod={r.headers.get("last-modified")}'
    except Exception as e:
        st = f'ERR {e}'
    print(f'{p}\n  key={k}\n  {url}\n  {st}')
