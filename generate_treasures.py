import os
import struct
from PIL import Image

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, "src")
DAT_DIR = os.path.join(SCRIPT_DIR, "work", "dat")

def load_data():
    global comm_sp, comm_bg, misc, demo_sp, demo_bg, ppu_spr, ppu_bg
    with open(os.path.join(DAT_DIR, "CommonSpritePatterns.dat"), "rb") as f: comm_sp = f.read()
    with open(os.path.join(DAT_DIR, "CommonBackgroundPatterns.dat"), "rb") as f: comm_bg = f.read()
    with open(os.path.join(DAT_DIR, "CommonMiscPatterns.dat"), "rb") as f: misc = f.read()
    with open(os.path.join(DAT_DIR, "DemoSpritePatterns.dat"), "rb") as f: demo_sp = f.read()
    with open(os.path.join(DAT_DIR, "DemoBackgroundPatterns.dat"), "rb") as f: demo_bg = f.read()
    ppu_spr = comm_sp + demo_sp
    ppu_bg = comm_bg + demo_bg + misc

def get_8x8(table_idx, tile_idx):
    table = ppu_bg if table_idx == 1 else ppu_spr
    off = tile_idx * 16
    if off + 16 > len(table):
        return [[0]*8 for _ in range(8)]
    raw = table[off : off + 16]
    pixels = []
    for y in range(8):
        b0 = raw[y]
        b1 = raw[y + 8]
        pixels.append([((b0 >> (7 - x)) & 1) | (((b1 >> (7 - x)) & 1) << 1) for x in range(8)])
    return pixels

def get_8x16(t):
    table = t & 1
    base = t & 0xFE
    top = get_8x8(table, base)
    btm = get_8x8(table, base + 1)
    pixels = []
    for y in range(8): pixels.append(top[y])
    for y in range(8): pixels.append(btm[y])
    return pixels

# Anim tables from Z_01.asm
ItemIdToSlot = [
    0x01, 0x00, 0x00, 0x00, 0x06, 0x05, 0x04, 0x04,
    0x02, 0x02, 0x03, 0x0D, 0x09, 0x0C, 0x1B, 0x1C,
    0x08, 0x0A, 0x0B, 0x0B, 0x0E, 0x0F, 0x10, 0x11,
    0x16, 0x17, 0x18, 0x1A, 0x1F, 0x1D, 0x1E, 0x07,
    0x07, 0x15, 0x19, 0x14
]

ItemIdToDescriptor = [
    0x14, 0x21, 0x22, 0x23, 0x01, 0x01, 0x21, 0x22,
    0x21, 0x22, 0x01, 0x01, 0x01, 0x01, 0x01, 0x15,
    0x01, 0x01, 0x21, 0x22, 0x01, 0x01, 0x01, 0x01,
    0x11, 0x11, 0x10, 0x01, 0x01, 0x01, 0x01, 0x11,
    0x22, 0x01, 0x10, 0x12
]

ItemSlotToPaletteOffsetsOrValues = [
    0xFF, 0x01, 0xFF, 0x00, 0x00, 0x02, 0x02, 0x00,
    0x01, 0x00, 0x02, 0x00, 0x00, 0x02, 0x02, 0x01,
    0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02
]

Anim_ItemFrameOffsets = [
    0x00, 0x03, 0x07, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E,
    0x0F, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17,
    0x18, 0x17, 0x18, 0x17, 0x19, 0x1B, 0x1C, 0x1D,
    0x1E, 0x1F, 0x20, 0x21, 0x1C, 0x22, 0x22, 0x26,
    0x27, 0x28, 0x29, 0x2B, 0x2E
]

Anim_ItemFrameTiles = [
    0x20, 0x82, 0x3C, 0x34, 0x70, 0x72, 0x74, 0x28,
    0x86, 0x3C, 0x2A, 0x26, 0x24, 0x22, 0x40, 0x4A,
    0x8A, 0x6C, 0x42, 0x46, 0x76, 0x2C, 0x4E, 0x4C,
    0x6A, 0x50, 0x52, 0x66, 0x32, 0x2E, 0x68, 0xF3,
    0x6E, 0xF2, 0x36, 0x38, 0x3A, 0x3C, 0x56, 0x48,
    0x78, 0x20, 0x82, 0x7A, 0x7C, 0x30, 0x64, 0x62
]

