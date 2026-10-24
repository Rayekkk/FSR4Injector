"""Probe whether block 1 of the Adrenalin 7z has LZMA2 dictionary-reset chunks we could start decoding from.
Downloads a small window of packed data and tries raw LZMA2 decoding from every candidate reset-chunk header."""
import lzma, re, sys, urllib.request

url, listing = sys.argv[1], sys.argv[2]
win_off_mib, win_mib = float(sys.argv[3]), float(sys.argv[4])
ARC = 1785344
HDR = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.amd.com/'}

txt = open(listing, encoding='utf-8', errors='replace').read()
ents = [dict(re.findall(r'^([A-Za-z ]+) = (.*)$', e, re.M)) for e in txt.split('\n\n') if 'Path = ' in e]
packed = {}
for e in ents:
    b = e.get('Block', '').strip()
    if b.isdigit() and e.get('Packed Size', '').strip().isdigit():
        packed[int(b)] = packed.get(int(b), 0) + int(e['Packed Size'])
blk1 = ARC + 32 + packed[0]
start = blk1 + int(win_off_mib * 2**20)
req = urllib.request.Request(url, headers={**HDR, 'Range': f'bytes={start}-{start + int(win_mib * 2**20) - 1}'})
data = urllib.request.urlopen(req, timeout=120).read()
print(f'block1 packed start={blk1} size={packed[1]}; window at +{win_off_mib} MiB, got {len(data)} bytes')

found = 0
for i in range(len(data) - 6):
    c = data[i]
    if c < 0xE0 or data[i + 5] != 0x5D:  # LZMA chunk with dictionary reset + props lc3/lp0/pb2
        continue
    try:
        d = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[{'id': lzma.FILTER_LZMA2, 'dict_size': 2**24}])
        out = d.decompress(data[i:i + 600000], max_length=4 * 2**20)
    except lzma.LZMAError:
        continue
    if len(out) >= 2**20:
        found += 1
        print(f'  reset chunk at window+{i} (packed +{win_off_mib * 2**20 + i:.0f} into block): decoded {len(out)} bytes OK')
        if found >= 5:
            break
print('candidates verified:', found)
