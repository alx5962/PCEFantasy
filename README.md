# The Legend of Zelda — NES to PC Engine Converter

Convert the original NES Legend of Zelda ROM into a playable **PC Engine** ROM.

---

## STATUS

This is a proof of concept, Don't expect anything to run correctly or accurately.

---

## Prerequisites

- **Python 3.x** — https://www.python.org/  
- **Pillow** image library:
  ```
  pip install pillow
  ```
- **The Legend of Zelda (USA) `.nes` ROM**  
  MD5: `4156f66c0fac36222b5a1da05db85d68`  
  The converter validates this exact hash. No other version will be accepted.

> **No compiler installation needed.**  
> The HuCC PC Engine toolchain is bundled in the `tools/` directory.

---

## Usage

### GUI Mode (double-click)

1. Double-click **`pceconvert.bat`**
2. A file picker dialog opens — select your `Legend of Zelda, The (USA).nes` ROM
3. The converter runs automatically and prints progress to the console
4. When finished, the output ROM is at `build\zelda.pce`

### CLI Mode

```
python pceconvert.py "path\to\Legend of Zelda, The (USA).nes"
```

Or using the batch launcher with a path argument:

```
pceconvert.bat "path\to\Legend of Zelda, The (USA).nes"
```

---

## Output

```
pceconvert\build\zelda.pce   (131,072 bytes)
```

Load `zelda.pce` in any PC Engine emulator that supports HuCard ROMs.


---

## Troubleshooting

**"MD5 mismatch" error**  
Make sure you are using the **Legend of Zelda (USA)** ROM, not a Japanese or patched version.  
Expected MD5: `4156f66c0fac36222b5a1da05db85d68`

**"Python not found"**  
Install Python 3.x from https://www.python.org/ and make sure "Add to PATH" is checked during install.

**"Pillow not installed"**  
Run: `pip install pillow`

**"HuCC tools not found"**  
The `tools\bin\` folder must exist alongside `pceconvert.bat`. Do not move `pceconvert.bat` out of the `pceconvert\` folder.

---

## Credits

### HuCC PC Engine Compiler

The HuCC compiler and assembler bundled in `tools/` were originally created by:

- **Zeograd**
- **David Michel** (creator of the MagicKit assembler)
- **David Shadoff**

Maintained and extended by the PC Engine homebrew community.

🔗 **HuCC GitHub**: https://github.com/pce-devel/huc

### Legend of Zelda NES Disassembly

This converter uses the Legend of Zelda NES disassembly project for its ROM data extraction manifests.

🔗 https://github.com/mstan/LegendOfZeldaNESRecomp
