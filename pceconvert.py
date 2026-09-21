#!/usr/bin/env python3
"""
pceconvert.py - Legend of Zelda NES -> PC Engine ROM Converter
Usage:
  python pceconvert.py "path/to/Legend of Zelda, The (USA).nes"   (CLI mode)
  python pceconvert.py                                              (GUI mode - file picker)

COMPLETELY AUTONOMOUS:
All tools, scripts, intermediate files, and outputs remain strictly inside pceconvert/.
No external folders or files outside pceconvert/ are referenced or modified.
"""

import os
import sys
import shutil
import subprocess

# -----------------------------------------------------------------------
# Resolve all paths inside this directory (pceconvert/)
# -----------------------------------------------------------------------
PCECONVERT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR        = os.path.join(PCECONVERT_DIR, "src")
TOOLS_BIN      = os.path.join(PCECONVERT_DIR, "tools", "bin")
TOOLS_INCLUDE  = os.path.join(PCECONVERT_DIR, "tools", "include", "hucc")
BUILD_DIR      = os.path.join(PCECONVERT_DIR, "build")

HUCC_EXE  = os.path.join(TOOLS_BIN, "hucc.exe")
PCEAS_EXE = os.path.join(TOOLS_BIN, "pceas.exe")


def banner(text, char="=", width=72):
    print(char * width)
    print(f"  {text}")
    print(char * width)


def check_tools():
    """Verify bundled HuCC executables and source directory are present."""
    missing = []
    for exe in [HUCC_EXE, PCEAS_EXE]:
        if not os.path.isfile(exe):
            missing.append(exe)
    if missing:
        print("  ERROR: Bundled HuCC tools not found:")
        for m in missing:
            print(f"    {m}")
        sys.exit(1)
    if not os.path.isdir(TOOLS_INCLUDE):
        print(f"  ERROR: HuCC include directory not found: {TOOLS_INCLUDE}")
        sys.exit(1)
    if not os.path.isfile(os.path.join(SRC_DIR, "main.c")):
        print(f"  ERROR: src/main.c not found: {os.path.join(SRC_DIR, 'main.c')}")
        sys.exit(1)


def pick_rom_gui():
    """Open a tkinter file picker and return the selected .nes path."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        print("  ERROR: tkinter not available. Run with ROM path as argument:")
        print("    python pceconvert.py \"path/to/zelda.nes\"")
        sys.exit(1)

    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", True)
    path = filedialog.askopenfilename(
        title="Select Legend of Zelda (USA) .nes ROM",
        filetypes=[("NES ROM files", "*.nes"), ("All files", "*.*")]
    )
    root.destroy()
    if not path:
        print("  No file selected. Aborting.")
        sys.exit(0)
    return path


def run_step(label, cmd, cwd=None, env=None, use_shell=False):
    """Run a subprocess step, streaming output. Exit on failure."""
    cmd_strs = [str(c) for c in cmd]
    print(f"\n  > {' '.join(cmd_strs)}")
    result = subprocess.run(
        cmd_strs,
        cwd=cwd,
        env=env,
        text=True,
        shell=use_shell
    )
    if result.returncode != 0:
        print(f"\n  ERROR: {label} failed (exit code {result.returncode})")
        sys.exit(result.returncode)


def main():
    banner("Legend of Zelda NES -> PC Engine ROM Converter")

    # ----------------------------------------------------------------
    # Step 0: Prerequisite checks
    # ----------------------------------------------------------------
    print("\n[0/6] Checking bundled HuCC toolchain and sources...")
    check_tools()
    print("  hucc.exe  : OK")
    print("  pceas.exe : OK")
    print("  include/  : OK")
    print("  src/main.c: OK")

    # ----------------------------------------------------------------
    # Step 1: Get ROM path (CLI arg or GUI picker)
    # ----------------------------------------------------------------
    if len(sys.argv) >= 2:
        rom_path = os.path.abspath(sys.argv[1])
        print(f"\n[1/6] ROM path (from argument): {rom_path}")
    else:
        print("\n[1/6] No ROM path given - opening file picker...")
        rom_path = pick_rom_gui()
        print(f"  Selected: {rom_path}")

    if not os.path.isfile(rom_path):
        print(f"  ERROR: File not found: {rom_path}")
        sys.exit(1)

    # ----------------------------------------------------------------
    # Step 2: Validate MD5 + extract .dat files from ROM into work/dat/
    # ----------------------------------------------------------------
    print(f"\n[2/6] Validating ROM and extracting graphics data...")
    extract_script = os.path.join(PCECONVERT_DIR, "extract_rom.py")
    run_step(
        "ROM extraction",
        [sys.executable, extract_script, rom_path]
    )

    # ----------------------------------------------------------------
    # Step 3: Convert NES assets to PC Engine format into src/
    # ----------------------------------------------------------------
    print(f"\n[3/6] Converting NES assets to PC Engine format...")
    run_step(
        "convert_zelda.py",
        [sys.executable, os.path.join(PCECONVERT_DIR, "convert_zelda.py")]
    )
    run_step(
        "generate_treasures.py",
        [sys.executable, os.path.join(PCECONVERT_DIR, "generate_treasures.py")]
    )

    # ----------------------------------------------------------------
    # Step 4: Compile C source with HuCC
    # ----------------------------------------------------------------
    print(f"\n[4/6] Compiling src/main.c with HuCC...")
    # hucc.exe is a mingw binary: it cannot parse absolute Windows paths
    # in PCE_INCLUDE. Compute the path relative to src/ (the cwd).
    pce_include_rel = os.path.relpath(TOOLS_INCLUDE, SRC_DIR)

    env = os.environ.copy()
    env["PATH"] = TOOLS_BIN + os.pathsep + env.get("PATH", "")
    # Use relative path so mingw hucc.exe can resolve it correctly
    env["PCE_INCLUDE"] = pce_include_rel

    # shell=True lets Windows resolve "hucc.exe" / "pceas.exe" via PATH
    run_step(
        "HuCC compile",
        ["hucc.exe", "-O2", "-s", "main.c"],
        cwd=SRC_DIR,
        env=env,
        use_shell=True
    )

    # ----------------------------------------------------------------
    # Step 5: Assemble into .pce ROM with pceas
    # ----------------------------------------------------------------
    print(f"\n[5/6] Assembling PC Engine ROM with pceas...")
    run_step(
        "pceas assemble",
        ["pceas.exe", "--hucc", "-I", pce_include_rel, "-pad", "-raw", "main.s"],
        cwd=SRC_DIR,
        env=env,
        use_shell=True
    )

    # ----------------------------------------------------------------
    # Step 6: Copy output ROM to pceconvert/build/
    # ----------------------------------------------------------------
    print(f"\n[6/6] Copying output ROM to build/...")
    os.makedirs(BUILD_DIR, exist_ok=True)
    src_pce  = os.path.join(SRC_DIR, "main.pce")
    dest_pce = os.path.join(BUILD_DIR, "zelda.pce")

    if not os.path.isfile(src_pce):
        print(f"  ERROR: main.pce not found at {src_pce}")
        sys.exit(1)

    shutil.copy2(src_pce, dest_pce)
    size = os.path.getsize(dest_pce)

    print()
    banner("SUCCESS!", "=")
    print(f"  Output ROM : {dest_pce}")
    print(f"  Size       : {size:,} bytes")
    print("=" * 72)

    if size != 131072:
        print(f"  WARNING: Expected 131,072 bytes but got {size:,}")


if __name__ == "__main__":
    main()