# Convert 16x16 pixel grid (values 0..3) into PCE VDC 16x16 sprite binary (128 bytes)
def make_pce_sprite_16x16(grid):
    out = bytearray(128)
    for y in range(16):
        r0 = 0
        r1 = 0
        r2 = 0
        r3 = 0
        for x in range(16):
            c = grid[y][x]
            bit = 15 - x
            if c & 1: r0 |= (1 << bit)
            if c & 2: r1 |= (1 << bit)
            if c & 4: r2 |= (1 << bit)
            if c & 8: r3 |= (1 << bit)
        # Plane 0 & 1
        out[y * 2] = r0 & 0xFF
        out[y * 2 + 1] = (r0 >> 8) & 0xFF
        out[32 + y * 2] = r1 & 0xFF
        out[32 + y * 2 + 1] = (r1 >> 8) & 0xFF
        # Plane 2 & 3
        out[64 + y * 2] = r2 & 0xFF
        out[64 + y * 2 + 1] = (r2 >> 8) & 0xFF
        out[96 + y * 2] = r3 & 0xFF
        out[96 + y * 2 + 1] = (r3 >> 8) & 0xFF
    return out

def render_authentic_item(item_id):
    slot = ItemIdToSlot[item_id]
    desc = ItemIdToDescriptor[item_id]
    val = desc & 0x0F
    pal_val = ItemSlotToPaletteOffsetsOrValues[slot] if slot < len(ItemSlotToPaletteOffsetsOrValues) else 0
    
    if slot in [0x16, 0x19, 0x1A, 0x1B]:
        pal = 1
    elif slot in [0, 2, 4, 7, 0x0B]:
        pal = (pal_val + val) & 3
        if slot == 0 and pal == 2: slot = 0x20
    else:
        pal = pal_val & 3
        
    offset = Anim_ItemFrameOffsets[slot] if slot < len(Anim_ItemFrameOffsets) else 0
    t0 = Anim_ItemFrameTiles[offset]
    
    grid = [[0]*16 for _ in range(16)]
    
    # Exact NES Zelda Anim_WriteSpecificItemSprites logic (Z_01.asm line 5329)
    if t0 == 0xF3 or (0x20 <= t0 < 0x62):
        # Narrow (8x16 centered horizontally at x=4..11)
        sp0 = get_8x16(t0)
        for y in range(16):
            for x in range(8):
                grid[y][x + 4] = sp0[y][x]
    elif t0 < 0x6C:
        # Slim mirrored with 1px overlap (sep = 7, e.g. Clock 0x66, Heart Container 0x68, Compass 0x6A)
        sp0 = get_8x16(t0)
        for y in range(16):
            for x in range(8):
                if sp0[y][x]:
                    grid[y][x] = sp0[y][x]
                    grid[y][7 + (7 - x)] = sp0[y][x]
    elif t0 < 0x7C:
        # Mirrored with sep = 8 (e.g. Raft 0x6C, Triforce 0x6E, Ladder 0x76)
        sp0 = get_8x16(t0)
        for y in range(16):
            for x in range(8):
                if sp0[y][x]:
                    grid[y][x] = sp0[y][x]
                    grid[y][8 + (7 - x)] = sp0[y][x]
    else:
        # Wide two distinct tiles
        sp0 = get_8x16(t0)
        sp1 = get_8x16(t0 + 2)
        for y in range(16):
            for x in range(8):
                if sp0[y][x]: grid[y][x] = sp0[y][x]
                if sp1[y][x]: grid[y][x + 8] = sp1[y][x]
                
    # Authentic demo palette overrides
    if item_id == 0x1B: pal = 0 # Triforce gold
    elif item_id == 0x1A: pal = 2 # Container heart red
    elif item_id == 0x22: pal = 2 # Heart red
    elif item_id == 0x23: pal = 2 # Fairy peach/red
    
    return grid, pal

# Link holding sign 48x48 (3x3 16x16 sprites)
def make_link_holding_sign_sprites():
    tiles = [
        0xE0, 0xE2, 0xEC, 0xEE, 0xF8, 0xFA,
        0xE4, 0xE6, 0xF0, 0xF2, 0xFC, 0xFE,
        0xE8, 0xEA, 0xF4, 0xF6, 0xDC, 0xDE,
        0x00, 0x00, 0x78, 0x78, 0x00, 0x00
    ]
    def get_8x8_demo(vram_idx):
        off = (vram_idx - 0x70) * 16
        if off < 0 or off + 16 > len(demo_sp):
            return [[0]*8 for _ in range(8)]
        raw = demo_sp[off : off + 16]
        pixels = []
        for y in range(8):
            b0 = raw[y]
            b1 = raw[y + 8]
            row = [((b0 >> (7 - x)) & 1) | (((b1 >> (7 - x)) & 1) << 1) for x in range(8)]
            pixels.append(row)
        return pixels

    big_grid = [[0]*48 for _ in range(48)]
    for r in range(3): # top 3 rows of 8x16 sprites (48x48)
        for c in range(6):
            t_base = tiles[r * 6 + c]
            if t_base != 0:
                top = get_8x8_demo(t_base)
                btm = get_8x8_demo(t_base + 1)
                for y in range(8):
                    for x in range(8):
                        big_grid[r*16 + y][c*8 + x] = top[y][x]
                        big_grid[r*16 + 8 + y][c*8 + x] = btm[y][x]
                        
    # Add feet from row 3 (c=2 and c=3) at bottom
    foot_l = get_8x8_demo(0x78)
    for y in range(8):
        for x in range(8):
            if foot_l[y][x]: big_grid[40 + y][16 + x] = foot_l[y][x]
            # right foot mirrored
            if foot_l[y][x]: big_grid[40 + y][31 - x] = foot_l[y][x]

    # Chop 48x48 into 3x3 16x16 sprites (9 sprites)
    sprites_9 = []
    for sy in range(3):
        for sx in range(3):
            sp_grid = [[0]*16 for _ in range(16)]
            for y in range(16):
                for x in range(16):
                    sp_grid[y][x] = big_grid[sy*16 + y][sx*16 + x]
            sprites_9.append(make_pce_sprite_16x16(sp_grid))
    return sprites_9

