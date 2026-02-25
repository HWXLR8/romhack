#!/usr/bin/env python3
#
# Unpack/repack the custom .bin sound bank you uploaded (contains embedded RIFF/WAVE XMA2 files).
# This script preserves the original entry metadata and rebuilds the container.
#
# Usage:
#   ./audio.py unpack se.bin out_dir
#   ./audio.py repack out_dir se_new.bin
#
# After unpack:
#   out_dir/
#     manifest.json
#     files/
#       se01d.xma
#       se02a.xma
#       ...
#
# You can replace the files in out_dir/files/ (keep names the same), then repack.

import argparse
import json
from pathlib import Path

HEADER_SIZE = 36
ENTRY_SIZE = 276
NAME_FIELD_SIZE = 260


def u32be(b: bytes) -> int:
    return int.from_bytes(b, "big")


def p32be(n: int) -> bytes:
    return int(n).to_bytes(4, "big")


def parse_bank(data: bytes):
    if len(data) < HEADER_SIZE:
        raise ValueError("File too small to be a valid bank")

    magic = data[:4]
    total_size = u32be(data[4:8])
    data_start = u32be(data[8:12])
    count = u32be(data[12:16])
    reserved = data[16:36]

    expected_data_start = HEADER_SIZE + count * ENTRY_SIZE
    if data_start != expected_data_start:
        raise ValueError(
            f"Unexpected data_start={data_start}, expected {expected_data_start} "
            f"(count={count}, entry_size={ENTRY_SIZE})"
        )

    if len(data) < data_start:
        raise ValueError("Truncated file (header/table runs past EOF)")

    entries = []
    for i in range(count):
        eoff = HEADER_SIZE + i * ENTRY_SIZE
        e = data[eoff:eoff + ENTRY_SIZE]

        index_byte = e[0]               # observed 0..N-1
        zero1 = e[1]                    # observed 0
        zero2 = e[2]                    # observed 0
        entry_type = e[3]               # observed 0x02
        size = u32be(e[4:8])            # big-endian
        reserved_u32 = u32be(e[8:12])   # observed 0
        off = u32be(e[12:16])           # big-endian
        raw_name = e[16:16 + NAME_FIELD_SIZE]
        name = raw_name.split(b"\x00", 1)[0].decode("utf-8", errors="replace")

        if off + size > len(data):
            raise ValueError(f"Entry {i} ('{name}') runs past EOF")

        entries.append({
            "i": i,
            "index_byte": index_byte,
            "zero1": zero1,
            "zero2": zero2,
            "entry_type": entry_type,
            "size": size,
            "reserved_u32": reserved_u32,
            "offset": off,
            "name": name,
        })

    # Optional sanity check (header total size)
    if total_size != len(data):
        print(f"Warning: header total_size={total_size}, actual file size={len(data)}")

    return {
        "magic_hex": magic.hex(),
        "reserved_hex": reserved.hex(),
        "count": count,
        "entries": entries,
    }


def safe_relpath(name: str) -> Path:
    # Converts ".\\foo\\bar.xma" or "./foo/bar.xma" to a safe relative path
    n = name.replace("\\", "/")
    while n.startswith("./") or n.startswith(".\\") or n.startswith("/"):
        if n.startswith("./") or n.startswith(".\\"):
            n = n[2:]
        else:
            n = n[1:]

    p = Path(n)
    clean_parts = [part for part in p.parts if part not in ("..", "")]
    return Path(*clean_parts) if clean_parts else Path("unnamed.bin")


