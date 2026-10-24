"""Build a sparse local copy of a remote 7z SFX with only the stub/start header and the end header filled in,
so `7z l -slt` can list blocks without downloading the whole archive."""
import struct, sys, urllib.request

url, out = sys.argv[1], sys.argv[2]
HDR = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.amd.com/'}

def get(a, b):
    req = urllib.request.Request(url, headers={**HDR, 'Range': f'bytes={a}-{b}'})
    with urllib.request.urlopen(req, timeout=60) as r:
        assert r.status == 206, r.status
        return r.read()

head = get(0, 4 * 1024 * 1024 - 1)
sig = head.find(b'7z\xbc\xaf\x27\x1c')
assert sig >= 0, '7z signature not found in first 4 MiB'
next_off, next_size = struct.unpack_from('<QQ', head, sig + 12)
total = int(urllib.request.urlopen(urllib.request.Request(url, method='HEAD', headers=HDR), timeout=30).headers['Content-Length'])
hdr_start = sig + 32 + next_off
tail = get(hdr_start, hdr_start + next_size - 1)
with open(out, 'wb') as f:
    f.truncate(total)
    f.write(head)
    f.seek(hdr_start)
    f.write(tail)
print(f'archive_offset={sig} header_at={hdr_start} header_size={next_size} total={total}')
