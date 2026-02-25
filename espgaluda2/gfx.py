#!/usr/bin/env python3
# cave_tex_simple.py
#
# Minimal CAVE X360 texture tool:
#   unpack <file.bin>          -> writes <stem>.tga and <stem>.png
#   repack <orig.bin> <image>  -> writes <orig_stem>_repacked.bin
#
# PNG repack uses the original TGA as a template and preserves the original 1-bit alpha mask.
# Requires Pillow: pip install pillow

from __future__ import annotations
import io
import math
import sys
from pathlib import Path
from PIL import Image


# -----------------------------
# Wrapper / CV1000 compression
# -----------------------------

def parse_wrapper(blob: bytes):
    if len(blob) < 0x30:
        raise ValueError("File too small")
    header_size = int.from_bytes(blob[0x08:0x0C], "big")
    raw_size = int.from_bytes(blob[0x28:0x2C], "big")
    comp_size = int.from_bytes(blob[0x2C:0x30], "big")
    if header_size <= 0 or header_size > len(blob):
        raise ValueError("Bad header size")
    if comp_size <= 0 or header_size + comp_size > len(blob):
        raise ValueError("Bad compressed size")
    return header_size, raw_size, comp_size


def cv1000_decompress(data: bytes) -> bytes:
    if len(data) < 12:
        raise ValueError("Compressed stream too short")

    out_size = int.from_bytes(data[0:4], "big")
    op_count = int.from_bytes(data[4:8], "big")
    data_ptr = int.from_bytes(data[8:12], "big")
    bit_ptr = 0x0C

    out = bytearray(out_size)
    out_ptr = 0
    bits_left = 0
    bit_byte = 0

    for _ in range(op_count):
        if bits_left == 0:
            bit_byte = data[bit_ptr]
            bit_ptr += 1
            bits_left = 8

        is_lz = (bit_byte & 0x80) != 0

        if not is_lz:
            out[out_ptr] = data[data_ptr]
            out_ptr += 1
            data_ptr += 1
        else:
            token = (data[data_ptr] << 8) | data[data_ptr + 1]
            data_ptr += 2
            backref = token >> 5
            length = (token & 0x1F) + 3
            src = out_ptr - backref
            if backref == 0 or src < 0:
                raise ValueError("Bad LZ token")
            for _ in range(length):
                out[out_ptr] = out[src]
                out_ptr += 1
                src += 1

        bit_byte = ((bit_byte << 1) & 0xFF)
        bits_left -= 1

    if out_ptr != out_size:
        raise ValueError("Decompress size mismatch")
    return bytes(out)


def cv1000_compress(in_data: bytes) -> bytes:
    # Greedy compressor compatible with the decompressor above.
    def find_match(pos: int):
        max_back = 2047
        start = max(0, pos - max_back)
        end = min(pos + 34, len(in_data))
        if pos < 34:
            end = pos
        window = in_data[start:end]

        best = (-1, 0)
        for ln in range(3, 35):  # encoded as (len-3) in 5 bits
            if pos + ln > len(in_data):
                break
            needle = in_data[pos:pos + ln]
            idx = window.find(needle)
            if idx != -1 and (start + idx + 1) <= pos:
                best = (pos - (start + idx), ln)
            else:
                return best
        return best

    flags = bytearray()
    tokens = bytearray()

    bit_acc = 0
    op_count = 0
    pos = 0
    produced = 0

    while pos < len(in_data):
        backref, ln = find_match(pos)

        if backref == -1:
            tokens.append(in_data[pos])
            pos += 1
            produced += 1
            is_lz = 0
        else:
            tok = (backref << 5) | (ln - 3)
            tokens.append((tok >> 8) & 0xFF)
            tokens.append(tok & 0xFF)
            pos += ln
            produced += ln
            is_lz = 1

        if op_count > 0 and (op_count % 8 == 0):
            flags.append(bit_acc)
            bit_acc = 0

        bit_acc = ((bit_acc << 1) | is_lz) & 0xFF
        op_count += 1

    if op_count % 8:
        bit_acc = (bit_acc << (8 - (op_count % 8))) & 0xFF
        flags.append(bit_acc)

    data_offset = 12 + math.ceil(op_count / 8)
    out = bytearray()
    out += produced.to_bytes(4, "big")
    out += op_count.to_bytes(4, "big")
    out += data_offset.to_bytes(4, "big")
    out += flags
    out += tokens
    return bytes(out)


def rebuild_wrapper(original_bin: bytes, new_comp: bytes, new_raw_size: int) -> bytes:
    header_size, _, _ = parse_wrapper(original_bin)
    header = bytearray(original_bin[:header_size])
    new_file_size = header_size + len(new_comp)
    header[0x04:0x08] = new_file_size.to_bytes(4, "big")
    header[0x28:0x2C] = new_raw_size.to_bytes(4, "big")
    header[0x2C:0x30] = len(new_comp).to_bytes(4, "big")
    return bytes(header) + new_comp


# -----------------------------
# TGA helpers (16-bit template)
# -----------------------------