def unpack(bin_path: Path, out_dir: Path):
    data = bin_path.read_bytes()
    bank = parse_bank(data)

    out_dir.mkdir(parents=True, exist_ok=True)
    files_dir = out_dir / "files"
    files_dir.mkdir(exist_ok=True)

    manifest = {
        "format": "custom_xma_bank_v1",
        "source_file": bin_path.name,
        "magic_hex": bank["magic_hex"],
        "reserved_hex": bank["reserved_hex"],
        "header_size": HEADER_SIZE,
        "entry_size": ENTRY_SIZE,
        "name_field_size": NAME_FIELD_SIZE,
        "entries": [],
    }

    for ent in bank["entries"]:
        rel = safe_relpath(ent["name"])
        out_path = files_dir / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)

        blob = data[ent["offset"]:ent["offset"] + ent["size"]]
        out_path.write_bytes(blob)

        manifest["entries"].append({
            "name": ent["name"],  # original path stored in the bank
            "stored_path": str(Path("files") / rel).replace("\\", "/"),
            "index_byte": ent["index_byte"],
            "zero1": ent["zero1"],
            "zero2": ent["zero2"],
            "entry_type": ent["entry_type"],
            "reserved_u32": ent["reserved_u32"],
        })

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Unpacked {len(bank['entries'])} files to: {out_dir}")


def repack(in_dir: Path, out_bin: Path):
    manifest_path = in_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != "custom_xma_bank_v1":
        raise ValueError("Unsupported manifest format")

    entries_meta = manifest["entries"]
    count = len(entries_meta)

    magic = bytes.fromhex(manifest["magic_hex"])
    if len(magic) != 4:
        raise ValueError("manifest magic_hex must be 4 bytes")

    reserved = bytes.fromhex(manifest["reserved_hex"])
    if len(reserved) != 20:
        raise ValueError("manifest reserved_hex must be 20 bytes")

    data_start = HEADER_SIZE + count * ENTRY_SIZE
    offset = data_start

    entry_records = []
    file_blobs = []

    for i, meta in enumerate(entries_meta):
        stored_path = in_dir / meta["stored_path"]
        if not stored_path.exists():
            raise FileNotFoundError(f"Missing payload file: {stored_path}")

        blob = stored_path.read_bytes()
        name_b = meta["name"].encode("utf-8")
        if len(name_b) >= NAME_FIELD_SIZE:
            raise ValueError(f"Entry name too long ({len(name_b)} bytes): {meta['name']!r}")

        entry = bytearray(ENTRY_SIZE)
        entry[0] = int(meta.get("index_byte", i)) & 0xFF
        entry[1] = int(meta.get("zero1", 0)) & 0xFF
        entry[2] = int(meta.get("zero2", 0)) & 0xFF
        entry[3] = int(meta.get("entry_type", 2)) & 0xFF
        entry[4:8] = p32be(len(blob))
        entry[8:12] = p32be(int(meta.get("reserved_u32", 0)))
        entry[12:16] = p32be(offset)
        entry[16:16 + len(name_b)] = name_b
        # remaining bytes are already zero

        entry_records.append(bytes(entry))
        file_blobs.append(blob)
        offset += len(blob)  # no alignment in the sample format

    total_size = offset

    header = bytearray(HEADER_SIZE)
    header[:4] = magic
    header[4:8] = p32be(total_size)
    header[8:12] = p32be(data_start)
    header[12:16] = p32be(count)
    header[16:36] = reserved

    out_bin.parent.mkdir(parents=True, exist_ok=True)
    with out_bin.open("wb") as f:
        f.write(header)
        for e in entry_records:
            f.write(e)
        for blob in file_blobs:
            f.write(blob)

    print(f"Repacked {count} files to: {out_bin}")


def main():
    ap = argparse.ArgumentParser(
        description="Unpack/repack custom .bin sound bank with embedded RIFF/WAVE (XMA2)"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_unpack = sub.add_parser("unpack", help="Extract files and write manifest.json")
    p_unpack.add_argument("bank", type=Path, help="Input .bin file")
    p_unpack.add_argument("out_dir", type=Path, help="Output directory")

    p_repack = sub.add_parser("repack", help="Rebuild .bin from unpacked directory")
    p_repack.add_argument("in_dir", type=Path, help="Directory containing manifest.json and files/")
    p_repack.add_argument("out_bank", type=Path, help="Output .bin file")

    args = ap.parse_args()

    if args.cmd == "unpack":
        unpack(args.bank, args.out_dir)
    elif args.cmd == "repack":
        repack(args.in_dir, args.out_bank)


if __name__ == "__main__":
    main()
