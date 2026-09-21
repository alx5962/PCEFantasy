"""
extract_rom.py - NES ROM extractor for pceconvert
Validates MD5 and extracts all binary data chunks from the NES ROM
into work/dat/ using bins.xml as the manifest. Fully autonomous.
"""

import hashlib
import os
import sys
import xml.etree.ElementTree as ET

EXPECTED_MD5 = "4156f66c0fac36222b5a1da05db85d68"
INES_HEADER_SIZE = 16

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BINS_XML = os.path.join(SCRIPT_DIR, "bins.xml")
DAT_DIR  = os.path.join(SCRIPT_DIR, "work", "dat")


def validate_md5(rom_bytes):
    actual = hashlib.md5(rom_bytes).hexdigest()
    if actual != EXPECTED_MD5:
        print(f"\n  ERROR: ROM MD5 mismatch!")
        print(f"  Expected : {EXPECTED_MD5}")
        print(f"  Got      : {actual}")
        print(f"\n  Please provide the correct Legend of Zelda (USA) .nes ROM.")
        sys.exit(1)
    print(f"  MD5 OK : {actual}")


def extract_bins(rom_bytes):
    if not os.path.isfile(BINS_XML):
        print(f"  ERROR: bins.xml not found at: {BINS_XML}")
        sys.exit(1)

    os.makedirs(DAT_DIR, exist_ok=True)

    tree = ET.parse(BINS_XML)
    root = tree.getroot()

    count = 0
    for binary in root.findall("Binary"):
        offset  = int(binary.get("Offset"))
        length  = int(binary.get("Length"))
        relname = binary.get("FileName")

        file_offset = offset + INES_HEADER_SIZE
        chunk = rom_bytes[file_offset : file_offset + length]

        if len(chunk) != length:
            print(f"  WARNING: {relname}: expected {length} bytes, got {len(chunk)}")

        dest_path = os.path.join(DAT_DIR, os.path.basename(relname))
        with open(dest_path, "wb") as f:
            f.write(chunk)

        print(f"  Extracted {os.path.basename(relname):45s}  {len(chunk):6d} bytes")
        count += 1

    return count


def run(rom_path):
    print(f"\n[1/2] Validating ROM: {os.path.basename(rom_path)}")
    with open(rom_path, "rb") as f:
        rom_bytes = f.read()
    validate_md5(rom_bytes)

    print(f"\n[2/2] Extracting graphics and data from ROM...")
    count = extract_bins(rom_bytes)
    print(f"\n  Done - {count} files extracted to {DAT_DIR}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_rom.py <path/to/zelda.nes>")
        sys.exit(1)
    run(sys.argv[1])
