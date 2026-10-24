"""Find MSVC x64 vtables of given classes via RTTI and print the VA of selected slots."""
import struct, sys

path, classes = sys.argv[1], sys.argv[2:]
d = open(path, 'rb').read()
pe = struct.unpack_from('<I', d, 0x3C)[0]
nsec = struct.unpack_from('<H', d, pe + 6)[0]
osz = struct.unpack_from('<H', d, pe + 20)[0]
base = struct.unpack_from('<Q', d, pe + 24 + 24)[0]
secs = [struct.unpack_from('<8sIIII', d, pe + 24 + osz + i * 40) for i in range(nsec)]

def rva2off(rva):
    for _, vs, va, rs, ro in secs:
        if va <= rva < va + max(vs, rs):
            return rva - va + ro

def off2rva(off):
    for _, vs, va, rs, ro in secs:
        if ro <= off < ro + rs:
            return off - ro + va

for cls in classes:
    name = f'.?AV{cls}@@'.encode() + b'\0'
    noff = d.find(name)
    if noff < 0:
        print(cls, 'not found'); continue
    td_rva = off2rva(noff) - 0x10
    # COL: sig(1), offset, cdOffset, pTypeDescriptor, pClassDescriptor, pSelf
    found = False
    pos = 0
    while True:
        pos = d.find(struct.pack('<I', td_rva), pos + 1)
        if pos < 0: break
        col_off = pos - 12
        sig, offset, cd, td, chd, selfp = struct.unpack_from('<IIIIII', d, col_off)
        if sig != 1 or td != td_rva or selfp != off2rva(col_off) or offset != 0:
            continue
        col_va = base + selfp
        vp = d.find(struct.pack('<Q', col_va))
        while vp >= 0:
            vt_rva = off2rva(vp + 8)
            slots = [struct.unpack_from('<Q', d, vp + 8 + 8 * i)[0] for i in range(6)]
            print(f'{cls}: vtable VA {base + vt_rva:#x}  slots: ' + ' '.join(f'[{i}]{s:#x}' for i, s in enumerate(slots)))
            found = True
            vp = d.find(struct.pack('<Q', col_va), vp + 1)
    if not found:
        print(cls, 'vtable not found')
print('imagebase', hex(base))