def generate_treasures():
    load_data()
    item_pairs = [
        (0x22, 0x1A, "HEART", "CONTAINER HEART"),
        (0x23, 0x21, "FAIRY", "CLOCK"),
        (0x18, 0x0F, "RUPY", "5 RUPIES"),
        (0x1F, 0x20, "LIFE POTION", "2ND POTION"),
        (0x15, 0x04, "LETTER", "FOOD"),
        (0x01, 0x02, "SWORD", "WHITE SWORD"),
        (0x03, 0x1C, "MAGICAL SWORD", "MAGICAL SHIELD"),
        (0x1D, 0x1E, "BOOMERANG", "MAGICAL BOOMERANG"),
        (0x00, 0x0A, "BOMB", "BOW"),
        (0x08, 0x09, "ARROW", "SILVER ARROW"),
        (0x06, 0x07, "BLUE CANDLE", "RED CANDLE"),
        (0x12, 0x13, "BLUE RING", "RED RING"),
        (0x14, 0x05, "POWER BRACELET", "RECORDER"),
        (0x0C, 0x0D, "RAFT", "STEPLADDER"),
        (0x10, 0x11, "MAGICAL ROD", "BOOK OF MAGIC"),
        (0x19, 0x0B, "KEY", "MAGICAL KEY"),
        (0x17, 0x16, "MAP", "COMPASS"),
        (0x1B, 0x1B, "TRIFORCE", "")
    ]

    all_sprites = bytearray()
    left_pals = []
    right_pals = []

    # 18 pairs = 36 sprites (interleaved: pair i left at 2*i, right at 2*i+1)
    for lid, rid, _, _ in item_pairs:
        grid_l, pal_l = render_authentic_item(lid)
        all_sprites.extend(make_pce_sprite_16x16(grid_l))
        left_pals.append(pal_l)

        grid_r, pal_r = render_authentic_item(rid)
        all_sprites.extend(make_pce_sprite_16x16(grid_r))
        right_pals.append(pal_r)

    # 9 sprites for Link holding sign (indices 36..44)
    link_sprites = make_link_holding_sign_sprites()
    for sp in link_sprites:
        all_sprites.extend(sp)

    spr_bin_path = os.path.join(OUT_DIR, "treasures_sprites.bin")
    with open(spr_bin_path, "wb") as f:
        f.write(all_sprites)
    print(f"Wrote {len(all_sprites)} bytes ({len(all_sprites)//128} sprites) -> {spr_bin_path}")

    # Build full 160-row BAT (32 columns * 160 rows = 5120 words = 10,240 bytes)
    EMPTY_WORD = (0x0100 + 0x24) & 0x0FFF
    bat_words = [EMPTY_WORD] * (32 * 160)

    # Row 2: Ivy garland + " ALL OF TREASURES " + Ivy garland (top margin of 2 rows)
    HEADER_ROW = 2
    ivy_left = [0xE4, 0xE5, 0xE4, 0xE5, 0xE4, 0xE5, 0xE6]
    for c, t in enumerate(ivy_left):
        bat_words[HEADER_ROW * 32 + c] = ((0x0100 + t) & 0x0FFF) | (3 << 12)
    center_txt = " ALL OF TREASURES "
    for c, ch in enumerate(center_txt):
        if ch == ' ':
            t = 0x24
        elif '0' <= ch <= '9':
            t = ord(ch) - ord('0')
        else:
            t = 0x0A + (ord(ch) - ord('A'))
        bat_words[HEADER_ROW * 32 + 7 + c] = ((0x0100 + t) & 0x0FFF) | (0 << 12)
    ivy_right = [0xE6, 0xE4, 0xE5, 0xE4, 0xE5, 0xE4, 0xE5]
    for c, t in enumerate(ivy_right):
        bat_words[HEADER_ROW * 32 + 25 + c] = ((0x0100 + t) & 0x0FFF) | (3 << 12)

    # 18 item label pairs (aligned with HEADER_ROW = 2)
    # Each pair spaced by exactly 8 rows (64 pixels)
    text_events = [
        # (row, col, text, pal)
        (12, 7,  "HEART     CONTAINER", 0),
        (13, 20, "HEART", 0),
        (20, 7,  "FAIRY        CLOCK", 0),
        (28, 7,  "RUPY       5 RUPIES", 0),
        (36, 4,  "LIFE POTION   2ND POTION", 0),
        (44, 6,  "LETTER        FOOD", 0),
        (52, 7,  "SWORD        WHITE", 0),
        (53, 20, "SWORD", 0),
        (60, 6,  "MAGICAL      MAGICAL", 0),
        (61, 7,  "SWORD        SHIELD", 0),
        (68, 5,  "BOOMERANG     MAGICAL", 0),
        (69, 18, "BOOMERANG", 0),
        (76, 7,  "BOMB          BOW", 0),
        (84, 7,  "ARROW        SILVER", 0),
        (85, 20, "ARROW", 0),
        (92, 7,  "BLUE          RED", 0),
        (93, 6,  "CANDLE        CANDLE", 0),
        (100, 7, "BLUE          RED", 0),
        (101, 7, "RING          RING", 0),
        (108, 7, "POWER       RECORDER", 0),
        (109, 5, "BRACELET", 0),
        (116, 7, "RAFT       STEPLADDER", 0),
        (124, 6, "MAGICAL      BOOK OF", 0),
        (125, 8, "ROD         MAGIC", 0),
        (132, 8, "KEY        MAGICAL", 0),
        (133, 21, "KEY", 0),
        (140, 8, "MAP        COMPASS", 0),
        (149, 12, "TRIFORCE", 0)
    ]

    for row, col, txt, pal in text_events:
        for c, ch in enumerate(txt):
            if ch == ' ':
                t = 0x24
            elif '0' <= ch <= '9':
                t = ord(ch) - ord('0')
            else:
                t = 0x0A + (ord(ch) - ord('A'))
            bat_words[row * 32 + col + c] = ((0x0100 + t) & 0x0FFF) | (pal << 12)

    bat_bytes = bytearray()
    for w in bat_words:
        bat_bytes.extend(struct.pack("<H", w))

    bat_bin_path = os.path.join(OUT_DIR, "treasures_bat.bin")
    with open(bat_bin_path, "wb") as f:
        f.write(bat_bytes)
    print(f"Wrote {len(bat_bytes)} bytes (160 rows) -> {bat_bin_path}")

    # Generate C header with parallel arrays for text and palettes
    hdr_path = os.path.join(OUT_DIR, "treasures_data.h")
    with open(hdr_path, "w") as f:
        f.write("/* Auto-generated Treasures Data for PC Engine */\n")
        f.write("#ifndef _TREASURES_DATA_H_\n#define _TREASURES_DATA_H_\n\n")
        f.write(f"const unsigned char treasures_left_pals[18] = {{\n  " + ", ".join(str(p) for p in left_pals) + "\n};\n\n")
        f.write(f"const unsigned char treasures_right_pals[18] = {{\n  " + ", ".join(str(p) for p in right_pals) + "\n};\n\n")
        
        f.write(f"#define NUM_TREASURE_TEXTS {len(text_events)}\n\n")
        f.write("const unsigned char treasure_text_row[NUM_TREASURE_TEXTS] = {\n  " + ", ".join(str(e[0]) for e in text_events) + "\n};\n\n")
        f.write("const unsigned char treasure_text_col[NUM_TREASURE_TEXTS] = {\n  " + ", ".join(str(e[1]) for e in text_events) + "\n};\n\n")
        
        # Concatenate strings into a single byte array with null terminators
        offsets = []
        buf_bytes = []
        for e in text_events:
            offsets.append(len(buf_bytes))
            buf_bytes.extend(list(e[2].encode('ascii')) + [0])
            
        f.write("const unsigned int treasure_text_offset[NUM_TREASURE_TEXTS] = {\n  " + ", ".join(str(o) for o in offsets) + "\n};\n\n")
        f.write("const unsigned char treasure_text_buf[] = {\n")
        lines = []
        for i in range(0, len(buf_bytes), 16):
            chunk = buf_bytes[i : i + 16]
            lines.append("  " + ", ".join(str(b) for b in chunk))
        f.write(",\n".join(lines) + "\n};\n\n")
        f.write("#endif\n")
    print(f"Wrote treasures header -> {hdr_path}")

if __name__ == "__main__":
    generate_treasures()
