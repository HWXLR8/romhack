#!/usr/bin/env python3

import os
import sys

file_name = sys.argv[1]
window_size = int(sys.argv[2])

print("Reading rom...", end='', flush=True)
with open(file_name, "rb") as f:
    rom = f.read()
print("done", flush=True)

print("Searching for samples...", end='', flush=True)
offsets = [0] # start at zero for the first sample
non_gap = 0
non_gap_threshold = 4096
in_sample = True # we begin in a sample
for i in range(len(rom) - window_size + 1):
    window = rom[i:i + window_size]
    # check if window only contains 0x00 or 0xFF
    if all(x in (0, 254, 255) for x in window):
        in_sample = False
        non_gap = 0
        continue
    else:
        if (non_gap == non_gap_threshold) and not in_sample:
            in_sample = True
            offsets.append(i - non_gap_threshold)
        else:
            non_gap += 1
print("done", flush=True)
num_samples = len(offsets)
print("Found %s samples" % num_samples)

def write_sample(num, data):
    print("Writing sample_%s..." % num, end='', flush=True)
    with open('samples/sample_%s' % num, 'wb') as f:
        f.write(data)
    print("done", flush=True)

print("Creating 'samples' directory")
os.makedirs('samples', exist_ok=True)
for o in range(num_samples):
    # write until EOF if last sample
    if o == num_samples - 1:
        write_sample(o, rom[offsets[o]:])
    else:
        begin = offsets[o]
        end = offsets[o + 1]
        write_sample(o, rom[begin:end])