def tga_info(tga: bytes):
    if len(tga) < 18:
        raise ValueError("TGA too short")
    id_len = tga[0]
    cmap_type = tga[1]
    img_type = tga[2]
    w = int.from_bytes(tga[12:14], "little")
    h = int.from_bytes(tga[14:16], "little")
    bpp = tga[16]
    desc = tga[17]
    cmap_len = int.from_bytes(tga[5:7], "little")
    cmap_bits = tga[7]
    cmap_bytes = ((cmap_len * cmap_bits) + 7) // 8 if cmap_type else 0
    img_off = 18 + id_len + cmap_bytes
    img_bytes = w * h * ((bpp + 7) // 8)
    if img_off + img_bytes > len(tga):
        raise ValueError("Invalid TGA image data")
    return {
        "id_len": id_len, "cmap_type": cmap_type, "img_type": img_type,
        "w": w, "h": h, "bpp": bpp, "desc": desc,
        "img_off": img_off, "img_bytes": img_bytes
    }


def extract_alpha_mask_from_tga16(tga: bytes):
    info = tga_info(tga)
    if info["img_type"] != 2 or info["cmap_type"] != 0 or info["bpp"] != 16:
        raise ValueError("Template must be uncompressed true-color 16-bit TGA")
    w, h = info["w"], info["h"]
    top_origin = bool(info["desc"] & 0x20)
    mask = [[0] * w for _ in range(h)]
    p = info["img_off"]
    for row_stored in range(h):
        y = row_stored if top_origin else (h - 1 - row_stored)
        for x in range(w):
            px = int.from_bytes(tga[p:p+2], "little")
            p += 2
            mask[y][x] = (px >> 15) & 1
    return info, mask


def png_to_tga16_using_template(image_path: Path, template_tga: bytes) -> bytes:
    info, alpha_mask = extract_alpha_mask_from_tga16(template_tga)
    w, h = info["w"], info["h"]
    top_origin = bool(info["desc"] & 0x20)

    with Image.open(image_path) as im:
        rgba = im.convert("RGBA")
        if rgba.size != (w, h):
            rgba = rgba.resize((w, h), Image.NEAREST)

        out = bytearray()
        # preserve header + id/cmap exactly
        out += template_tga[:info["img_off"]]

        for row_stored in range(h):
            y = row_stored if top_origin else (h - 1 - row_stored)
            for x in range(w):
                r, g, b, _a = rgba.getpixel((x, y))
                r5 = (r * 31 + 127) // 255
                g5 = (g * 31 + 127) // 255
                b5 = (b * 31 + 127) // 255
                a1 = alpha_mask[y][x]  # preserve original 1-bit alpha
                px = (b5) | (g5 << 5) | (r5 << 10) | (a1 << 15)  # A1R5G5B5
                out += px.to_bytes(2, "little")

        # preserve trailer bytes (if any)
        out += template_tga[info["img_off"] + info["img_bytes"]:]
        return bytes(out)


# -----------------------------
# Commands
# -----------------------------

def unpack(bin_path: Path):
    blob = bin_path.read_bytes()
    header_size, raw_size, comp_size = parse_wrapper(blob)
    comp = blob[header_size:header_size + comp_size]
    tga = cv1000_decompress(comp)

    if raw_size and len(tga) != raw_size:
        raise ValueError(f"Raw size mismatch: header says {raw_size:#x}, got {len(tga):#x}")

    out_dir = Path.cwd() / "extracted-gfx"
    out_dir.mkdir(parents=True, exist_ok=True)

    # write into ./extracted-gfx, not next to the source .bin
    tga_path = out_dir / f"{bin_path.stem}.tga"
    png_path = out_dir / f"{bin_path.stem}.png"

    tga_path.write_bytes(tga)

    # color-visible PNG (drop alpha)
    with Image.open(io.BytesIO(tga)) as im:
        im.convert("RGB").save(png_path, "PNG")

    info = tga_info(tga)
    print(f"Unpacked: {bin_path.name}")
    print(f"  -> {tga_path}")
    print(f"  -> {png_path} (color-visible)")
    print(f"  TGA: {info['w']}x{info['h']} {info['bpp']}bpp type={info['img_type']}")


def repack(original_bin_path: Path, edited_image_path: Path):
    original_bin = original_bin_path.read_bytes()
    header_size, raw_size, comp_size = parse_wrapper(original_bin)
    old_comp = original_bin[header_size:header_size + comp_size]
    template_tga = cv1000_decompress(old_comp)

    if edited_image_path.suffix.lower() == ".tga":
        new_tga = edited_image_path.read_bytes()
        a = tga_info(template_tga)
        b = tga_info(new_tga)
        if (a["w"], a["h"]) != (b["w"], b["h"]):
            raise ValueError("Edited TGA size does not match original")
    else:
        new_tga = png_to_tga16_using_template(edited_image_path, template_tga)

    new_comp = cv1000_compress(new_tga)
    new_bin = rebuild_wrapper(original_bin, new_comp, len(new_tga))

    out_dir = Path.cwd() / "extracted-gfx"
    out_dir.mkdir(parents=True, exist_ok=True)

    # write into ./extracted-gfx, not next to the source .bin
    out_path = out_dir / f"{original_bin_path.stem}_repacked.bin"
    out_path.write_bytes(new_bin)

    print(f"Repacked: {original_bin_path.name}")
    print(f"  from: {edited_image_path.name}")
    print(f"  -> {out_path}")


def main():
    if len(sys.argv) < 3:
        print("Usage:")
        print("  ./cave-gfx.py unpack <file1.bin> [file2.bin ...]")
        print("  ./cave-gfx.py repack <original.bin> <edited.png|edited.tga>")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    try:
        if cmd == "unpack":
            # allow multiple .bin files
            if len(sys.argv) < 3:
                raise ValueError("unpack needs at least 1 .bin file")
            for p in sys.argv[2:]:
                unpack(Path(p))

        elif cmd == "repack":
            # one pair at a time: original + edited image
            if len(sys.argv) != 4:
                raise ValueError("repack needs original.bin and edited image")
            repack(Path(sys.argv[2]), Path(sys.argv[3]))

        else:
            raise ValueError(f"Unknown command: {cmd}")

    except Exception as e:
        print("Error:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
