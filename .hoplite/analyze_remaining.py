import re, os
from pathlib import Path

os.chdir('/tmp/hoplite/workspace')

# Parse linked .text ranges from splits.txt
ranges = []
cur = None
for line in Path('config/GALE01/splits.txt').read_text().splitlines():
    m = re.match(r'^(\S+):\s*$', line)
    if m and '/' in m.group(1):
        cur = m.group(1)
    m = re.match(r'^\s*\.text\s+start:(0x[0-9A-Fa-f]+) end:(0x[0-9A-Fa-f]+)', line)
    if m and cur:
        ranges.append((cur, int(m.group(1), 16), int(m.group(2), 16)))

# Parse functions from symbols.txt
funcs = []
for line in Path('config/GALE01/symbols.txt').read_text().splitlines():
    m = re.match(r'^(\S+) = \.text:(0x[0-9A-Fa-f]+); // type:function size:(0x[0-9A-Fa-f]+)', line)
    if m:
        funcs.append((m.group(1), int(m.group(2), 16), int(m.group(3), 16)))

print(f"linked .text units: {len(ranges)}, total functions in .text: {len(funcs)}")

def covered(addr):
    for name, s, e in ranges:
        if s <= addr < e:
            return name
    return None

remaining = [(n, a, sz) for n, a, sz in funcs if not covered(a)]
print(f"functions outside linked units: {len(remaining)}")

names = {n for n,_,_ in remaining}
found = set()
for root, dirs, files in os.walk('src'):
    for f in files:
        if f.endswith(('.c','.h','.s','.inc')):
            p = os.path.join(root,f)
            try:
                t = open(p, errors='ignore').read()
            except Exception:
                continue
            for n in names:
                if n in t:
                    found.add(n)
print(f"of those, name appears somewhere in src: {len(found)}")
for n,a,sz in sorted(remaining, key=lambda x:x[1]):
    print(f"0x{a:08X} size=0x{sz:<4X} {n} in_src={'y' if n in found else 'n'}")
