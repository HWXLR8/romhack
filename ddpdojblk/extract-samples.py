#!/usr/bin/env python3

import os
import sys

class ROM:
    def __init__(self, rom_path, window_size):
        self.window_size = window_size
        self.rom_path = rom_path
        self.offsets = None
        print("Reading rom...", end='', flush=True)
        with open(self.rom_path, "rb") as f:
            self.rom = f.read()
        print("done", flush=True)

    # returns a list of offsets indicating the beginning of a sample
    def find_offsets(self):
        print("Searching for samples...", end='', flush=True)
        self.offsets = [0] # start at zero for the first sample
        non_gap = 0
        non_gap_threshold = 2048
        in_sample = True # we begin in a sample
        for i in range(len(self.rom) - self.window_size + 1):
            window = self.rom[i:i + self.window_size]
            # check if window only contains 0x00/0xFE/0xFF
            if all(x in (0, 254, 255) for x in window):
                in_sample = False
                non_gap = 0
            else:
                if not in_sample:
                    non_gap += 1
                    if non_gap == non_gap_threshold:
                        in_sample = True
                        self.offsets.append(i - non_gap_threshold)

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
                file.write(str(hex(offset)) + '\n')
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
                self._write_sample(o, self.rom[self.offsets[o]:])
            else:
                begin = self.offsets[o]
                end = self.offsets[o + 1]
                self._write_sample(o, self.rom[begin:end])

    def _zero_out(self, start_address, end_address):
        with open(self.rom_path, 'r+b') as f:
            f.seek(start_address)
            zero_bytes = b'\x00' * (end_address - start_address + 1)
            f.write(zero_bytes)
        f.close()

    # remove all music samples, preserves SFX and voices
    def remove_music(self):
        music_samples = [
                                35, 36,
            60, 61, 62, 63, 64, 65, 66, 67, 68, 69,
            70, 71, 72, 73, 74, 75, 76, 77, 78, 79,
            80, 81, 82, 83, 84, 85, 86, 87, 88, 89,
            90,
        ]
        print("Zeroing out sample", end='', flush=True)
        for sample in music_samples:
            start_addr = self.offsets[sample]

            # if last sample, zero out until the EOF
            if sample == len(self.offsets) - 1:
                end_addr = 0x3FFFF0
            else:
                end_addr = self.offsets[sample + 1]

            print("zeroing out sample %s: %s -> %s" % (sample, hex(start_addr), hex(end_addr)))
            self._zero_out(start_addr, end_addr)

rom_path = sys.argv[1]
window_size = 32
r = ROM(rom_path, window_size)
r.find_offsets()
r.write_offsets()
r.write_samples()
# r.remove_music()
