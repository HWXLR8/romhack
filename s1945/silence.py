#!/usr/bin/env python3

IN  = "u61.bin"
OUT = "u61_patched.bin"

# hard-coded byte ranges: (START, END) with END exclusive
RANGES = [
    (672_084, 839_682), # music
    (1524061, 1633017), # percussion
]

with open(IN, "rb") as f:
    data = bytearray(f.read())
n = len(data)

for s, e in RANGES:
    if s < 0 or e <= s:
        raise ValueError(f"Invalid range {s}:{e}")
    if s >= n:
        continue # skip ranges beyond file
    e = min(e, n) # clamp to file end
    data[s:e] = b"\x00" * (e - s)

with open(OUT, "wb") as f:
    f.write(data)
print(f"patched {OUT} from {IN} with {len(RANGES)} range(s).")
