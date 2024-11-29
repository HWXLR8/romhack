#!/usr/bin/env python3

import os
import sys

class ROM:
    def __init__(self, file_name):
        self.offsets = None
        print("Reading rom...", end='', flush=True)
        with open(file_name, "rb") as f:
            self.rom = f.read()
        print("done", flush=True)

    # returns a list of offsets indicating the beginning of a sample
    def find_offsets(self, window_size=64):
        print("Searching for samples...", end='', flush=True)
        self.offsets = [0] # start at zero for the first sample
        non_gap = 0
        non_gap_threshold = 4096
        in_sample = True # we begin in a sample
        for i in range(len(self.rom) - window_size + 1):
            window = self.rom[i:i + window_size]
            # check if window only contains 0x00/0xFE/0xFF
            if all(x in (0, 254, 255) for x in window):
                in_sample = False
                non_gap = 0
                continue
            else:
                if (non_gap == non_gap_threshold) and not in_sample:
                    in_sample = True
                    self.offsets.append(i - non_gap_threshold)
                else:
                    non_gap += 1
        print("done", flush=True)
        self.num_samples = len(self.offsets)
        print("Found %s samples" % self.num_samples)
        return self.offsets

    def write_offsets(self):
        if self.offsets is None:
            self.find_offsets()
        with open('offsets', 'w') as file:
            print("Writing offsets to file...", end='', flush=True)
            for offset in self.offsets:
                file.write(str(offset) + '\n')
            print("done", flush=True)

    def _write_sample(self, num, data):
        print("Writing sample_%s..." % num, end='', flush=True)
        with open('samples/sample_%s' % num, 'wb') as f:
            f.write(data)
        print("done", flush=True)

    def write_samples(self):
        print("Creating 'samples' directory")
        os.makedirs('samples', exist_ok=True)
        for o in range(self.num_samples):
            # write until EOF if last sample
            if o == self.num_samples - 1:
                self._write_sample(o, self.rom[offsets[o]:])
            else:
                begin = self.offsets[o]
                end = self.offsets[o + 1]
                self._write_sample(o, self.rom[begin:end])

file_name = sys.argv[1]
window_size = int(sys.argv[2])
r = ROM(file_name)
r.find_offsets()
r.write_offsets()
