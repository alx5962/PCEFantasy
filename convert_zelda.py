import os
import struct
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, "src")
DAT_DIR = os.path.join(SCRIPT_DIR, "work", "dat")
SRC_DIR = os.path.join(SCRIPT_DIR, "disasm_data")

def nes_tile_to_pce_vram(nes_16b):
    """Converts 16-byte NES 2bpp tile to 32-byte PCE VDC 4bpp tile in VRAM format."""
    pce_bytes = bytearray(32)
    for y in range(8):
        # Plane 0 in low byte, Plane 1 in high byte of 16-bit word
        pce_bytes[y * 2] = nes_16b[y]
        pce_bytes[y * 2 + 1] = nes_16b[y + 8]
    # Planes 2 and 3 are left 0x00
    return bytes(pce_bytes)

def decode_nes_tile_pixels(nes_16b):
    """Decodes 16-byte NES 2bpp tile to 8x8 list of pixel values 0..3."""
    grid = []
    for y in range(8):
        lo = nes_16b[y]
        hi = nes_16b[y + 8]
        row = [((lo >> x) & 1) | (((hi >> x) & 1) << 1) for x in range(7, -1, -1)]
        grid.append(row)
    return grid

def make_pce_sprite_16x16(grid16):
    """
    Converts a 16x16 list of pixels (values 0..3) to 128-byte PCE VDC sprite format.
    Format: 64 words (128 bytes):
      Plane 0: words 0..15 (lines 0..15)
      Plane 1: words 16..31 (lines 0..15)
      Plane 2: words 32..47 (lines 0..15)
      Plane 3: words 48..63 (lines 0..15)
    """
    pce_spr = bytearray(128)
    for plane in range(2):
        plane_offset = plane * 32
        for y in range(16):
            word_val = 0
            for x in range(16):
                val = grid16[y][x]
                bit = (val >> plane) & 1
                if bit:
                    word_val |= (1 << (15 - x))
            pce_spr[plane_offset + y * 2] = word_val & 0xFF
            pce_spr[plane_offset + y * 2 + 1] = (word_val >> 8) & 0xFF
    return bytes(pce_spr)

def unpack_title_screen_bat():
    """Unpacks authentic 32x28 Title Screen BAT and attributes from GameTitleTransferBuf.dat."""
    buf_path = os.path.join(DAT_DIR, "GameTitleTransferBuf.dat")
    data = open(buf_path, "rb").read()

    vram = bytearray(0x1000) # $2000..$2FFF
    ptr = 0
    while ptr < len(data):
        hi = data[ptr]
        if hi == 0xFF:
            break
        lo = data[ptr + 1]
        count = data[ptr + 2]
        ptr += 3
        is_vertical = bool(count & 0x40)
        is_rle = bool(count & 0x80)
        length = count & 0x3F
        addr = ((hi << 8) | lo) - 0x2000
        if is_rle:
            val = data[ptr]
            ptr += 1
            for _ in range(length):
                vram[addr] = val
                addr += 32 if is_vertical else 1
        else:
            for _ in range(length):
                vram[addr] = data[ptr]
                ptr += 1
                addr += 32 if is_vertical else 1

    attrs = vram[0x3C0 : 0x400]

    def get_pal(x, y):
        attr_idx = (y // 4) * 8 + (x // 4)
        b = attrs[attr_idx]
        sub_x = (x % 4) // 2
        sub_y = (y % 4) // 2
        shift = (sub_y * 2 + sub_x) * 2
        return (b >> shift) & 0x03

    bat_bytes = bytearray()
    for y in range(28):
        for x in range(32):
            tile = vram[y * 32 + x]
            pal = get_pal(x, y)
            word = ((0x0100 + tile) & 0x0FFF) | ((pal & 0x0F) << 12)
            bat_bytes.extend(struct.pack("<H", word))

    bat_path = os.path.join(OUT_DIR, "title_bat.bin")
    with open(bat_path, "wb") as f:
        f.write(bat_bytes)
    print(f"Wrote authentic Title Screen BAT -> {bat_path} ({len(bat_bytes)} bytes)")

def unpack_story_scroll_bat():
    """Unpacks authentic 32x64 Story Prologue scroll BAT from StoryTileAttrTransferBuf.dat."""
    buf_path = os.path.join(DAT_DIR, "StoryTileAttrTransferBuf.dat")
    data = open(buf_path, "rb").read()

    vram = bytearray(0x1000) # $2000..$2FFF
    ptr = 0
    while ptr < len(data):
        hi = data[ptr]
        if hi == 0xFF:
            break
        lo = data[ptr + 1]
        count = data[ptr + 2]
        ptr += 3
        is_vertical = bool(count & 0x40)
        is_rle = bool(count & 0x80)
        length = count & 0x3F
        addr = ((hi << 8) | lo) - 0x2000
        if is_rle:
            val = data[ptr]
            ptr += 1
            for _ in range(length):
                vram[addr] = val
                addr += 32 if is_vertical else 1
        else:
            for _ in range(length):
                vram[addr] = data[ptr]
                ptr += 1
                addr += 32 if is_vertical else 1

    attrs = vram[0x3C0 : 0x400]

    def get_pal(x, y):
        attr_idx = (y // 4) * 8 + (x // 4)
        b = attrs[attr_idx]
        sub_x = (x % 4) // 2
        sub_y = (y % 4) // 2
        shift = (sub_y * 2 + sub_x) * 2
        return (b >> shift) & 0x03

    # We build a 32x64 BAT (2048 words = 4096 bytes)
    # Rows 0..27 (28 rows): Blank space (0x24)
    # Rows 28..53 (26 rows): Authentic framed story from rows 4..29 of vram
    # Rows 54..63 (10 rows): Blank space (0x24)
    bat_words = [((0x0100 + 0x24) & 0x0FFF) | (0 << 12)] * (32 * 64)

    for y_src in range(4, 30):
        y_dst = 28 + (y_src - 4)
        for x in range(32):
            tile = vram[y_src * 32 + x]
            pal = get_pal(x, y_src)
            word = ((0x0100 + tile) & 0x0FFF) | ((pal & 0x0F) << 12)
            bat_words[y_dst * 32 + x] = word

    bat_bytes = bytearray()
    for w in bat_words:
        bat_bytes.extend(struct.pack("<H", w))

    out_path = os.path.join(OUT_DIR, "story_scroll_bat.bin")
    with open(out_path, "wb") as f:
        f.write(bat_bytes)
    print(f"Wrote authentic Story Scroll BAT -> {out_path} ({len(bat_bytes)} bytes)")

def unpack_title_sprites():
    """Generates authentic 16x16 Title Screen sprites (ornate corners, sword hilt, glints, waterfall waves/crests)."""
    dat_path = os.path.join(DAT_DIR, "DemoSpritePatterns.dat")
    dat = open(dat_path, "rb").read()

    def get_tile(idx):
        return decode_nes_tile_pixels(dat[idx * 16 : (idx + 1) * 16])

    def make_16x16(tl, bl, tr, br):
        t_tl = get_tile(tl)
        t_bl = get_tile(bl)
        t_tr = get_tile(tr)
        t_br = get_tile(br)
        grid = []
        for y in range(8):
            grid.append(t_tl[y] + t_tr[y])
        for y in range(8):
            grid.append(t_bl[y] + t_br[y])
        return grid

    sprites = bytearray()
    # Sprite 0 (0x2000): Corner Top-Left (90, 91, 92, 93)
    sprites.extend(make_pce_sprite_16x16(make_16x16(90, 91, 92, 93)))
    # Sprite 1 (0x2040): Sword Hilt (94, 95, 96, 97)
    sprites.extend(make_pce_sprite_16x16(make_16x16(94, 95, 96, 97)))

    # Sprite 2 (0x2080): Sparkle Glint Frame 1 (98, 99 centered in 16x16)
    sp1 = [[0]*16 for _ in range(16)]
    for y in range(8):
        for x in range(8):
            sp1[y][x+4] = get_tile(98)[y][x]
            sp1[y+8][x+4] = get_tile(99)[y][x]
    sprites.extend(make_pce_sprite_16x16(sp1))

    # Sprite 3 (0x20C0): Sparkle Glint Frame 2 (100, 101 centered in 16x16)
    sp2 = [[0]*16 for _ in range(16)]
    for y in range(8):
        for x in range(8):
            sp2[y][x+4] = get_tile(100)[y][x]
            sp2[y+8][x+4] = get_tile(101)[y][x]
    sprites.extend(make_pce_sprite_16x16(sp2))

    # Crest Sprites (Y = 168)
    # Sprite 4 (0x2100): Crest Left Frame 1 (50, 51, 52, 53)
    sprites.extend(make_pce_sprite_16x16(make_16x16(50, 51, 52, 53)))
    # Sprite 5 (0x2140): Crest Right Frame 1 (54, 55, 56, 57)
    sprites.extend(make_pce_sprite_16x16(make_16x16(54, 55, 56, 57)))
    # Sprite 6 (0x2180): Crest Left Frame 2 (58, 59, 60, 61)
    sprites.extend(make_pce_sprite_16x16(make_16x16(58, 59, 60, 61)))
    # Sprite 7 (0x21C0): Crest Right Frame 2 (62, 63, 64, 65)
    sprites.extend(make_pce_sprite_16x16(make_16x16(62, 63, 64, 65)))

    # Wave Sprites (Rolling down Y = 178..224)
    # Frame 0 (Y < 185): Sprite 8 (0x2200) Left (66..69), Sprite 9 (0x2240) Right (70..73)
    sprites.extend(make_pce_sprite_16x16(make_16x16(66, 67, 68, 69)))
    sprites.extend(make_pce_sprite_16x16(make_16x16(70, 71, 72, 73)))
    # Frame 1 (185 <= Y < 194): Sprite 10 (0x2280) Left (74..77), Sprite 11 (0x22C0) Right (78..81)
    sprites.extend(make_pce_sprite_16x16(make_16x16(74, 75, 76, 77)))
    sprites.extend(make_pce_sprite_16x16(make_16x16(78, 79, 80, 81)))
    # Frame 2 (Y >= 194): Sprite 12 (0x2300) Left (82..85), Sprite 13 (0x2340) Right (86..89)
    sprites.extend(make_pce_sprite_16x16(make_16x16(82, 83, 84, 85)))
    sprites.extend(make_pce_sprite_16x16(make_16x16(86, 87, 88, 89)))

    spr_path = os.path.join(OUT_DIR, "title_sprites.bin")
    with open(spr_path, "wb") as f:
        f.write(sprites)
    print(f"Wrote Title sprites -> {spr_path} ({len(sprites)} bytes, {len(sprites)//128} sprites)")

def unpack_select_screen_bat():
    """Generates authentic 32x28 File Selection Screen (Mode 1, Image 2) BAT."""
    bat = [0] * (32 * 28)

    def set_cell(x, y, tile, pal=0):
        if 0 <= x < 32 and 0 <= y < 28:
            bat[y * 32 + x] = ((0x0100 + (tile & 0x0FFF)) & 0x0FFF) | ((pal & 0x0F) << 12)

    def print_text(x, y, text, pal=0):
        for i, ch in enumerate(text):
            if '0' <= ch <= '9':
                t = ord(ch) - ord('0')
            elif 'A' <= ch <= 'Z':
                t = 10 + (ord(ch) - ord('A'))
            elif ch == '-':
                t = 0x62
            elif ch == ' ':
                t = 0x24
            else:
                t = 0x24
            set_cell(x + i, y, t, pal)

    # Initialize all cells with space (0x24)
    for y in range(28):
        for x in range(32):
            set_cell(x, y, 0x24, pal=0)

    # Header: - S E L E C T - (Row 4)
    print_text(7, 4, "- S E L E C T -", pal=0)

    # Blue Box Border (Rows 7..24, Cols 3..28)
    # Top border (Row 7)
    set_cell(3, 7, 0x69, pal=1) # Top-left corner
    for x in range(4, 10):
        set_cell(x, 7, 0x6A, pal=1)
    print_text(10, 7, "NAME", pal=0)
    for x in range(14, 19):
        set_cell(x, 7, 0x6A, pal=1)
    print_text(19, 7, "LIFE", pal=0)
    for x in range(23, 28):
        set_cell(x, 7, 0x6A, pal=1)
    set_cell(28, 7, 0x6B, pal=1) # Top-right corner

    # Vertical borders (Rows 8..23)
    for y in range(8, 24):
        set_cell(3, y, 0x6C, pal=1)
        set_cell(28, y, 0x6C, pal=1)

    # Bottom border (Row 24)
    set_cell(3, 24, 0x6E, pal=1) # Bottom-left corner
    for x in range(4, 28):
        set_cell(x, 24, 0x6A, pal=1)
    set_cell(28, 24, 0x6D, pal=1) # Bottom-right corner

    # Save Slot 1 (Row 10): Link icon at col 6, Name 'AL' at col 9, '-' at col 17
    print_text(9, 10, "AL", pal=0)
    set_cell(17, 10, 0x62, pal=0) # '-'
    print_text(11, 11, "0", pal=0)  # Death count '0' under name
    # 3 Red Hearts under LIFE
    set_cell(18, 11, 0xF2, pal=2)
    set_cell(19, 11, 0xF2, pal=2)
    set_cell(20, 11, 0xF2, pal=2)

    # Save Slot 2 (Row 13): '-' at col 17
    set_cell(17, 13, 0x62, pal=0)

    # Save Slot 3 (Row 16): '-' at col 17
    set_cell(17, 16, 0x62, pal=0)

    # Menu Options (Rows 20 & 22)
    print_text(6, 20, "REGISTER YOUR NAME", pal=0)
    print_text(6, 22, "ELIMINATION MODE", pal=0)

    select_bat_bytes = bytearray()
    for word in bat:
        select_bat_bytes.extend(struct.pack("<H", word))

    select_bat_path = os.path.join(OUT_DIR, "select_bat.bin")
    with open(select_bat_path, "wb") as f:
        f.write(select_bat_bytes)
    print(f"Wrote File Selection BAT -> {select_bat_path} ({len(select_bat_bytes)} bytes)")

def unpack_start_room_0x77():
    """Unpacks authentic Overworld room 0x77 tilemap with CheckTileObject dynamic substitutions."""
    asm_path = os.path.join(SRC_DIR, "Z_05.asm")
    content = open(asm_path, "r").read()

    m = re.search(r"\nPrimarySquaresOW:\s*(.*?)(?=SecondarySquaresOW:)", content, re.DOTALL)
    primary_bytes = []
    for line in m.group(1).strip().splitlines():
        if ".BYTE" in line:
            primary_bytes.extend([int(x.strip().replace("$", "0x"), 16) for x in line.split(".BYTE")[1].split(",")])

    m = re.search(r"\nSecondarySquaresOW:\s*(.*?)(?=LayoutRoomOW:)", content, re.DOTALL)
    secondary_bytes = []
    for line in m.group(1).strip().splitlines():
        if ".BYTE" in line:
            secondary_bytes.extend([int(x.strip().replace("$", "0x"), 16) for x in line.split(".BYTE")[1].split(",")])

    heaps = []
    for h in range(16):
        hname = f"ColumnHeapOW{h:X}"
        next_name = f"ColumnHeapOW{h+1:X}" if h < 15 else "ColumnHeapOWAddr"
        m = re.search(rf"{hname}:\s*(.*?)(?={next_name}:)", content, re.DOTALL)
        hbytes = []
        for line in m.group(1).strip().splitlines():
            if ".BYTE" in line:
                hbytes.extend([int(x.strip().replace("$", "0x"), 16) for x in line.split(".BYTE")[1].split(",")])
        heaps.append(hbytes)

    level_block_ow = open(os.path.join(DAT_DIR, "LevelBlockOW.dat"), "rb").read()
    room_layouts_ow = open(os.path.join(DAT_DIR, "RoomLayoutsOW.dat"), "rb").read()
    room_id = 0x77
    unique_room_id = level_block_ow[0x180 + room_id] & 0x7F
    room_cols = room_layouts_ow[unique_room_id * 16 : (unique_room_id + 1) * 16]

    grid = [[0x24] * 32 for _ in range(22)]

    for col_idx, col_desc in enumerate(room_cols):
        heap_num = (col_desc >> 4) & 0x0F
        col_num = col_desc & 0x0F
        heap = heaps[heap_num]

        ptr = 0
        cols_found = -1
        while ptr < len(heap):
            if heap[ptr] & 0x80:
                cols_found += 1
                if cols_found == col_num:
                    break
            ptr += 1

        row = 0
        repeat = False
        while row < 11:
            desc = heap[ptr]
            sq_idx = desc & 0x3F

            if sq_idx >= 0x10:
                primary = primary_bytes[sq_idx]
                # CheckTileObject (Z_05.asm line 5925):
                # Dynamic object placeholder tokens $E5..$EA are substituted by TileObjectPrimarySquaresOW
                if 0xE5 <= primary <= 0xEA:
                    primary = [0xC8, 0xD8, 0xC4, 0xBC, 0xC0, 0xC0][primary - 0xE5]
                t0 = primary
                t1 = (primary + 1) & 0xFF
                t2 = (primary + 2) & 0xFF
                t3 = (primary + 3) & 0xFF
            else:
                base = sq_idx * 4
                t0 = secondary_bytes[base]
                t1 = secondary_bytes[base + 1]
                t2 = secondary_bytes[base + 2]
                t3 = secondary_bytes[base + 3]

            gx = col_idx * 2
            gy = row * 2
            grid[gy][gx] = t0
            grid[gy+1][gx] = t1
            grid[gy][gx+1] = t2
            grid[gy+1][gx+1] = t3

            if desc & 0x40:
                repeat = not repeat
                if not repeat:
                    ptr += 1
            else:
                ptr += 1
            row += 1

    return grid

def unpack_cave_bat():
    """Unpacks authentic Cave 0 BAT (Room 0x77 Sword Cave with Old Man & Flames)."""
    asm_path = os.path.join(SRC_DIR, "Z_05.asm")
    content = open(asm_path, "r").read()

    m = re.search(r"\nPrimarySquaresOW:\s*(.*?)(?=SecondarySquaresOW:)", content, re.DOTALL)
    primary_bytes = []
    for line in m.group(1).strip().splitlines():
        if ".BYTE" in line:
            primary_bytes.extend([int(x.strip().replace("$", "0x"), 16) for x in line.split(".BYTE")[1].split(",")])

    m = re.search(r"\nSecondarySquaresOW:\s*(.*?)(?=LayoutRoomOW:)", content, re.DOTALL)
    secondary_bytes = []
    for line in m.group(1).strip().splitlines():
        if ".BYTE" in line:
            secondary_bytes.extend([int(x.strip().replace("$", "0x"), 16) for x in line.split(".BYTE")[1].split(",")])

    heaps = []
    for h in range(16):
        hname = f"ColumnHeapOW{h:X}"
        next_name = f"ColumnHeapOW{h+1:X}" if h < 15 else "ColumnHeapOWAddr"
        m = re.search(rf"{hname}:\s*(.*?)(?={next_name}:)", content, re.DOTALL)
        hbytes = []
        for line in m.group(1).strip().splitlines():
            if ".BYTE" in line:
                hbytes.extend([int(x.strip().replace("$", "0x"), 16) for x in line.split(".BYTE")[1].split(",")])
        heaps.append(hbytes)

    cave0_cols = [0x00, 0x00, 0x95, 0x95, 0x95, 0x95, 0x95, 0xC2, 0xC2, 0x95, 0x95, 0x95, 0x95, 0x95, 0x00, 0x00]
    cave_grid = [[0x24] * 32 for _ in range(22)]

    for col_idx, cdesc in enumerate(cave0_cols):
        hnum = (cdesc >> 4) & 0x0F
        cnum = cdesc & 0x0F
        heap = heaps[hnum]
        ptr = 0
        cfound = -1
        while ptr < len(heap):
            if heap[ptr] & 0x80:
                cfound += 1
                if cfound == cnum:
                    break
            ptr += 1
        row = 0
        rep = False
        while row < 11 and ptr < len(heap):
            desc = heap[ptr]
            sq = desc & 0x3F
            if sq >= 0x10:
                p = primary_bytes[sq]
                if 0xE5 <= p <= 0xEA:
                    p = [0xC8, 0xD8, 0xC4, 0xBC, 0xC0, 0xC0][p - 0xE5]
                t0, t1, t2, t3 = p, (p + 1) & 0xFF, (p + 2) & 0xFF, (p + 3) & 0xFF
            else:
                base = sq * 4
                t0, t1, t2, t3 = secondary_bytes[base:base+4]
            gx = col_idx * 2
            gy = row * 2
            cave_grid[gy][gx] = t0
            cave_grid[gy+1][gx] = t1
            cave_grid[gy][gx+1] = t2
            cave_grid[gy+1][gx+1] = t3
            if desc & 0x40:
                rep = not rep
                if not rep: ptr += 1
            else: ptr += 1
            row += 1

    bat = [0] * (32 * 28)
    def set_cell(x, y, tile, pal=0):
        if 0 <= x < 32 and 0 <= y < 28:
            bat[y * 32 + x] = ((0x0100 + (tile & 0x0FFF)) & 0x0FFF) | ((pal & 0x0F) << 12)

    for y in range(6):
        for x in range(32):
            set_cell(x, y, 0x24, pal=0)

    # Standard HUD
    for my in range(1, 5):
        for mx in range(2, 10):
            if my == 4 and mx == 5:
                set_cell(mx, my, 0xFE, pal=5)
            else:
                set_cell(mx, my, 0xF5, pal=1)
    set_cell(11, 1, 0xF7, pal=4)
    set_cell(12, 1, 0x21, pal=1)
    set_cell(13, 1, 0x00, pal=1)
    set_cell(11, 3, 0xF9, pal=4)
    set_cell(12, 3, 0x21, pal=1)
    set_cell(13, 3, 0x00, pal=1)
    set_cell(11, 4, 0x61, pal=2)
    set_cell(12, 4, 0x21, pal=1)
    set_cell(13, 4, 0x00, pal=1)
    for bx, letter in [(15, 0x0B), (18, 0x0A)]:
        set_cell(bx, 1, 0x69, pal=2)
        set_cell(bx + 1, 1, letter, pal=2)
        set_cell(bx + 2, 1, 0x6B, pal=2)
        for my in (2, 3):
            set_cell(bx, my, 0x6C, pal=2)
            set_cell(bx + 1, my, 0x24, pal=2)
            set_cell(bx + 2, my, 0x6C, pal=2)
        set_cell(bx, 4, 0x6E, pal=2)
        set_cell(bx + 1, 4, 0x6A, pal=2)
        set_cell(bx + 2, 4, 0x6D, pal=2)
    life_chars = [0x2F, 0x15, 0x12, 0x0F, 0x0E, 0x2F]
    for i, ch in enumerate(life_chars):
        set_cell(22 + i, 1, ch, pal=3)
    for i in range(3):
        set_cell(22 + i, 4, 0xF2, pal=3)

    # Playfield Cave Room (Rock walls use BG Palette 9, floor tile 0x24 uses Palette 0)
    for ry in range(22):
        for rx in range(32):
            tile = cave_grid[ry][rx]
            pal = 9 if tile != 0x24 else 0
            set_cell(rx, 6 + ry, tile, pal=pal)

    # Note: Cave dialogues are drawn dynamically per cave in main.c!

    cave_bat_bytes = bytearray()
    for word in bat:
        cave_bat_bytes.extend(struct.pack("<H", word))
    cave_bat_path = os.path.join(OUT_DIR, "cave_bat.bin")
    with open(cave_bat_path, "wb") as f:
        f.write(cave_bat_bytes)
    print(f"Wrote authentic Cave BAT -> {cave_bat_path} ({len(cave_bat_bytes)} bytes)")

def generate_zelda_music_header():
    """Converts SongScriptDemo0, SongScriptOverworld0, and SongScriptUnderworld0 into multi-track PC Engine PSG sound driver."""
    period_table = [
        0x00, 0x23, 0x00, 0x6A, 0x03, 0x27, 0x00, 0x97,
        0x00, 0x00, 0x02, 0xF9, 0x02, 0xCF, 0x02, 0xA6,
        0x02, 0x80, 0x02, 0x5C, 0x02, 0x3A, 0x02, 0x1A,
        0x01, 0xFC, 0x01, 0xDF, 0x01, 0xC4, 0x01, 0xAB,
        0x01, 0x93, 0x01, 0x7C, 0x01, 0x67, 0x01, 0x53,
        0x01, 0x40, 0x01, 0x2E, 0x01, 0x1D, 0x01, 0x0D,
        0x00, 0xFE, 0x00, 0xEF, 0x00, 0xE2, 0x00, 0xD5,
        0x00, 0xC9, 0x00, 0xBE, 0x00, 0xB3, 0x00, 0xA9,
        0x00, 0xA0, 0x00, 0x8E, 0x00, 0x86, 0x00, 0x77,
        0x00, 0x7E, 0x00, 0x71, 0x00, 0x54, 0x00, 0x64,
        0x00, 0x5F, 0x00, 0x59, 0x00, 0x50, 0x00, 0x47,
        0x00, 0x43, 0x00, 0x3F, 0x00, 0x38, 0x00, 0x32,
        0x00, 0x21, 0x05, 0x4D, 0x05, 0x01, 0x04, 0xB9,
        0x04, 0x35, 0x03, 0xF8, 0x03, 0xBF, 0x03, 0x89,
        0x03, 0x57
    ]

    def get_period(note_id):
        if note_id + 1 < len(period_table):
            hi = period_table[note_id]
            lo = period_table[note_id + 1]
            return (hi << 8) | lo
        return 0

    def decode_song(dat_filename, base_addr, dur_table, phrase_headers):
        dat_path = os.path.join(DAT_DIR, dat_filename)
        data = open(dat_path, "rb").read()
        all_frames = []
        for addr, trg_off, sq0_off in phrase_headers:
            offset = addr - base_addr
            script = data[offset:]
            sq1_ptr, sq1_dur, sq1_cnt, sq1_period = 0, 1, 1, 0
            sq0_ptr, sq0_dur, sq0_cnt, sq0_period = sq0_off, 1, 1, 0
            trg_ptr, trg_dur, trg_cnt, trg_period, trg_rep, trg_start = trg_off, 1, 1, 0, 0, 0

            p_frames = 0
            while p_frames < 60 * 60:
                sq1_cnt -= 1
                if sq1_cnt == 0:
                    if sq1_ptr >= len(script): break
                    b = script[sq1_ptr]; sq1_ptr += 1
                    if b == 0: break
                    if b & 0x80:
                        sq1_dur = dur_table[b & 7]
                        b = script[sq1_ptr]; sq1_ptr += 1
                        if b == 0: break
                    sq1_period = get_period(b)
                    sq1_cnt = sq1_dur

                sq0_cnt -= 1
                if sq0_cnt == 0:
                    if sq0_ptr < len(script):
                        b = script[sq0_ptr]; sq0_ptr += 1
                        if b != 0:
                            if b & 0x80:
                                sq0_dur = dur_table[b & 7]
                                b = script[sq0_ptr]; sq0_ptr += 1
                            sq0_period = get_period(b) if b != 0 else 0
                            sq0_cnt = sq0_dur
                        else:
                            sq0_period = 0; sq0_cnt = 999

                trg_cnt -= 1
                if trg_cnt == 0:
                    while trg_ptr < len(script):
                        b = script[trg_ptr]; trg_ptr += 1
                        if b == 0:
                            trg_period = 0; trg_cnt = 999; break
                        elif b >= 0xF1:
                            trg_rep = b - 0xF0; trg_start = trg_ptr
                        elif b == 0xF0:
                            trg_rep -= 1
                            if trg_rep > 0: trg_ptr = trg_start
                        elif b & 0x80:
                            trg_dur = dur_table[b & 7]
                            b = script[trg_ptr]; trg_ptr += 1
                            trg_period = get_period(b); trg_cnt = trg_dur; break
                        else:
                            trg_period = get_period(b); trg_cnt = trg_dur; break

                all_frames.append((sq1_period, sq0_period, trg_period))
                p_frames += 1

        events = []
        cur_ev = None
        for f in all_frames:
            if cur_ev is None:
                cur_ev = [1, f[0], f[1], f[2]]
            elif cur_ev[1] == f[0] and cur_ev[2] == f[1] and cur_ev[3] == f[2] and cur_ev[0] < 255:
                cur_ev[0] += 1
            else:
                events.append(tuple(cur_ev))
                cur_ev = [1, f[0], f[1], f[2]]
        if cur_ev:
            events.append(tuple(cur_ev))
        return events

    ev_demo = decode_song("SongScriptDemo0.dat", 0x948B, [0x3C, 0x50, 0x0A, 0x05, 0x14, 0x0D, 0x28, 0x0E], [
        (0x948B, 0x3B, 0x1D), (0x94DC, 0x27, 0x57), (0x95A1, 0x38, 0x17), (0x95F1, 0x6C, 0x26),
        (0x968D, 0x3E, 0x25), (0x96EB, 0x19, 0x0D), (0x9720, 0x3F, 0x27), (0x978F, 0x1D, 0x11),
    ])
    ev_ow = decode_song("SongScriptOverworld0.dat", 0x8E70, [0x06, 0x0C, 0x08, 0x18, 0x24, 0x30, 0x48, 0x10], [
        (0x8E70, 0x32, 0x5D), (0x8F0F, 0x35, 0x16), (0x8F55, 0x60, 0x26), (0x8FE4, 0x3B, 0x1A), (0x9032, 0x59, 0x2D)
    ])
    ev_uw = decode_song("SongScriptUnderworld0.dat", 0x90DD, [0x03, 0x0A, 0x01, 0x14, 0x05, 0x28, 0x3C, 0x70], [
        (0x90DD, 0x45, 0x22), (0x913A, 0x39, 0x1C)
    ])

    def wrap_array(arr, per_line=12):
        lines = []
        for i in range(0, len(arr), per_line):
            lines.append("    " + ", ".join(str(x) for x in arr[i:i+per_line]))
        return ",\n".join(lines)

    demo_dur = wrap_array([ev[0] for ev in ev_demo])
    demo_p0 = wrap_array([ev[1] for ev in ev_demo])
    demo_p1 = wrap_array([ev[2] for ev in ev_demo])
    demo_p2 = wrap_array([ev[3] for ev in ev_demo])

    ow_dur = wrap_array([ev[0] for ev in ev_ow])
    ow_p0 = wrap_array([ev[1] for ev in ev_ow])
    ow_p1 = wrap_array([ev[2] for ev in ev_ow])
    ow_p2 = wrap_array([ev[3] for ev in ev_ow])

    uw_dur = wrap_array([ev[0] for ev in ev_uw])
    uw_p0 = wrap_array([ev[1] for ev in ev_uw])
    uw_p1 = wrap_array([ev[2] for ev in ev_uw])
    uw_p2 = wrap_array([ev[3] for ev in ev_uw])

    header = f"""/* Zelda PC Engine PSG Multi-Track Sound Driver - Generated by convert_zelda.py */
#ifndef _ZELDA_MUSIC_H
#define _ZELDA_MUSIC_H

#define TRACK_TITLE      0
#define TRACK_OVERWORLD  1
#define TRACK_UNDERWORLD 2
#define TRACK_FANFARE    3

#define ZELDA_DEMO_TOTAL_EVENTS {len(ev_demo)}
#define ZELDA_OW_TOTAL_EVENTS   {len(ev_ow)}
#define ZELDA_UW_TOTAL_EVENTS   {len(ev_uw)}
#define ZELDA_FANFARE_TOTAL_EVENTS 4

static const unsigned char zelda_fanfare_dur[4] = {{ 6, 6, 6, 60 }};
static const unsigned int  zelda_fanfare_p0[4]  = {{ 285, 269, 254, 226 }};
static const unsigned int  zelda_fanfare_p1[4]  = {{ 0, 0, 0, 453 }};
static const unsigned int  zelda_fanfare_p2[4]  = {{ 571, 538, 508, 453 }};

static const unsigned char zelda_demo_dur[{len(ev_demo)}] = {{
{demo_dur}
}};
static const unsigned int zelda_demo_p0[{len(ev_demo)}] = {{
{demo_p0}
}};
static const unsigned int zelda_demo_p1[{len(ev_demo)}] = {{
{demo_p1}
}};
static const unsigned int zelda_demo_p2[{len(ev_demo)}] = {{
{demo_p2}
}};

static const unsigned char zelda_ow_dur[{len(ev_ow)}] = {{
{ow_dur}
}};
static const unsigned int zelda_ow_p0[{len(ev_ow)}] = {{
{ow_p0}
}};
static const unsigned int zelda_ow_p1[{len(ev_ow)}] = {{
{ow_p1}
}};
static const unsigned int zelda_ow_p2[{len(ev_ow)}] = {{
{ow_p2}
}};

static const unsigned char zelda_uw_dur[{len(ev_uw)}] = {{
{uw_dur}
}};
static const unsigned int zelda_uw_p0[{len(ev_uw)}] = {{
{uw_p0}
}};
static const unsigned int zelda_uw_p1[{len(ev_uw)}] = {{
{uw_p1}
}};
static const unsigned int zelda_uw_p2[{len(ev_uw)}] = {{
{uw_p2}
}};

static const unsigned char zelda_square_wave[32] = {{
    31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31,
     0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0
}};

static const unsigned char zelda_triangle_wave[32] = {{
     0,  2,  4,  6,  8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30,
    31, 29, 27, 25, 23, 21, 19, 17, 15, 13, 11,  9,  7,  5,  3,  1
}};

static unsigned char g_current_track = 0;
static unsigned char g_music_frame_counter = 0;
static unsigned int  g_music_event_idx = 0;
static unsigned char g_sfx_timer = 0;

void music_play(unsigned char track)
{{
    g_current_track = track;
    g_music_event_idx = 0;
    g_music_frame_counter = 0;
}}

void init_zelda_sound(void)
{{
    unsigned char i;

    poke(0x0801, 0xFF);

    poke(0x0800, 0);
    poke(0x0804, 0x40);
    poke(0x0804, 0x00);
    for (i = 0; i < 32; i++) {{
        poke(0x0806, zelda_square_wave[i]);
    }}
    poke(0x0805, 0xFF);

    poke(0x0800, 1);
    poke(0x0804, 0x40);
    poke(0x0804, 0x00);
    for (i = 0; i < 32; i++) {{
        poke(0x0806, zelda_square_wave[i]);
    }}
    poke(0x0805, 0xFF);

    poke(0x0800, 2);
    poke(0x0804, 0x40);
    poke(0x0804, 0x00);
    for (i = 0; i < 32; i++) {{
        poke(0x0806, zelda_triangle_wave[i]);
    }}
    poke(0x0805, 0xFF);

    poke(0x0800, 3);
    poke(0x0804, 0x40);
    poke(0x0804, 0x00);
    for (i = 0; i < 32; i++) {{
        poke(0x0806, zelda_square_wave[i]);
    }}
    poke(0x0805, 0xFF);

    poke(0x0800, 4);
    poke(0x0804, 0x00);
    poke(0x0805, 0xFF);
    poke(0x0807, 0x00);

    music_play(TRACK_TITLE);
}}

void sfx_sword(void)
{{
    poke(0x0800, 4);
    poke(0x0804, 0x80 | 28);
    poke(0x0807, 0x80 | 12);
    g_sfx_timer = 5;
}}

void sfx_hit(void)
{{
    poke(0x0800, 4);
    poke(0x0804, 0x80 | 31);
    poke(0x0807, 0x80 | 22);
    g_sfx_timer = 8;
}}

void sfx_item(void)
{{
    poke(0x0800, 3);
    poke(0x0802, 110);
    poke(0x0803, 0);
    poke(0x0804, 0x80 | 28);
    g_sfx_timer = 10;
}}

void update_zelda_music(void)
{{
    unsigned int p0;
    unsigned int p1;
    unsigned int p2;
    unsigned char dur;

    if (g_sfx_timer > 0) {{
        g_sfx_timer--;
        if (g_sfx_timer == 0) {{
            poke(0x0800, 4);
            poke(0x0804, 0x00);
            poke(0x0807, 0x00);
            poke(0x0800, 3);
            poke(0x0804, 0x00);
        }}
    }}

    if (g_music_frame_counter > 0) {{
        g_music_frame_counter--;
        return;
    }}

    if (g_current_track == TRACK_TITLE) {{
        dur = zelda_demo_dur[g_music_event_idx];
        p0  = zelda_demo_p0[g_music_event_idx];
        p1  = zelda_demo_p1[g_music_event_idx];
        p2  = zelda_demo_p2[g_music_event_idx];
    }} else if (g_current_track == TRACK_OVERWORLD) {{
        dur = zelda_ow_dur[g_music_event_idx];
        p0  = zelda_ow_p0[g_music_event_idx];
        p1  = zelda_ow_p1[g_music_event_idx];
        p2  = zelda_ow_p2[g_music_event_idx];
    }} else if (g_current_track == TRACK_UNDERWORLD) {{
        dur = zelda_uw_dur[g_music_event_idx];
        p0  = zelda_uw_p0[g_music_event_idx];
        p1  = zelda_uw_p1[g_music_event_idx];
        p2  = zelda_uw_p2[g_music_event_idx];
    }} else if (g_current_track == TRACK_FANFARE) {{
        dur = zelda_fanfare_dur[g_music_event_idx];
        p0  = zelda_fanfare_p0[g_music_event_idx];
        p1  = zelda_fanfare_p1[g_music_event_idx];
        p2  = zelda_fanfare_p2[g_music_event_idx];
    }} else {{
        return;
    }}

    g_music_frame_counter = dur - 1;

    poke(0x0800, 0);
    if (p0 != 0) {{
        poke(0x0802, p0 & 0xFF);
        poke(0x0803, (p0 >> 8) & 0x0F);
        poke(0x0804, 0x80 | 28);
    }} else {{
        poke(0x0804, 0x00);
    }}

    poke(0x0800, 1);
    if (p1 != 0) {{
        poke(0x0802, p1 & 0xFF);
        poke(0x0803, (p1 >> 8) & 0x0F);
        poke(0x0804, 0x80 | 24);
    }} else {{
        poke(0x0804, 0x00);
    }}

    poke(0x0800, 2);
    if (p2 != 0) {{
        poke(0x0802, p2 & 0xFF);
        poke(0x0803, (p2 >> 8) & 0x0F);
        poke(0x0804, 0x80 | 30);
    }} else {{
        poke(0x0804, 0x00);
    }}

    g_music_event_idx++;
    if (g_current_track == TRACK_TITLE) {{
        if (g_music_event_idx >= ZELDA_DEMO_TOTAL_EVENTS) g_music_event_idx = 0;
    }} else if (g_current_track == TRACK_OVERWORLD) {{
        if (g_music_event_idx >= ZELDA_OW_TOTAL_EVENTS) g_music_event_idx = 25;
    }} else if (g_current_track == TRACK_UNDERWORLD) {{
        if (g_music_event_idx >= ZELDA_UW_TOTAL_EVENTS) g_music_event_idx = 0;
    }} else if (g_current_track == TRACK_FANFARE) {{
        if (g_music_event_idx >= ZELDA_FANFARE_TOTAL_EVENTS) {{
            g_music_event_idx = ZELDA_FANFARE_TOTAL_EVENTS - 1;
        }}
    }}
}}

void music_stop(void)
{{
    g_current_track = 255;
    poke(0x0800, 0); poke(0x0804, 0x00);
    poke(0x0800, 1); poke(0x0804, 0x00);
    poke(0x0800, 2); poke(0x0804, 0x00);
    poke(0x0800, 3); poke(0x0804, 0x00);
    poke(0x0800, 4); poke(0x0804, 0x00);
}}

void sfx_text_char(void)
{{
    poke(0x0800, 3);
    poke(0x0802, 180);
    poke(0x0803, 0);
    poke(0x0804, 0x80 | 24);
    g_sfx_timer = 3;
}}

void sfx_pause(void)
{{
    poke(0x0800, 0);
    poke(0x0802, 0x60);
    poke(0x0803, 0x01);
    poke(0x0804, 0x80 | 31);
}}

void sfx_die(void)
{{
    poke(0x0800, 4);
    poke(0x0804, 0x80 | 31);
    poke(0x0807, 0x80 | 28);
    g_sfx_timer = 30;
}}

#endif
"""
    music_path = os.path.join(OUT_DIR, "zelda_music.h")
    with open(music_path, "w") as f:
        f.write(header)
    print(f"Wrote multi-track Zelda PSG driver -> {music_path} (Demo: {len(ev_demo)}, OW: {len(ev_ow)}, UW: {len(ev_uw)})")

def generate_uw_tables_header():
    """Generates pce/uw_tables.h containing Underworld room decoding tables."""
    z05_path = os.path.join(SRC_DIR, "Z_05.asm")
    content = open(z05_path, "r").read()

    m = re.search(r"\nPrimarySquaresUW:\s*(.*?)(?=LayoutUWFloor:)", content, re.DOTALL)
    primary_bytes = []
    for line in m.group(1).strip().splitlines():
        if ".BYTE" in line:
            primary_bytes.extend([int(x.strip().replace("$", "0x"), 16) for x in line.split(".BYTE")[1].split(",")])

    col_heaps = []
    for h in range(10):
        next_name = f"ColumnHeapUW{h+1}" if h < 9 else "ColumnHeapUWCellar"
        m = re.search(rf"ColumnHeapUW{h}:\s*(.*?)(?={next_name}:)", content, re.DOTALL)
        hbytes = []
        for line in m.group(1).strip().splitlines():
            if ".BYTE" in line:
                hbytes.extend([int(x.strip().replace("$", "0x"), 16) for x in line.split(".BYTE")[1].split(",")])
        col_heaps.append(hbytes)

    all_heap_bytes = []
    heap_offsets = []
    for h in col_heaps:
        heap_offsets.append(len(all_heap_bytes))
        all_heap_bytes.extend(h)

    col_offsets = [0] * 256
    for h in range(10):
        heap = col_heaps[h]
        base = heap_offsets[h]
        ptr = 0
        cur_col = -1
        col_ptrs = {}
        while ptr < len(heap):
            if heap[ptr] & 0x80:
                cur_col += 1
                col_ptrs[cur_col] = base + ptr
            ptr += 1
        for c in range(16):
            cdesc = (h << 4) | c
            col_offsets[cdesc] = col_ptrs.get(c, 0)

    level_block_uw = open(os.path.join(DAT_DIR, "LevelBlockUW1Q1.dat"), "rb").read()
    raw_a = list(level_block_uw[0x000 : 0x080])
    raw_b = list(level_block_uw[0x080 : 0x100])
    raw_c = list(level_block_uw[0x100 : 0x180])
    raw_d = [b & 0x3F for b in level_block_uw[0x180 : 0x200]]

    room_layouts_uw = open(os.path.join(DAT_DIR, "RoomLayoutsUW.dat"), "rb").read()

    # Pre-compute uw_wall_template (32x22 = 704 bytes in row-major order)
    ram = [0xF6] * 0x10000
    def read16(addr): return ram[addr] | (ram[addr+1] << 8)
    def write16(addr, val):
        ram[addr] = val & 0xFF
        ram[addr+1] = (val >> 8) & 0xFF

    wall_tile_list = [
        0xE0, 0xF5, 0xF5, 0xF5, 0xF5, 0xB8, 0xF5, 0xD4,
        0xF5, 0xF5, 0xF5, 0xC4, 0xDE, 0xDE, 0xBC, 0xC8,
        0xDE, 0xBC, 0xDE, 0xDE, 0xF5, 0xDC, 0xC4, 0xDE,
        0xC8, 0xDE, 0xBC, 0xC8, 0xDE, 0xDE, 0xF5, 0xDC,
        0xDC, 0x00, 0xC0, 0xD0, 0xDC, 0x00, 0xF5, 0xDC,
        0xCC, 0x00, 0xF5, 0xDC, 0xDC, 0x00, 0xF5, 0xCC,
        0xD0, 0x00, 0xF5, 0xDC, 0xDC, 0x00, 0xC0, 0xD0,
        0xDC, 0x00, 0xF5, 0xDC, 0xCC, 0x00, 0xF5, 0xDC,
        0xDC, 0x00, 0xD8, 0xCC, 0xD0, 0x00, 0xF5, 0xDC,
        0xDC, 0x00, 0xF5, 0xDC, 0xDC, 0x00
    ]
    for i, b in enumerate(wall_tile_list): ram[0x9FA0 + i] = b
    for addr in range(0x6530, 0x6530 + 704): ram[addr] = 0xF6
    write16(0x00, 0x9FA0)
    write16(0x02, 0x6547)
    write16(0x04, 0x655A)
    ram[0x06] = 0x0A

    while True:
        tile = ram[read16(0x00)]
        if tile == 0:
            ram[0x06] = 0x13
            write16(0x02, read16(0x02) + 0x13)
            write16(0x04, read16(0x04) + 0x19)
            write16(0x00, read16(0x00) + 1)
            if (read16(0x00) & 0xFF) == 0xEE: break
            continue
        ram[read16(0x02)] = tile
        bot_tile = tile
        if tile != 0xDE and tile < 0xE2: bot_tile = tile + 1
        ram[read16(0x04)] = bot_tile
        ram[0x06] = (ram[0x06] - 1) & 0xFF
        if ram[0x06] != 0:
            write16(0x02, read16(0x02) + 1)
            write16(0x04, read16(0x04) - 1)
        else:
            ram[0x06] = 0x0A
            write16(0x02, read16(0x02) + 0x0D)
            write16(0x04, read16(0x04) + 0x1F)
        write16(0x00, read16(0x00) + 1)
        if (read16(0x00) & 0xFF) == 0xEE: break

    src = 0x6530
    dst = 0x67EF
    while src < 0x6690:
        t = ram[src]
        rot_t = t
        if t == 0xDD: rot_t = 0xDC
        elif t < 0xE0:
            if t < 0xDC: rot_t = t + 2
            else: rot_t = t + 1
        ram[dst] = rot_t
        src += 1
        dst -= 1

    uw_wall_row_major = []
    for ry in range(22):
        for rx in range(32):
            uw_wall_row_major.append(ram[0x6530 + rx * 22 + ry])

    def wrap_arr(arr, per_line=16):
        lines = []
        for i in range(0, len(arr), per_line):
            lines.append("    " + ", ".join(f"0x{x:02X}" for x in arr[i:i+per_line]))
        return ",\n".join(lines)

    col_offsets_lines = []
    for i in range(0, 256, 8):
        col_offsets_lines.append("    " + ", ".join(f"{x:4d}" for x in col_offsets[i:i+8]))
    col_offsets_str = ",\n".join(col_offsets_lines)

    header = f"""/* Underworld Decoding Tables - Generated by convert_zelda.py */
#ifndef _UW_TABLES_H
#define _UW_TABLES_H

static const unsigned char uw_level_block_a[128] = {{
{wrap_arr(raw_a)}
}};

static const unsigned char uw_level_block_b[128] = {{
{wrap_arr(raw_b)}
}};

static const unsigned char uw_level_block_c[128] = {{
{wrap_arr(raw_c)}
}};

static const unsigned char uw_level_block_d[128] = {{
{wrap_arr(raw_d)}
}};

static const unsigned char uw_room_layouts[{len(room_layouts_uw)}] = {{
{wrap_arr(room_layouts_uw)}
}};

static const unsigned char uw_column_heaps[{len(all_heap_bytes)}] = {{
{wrap_arr(all_heap_bytes)}
}};

static const unsigned int uw_col_offsets[256] = {{
{col_offsets_str}
}};

static const unsigned char uw_primary_squares[{len(primary_bytes)}] = {{
{wrap_arr(primary_bytes)}
}};

static const unsigned char uw_wall_template[704] = {{
{wrap_arr(uw_wall_row_major)}
}};

// 5 door types: 0=Open, 1=Shutter, 2=Key/Locked, 3=Wall, 4=Bomb Hole
static const unsigned char door_face_tiles_n[60] = {{
    0x78, 0x79, 0x7A, 0x78, 0x24, 0x77, 0x78, 0x24, 0x75, 0x78, 0x7B, 0x7C,
    0x78, 0x79, 0x7A, 0x78, 0x98, 0x99, 0x78, 0x9A, 0x9B, 0x78, 0x7B, 0x7C,
    0x78, 0x79, 0x7A, 0x78, 0xA8, 0xA9, 0x78, 0xAA, 0xAB, 0x78, 0x7B, 0x7C,
    0xF5, 0xDC, 0xDC, 0xF5, 0xDC, 0xDC, 0xF5, 0xDC, 0xDC, 0xF5, 0xDC, 0xDC,
    0xF5, 0xDC, 0xDC, 0xF5, 0x8C, 0x24, 0xF5, 0x8D, 0x24, 0xF5, 0xDC, 0xDC
}};

static const unsigned char door_face_tiles_s[60] = {{
    0x7E, 0x7F, 0x7D, 0x76, 0x24, 0x7D, 0x74, 0x24, 0x7D, 0x80, 0x81, 0x7D,
    0x7E, 0x7F, 0x7D, 0x9C, 0x9D, 0x7D, 0x9E, 0x9F, 0x7D, 0x80, 0x81, 0x7D,
    0x7E, 0x7F, 0x7D, 0xA8, 0xA9, 0x7D, 0xAA, 0xAB, 0x7D, 0x80, 0x81, 0x7D,
    0xDD, 0xDD, 0xF5, 0xDD, 0xDD, 0xF5, 0xDD, 0xDD, 0xF5, 0xDD, 0xDD, 0xF5,
    0xDD, 0xDD, 0xF5, 0x24, 0x8E, 0xF5, 0x24, 0x8F, 0xF5, 0xDD, 0xDD, 0xF5
}};

static const unsigned char door_face_tiles_w[60] = {{
    0x82, 0x82, 0x83, 0x24, 0x85, 0x76, 0x82, 0x82, 0x24, 0x84, 0x77, 0x86,
    0x82, 0x82, 0x83, 0xA0, 0x85, 0xA2, 0x82, 0x82, 0xA1, 0x84, 0xA3, 0x86,
    0x82, 0x82, 0x83, 0xAC, 0x85, 0xAE, 0x82, 0x82, 0xAD, 0x84, 0xAF, 0x86,
    0xF5, 0xF5, 0xDE, 0xDE, 0xDE, 0xDE, 0xF5, 0xF5, 0xDE, 0xDE, 0xDE, 0xDE,
    0xF5, 0xF5, 0xDE, 0x90, 0xDE, 0x24, 0xF5, 0xF5, 0x91, 0xDE, 0x24, 0xDE
}};

static const unsigned char door_face_tiles_e[60] = {{
    0x88, 0x74, 0x8A, 0x24, 0x87, 0x87, 0x75, 0x89, 0x24, 0x8B, 0x87, 0x87,
    0x88, 0xA4, 0x8A, 0xA6, 0x87, 0x87, 0xA5, 0x89, 0xA7, 0x8B, 0x87, 0x87,
    0x88, 0xAC, 0x8A, 0xAE, 0x87, 0x87, 0xAD, 0x89, 0xAF, 0x8B, 0x87, 0x87,
    0xDF, 0xDF, 0xDF, 0xDF, 0xF5, 0xF5, 0xDF, 0xDF, 0xDF, 0xDF, 0xF5, 0xF5,
    0xDF, 0x24, 0xDF, 0x92, 0xF5, 0xF5, 0x24, 0xDF, 0x93, 0xDF, 0xF5, 0xF5
}};

static const unsigned char dt_to_face[8] = {{ 0, 3, 3, 3, 3, 2, 2, 1 }};

#endif
"""
    uw_path = os.path.join(OUT_DIR, "uw_tables.h")
    with open(uw_path, "w") as f:
        f.write(header)
    print(f"Wrote Underworld tables -> {uw_path}")

def generate_ow_tables_header():
    """Generates pce/ow_tables.h containing 128-room overworld decoding tables."""
    content = open(os.path.join(SRC_DIR, "Z_05.asm"), "r").read()

    m = re.search(r"\nPrimarySquaresOW:\s*(.*?)(?=SecondarySquaresOW:)", content, re.DOTALL)
    primary_bytes = []
    for line in m.group(1).strip().splitlines():
        if ".BYTE" in line:
            primary_bytes.extend([int(x.strip().replace("$", "0x"), 16) for x in line.split(".BYTE")[1].split(",")])

    m = re.search(r"\nSecondarySquaresOW:\s*(.*?)(?=LayoutRoomOW:)", content, re.DOTALL)
    secondary_bytes = []
    for line in m.group(1).strip().splitlines():
        if ".BYTE" in line:
            secondary_bytes.extend([int(x.strip().replace("$", "0x"), 16) for x in line.split(".BYTE")[1].split(",")])

    heaps = []
    heap_offsets = []
    all_heap_bytes = []
    for h in range(16):
        hname = f"ColumnHeapOW{h:X}"
        next_name = f"ColumnHeapOW{h+1:X}" if h < 15 else "ColumnHeapOWAddr"
        m = re.search(rf"{hname}:\s*(.*?)(?={next_name}:)", content, re.DOTALL)
        hbytes = []
        for line in m.group(1).strip().splitlines():
            if ".BYTE" in line:
                hbytes.extend([int(x.strip().replace("$", "0x"), 16) for x in line.split(".BYTE")[1].split(",")])
        heaps.append(hbytes)
        heap_offsets.append(len(all_heap_bytes))
        all_heap_bytes.extend(hbytes)

    col_offsets = [0] * 256
    for cdesc in range(256):
        hnum = (cdesc >> 4) & 0x0F
        cnum = cdesc & 0x0F
        heap = heaps[hnum]
        ptr = 0
        cfound = -1
        while ptr < len(heap):
            if heap[ptr] & 0x80:
                cfound += 1
                if cfound == cnum:
                    break
            ptr += 1
        if cfound == cnum:
            col_offsets[cdesc] = heap_offsets[hnum] + ptr
        else:
            col_offsets[cdesc] = 0

    level_block_ow = open(os.path.join(DAT_DIR, "LevelBlockOW.dat"), "rb").read()
    room_layouts_ow = open(os.path.join(DAT_DIR, "RoomLayoutsOW.dat"), "rb").read()
    obj_lists_dat = open(os.path.join(DAT_DIR, "ObjLists.dat"), "rb").read()

    raw_a = list(level_block_ow[0x000 : 0x080])
    raw_b = list(level_block_ow[0x080 : 0x100])
    raw_c = list(level_block_ow[0x100 : 0x180])
    raw_d = list(level_block_ow[0x180 : 0x200])
    raw_e = list(level_block_ow[0x200 : 0x280])
    raw_f = list(level_block_ow[0x280 : 0x300])

    layout_ids = [raw_d[r] & 0x7F for r in range(128)]
    attr_a = [raw_a[r] & 0x03 for r in range(128)]
    attr_b = [raw_b[r] & 0x03 for r in range(128)]

    # Read ObjList offsets from ObjListAddrs.inc
    inc_path = os.path.join(SRC_DIR, "dat", "ObjListAddrs.inc")
    obj_list_offsets = []
    if os.path.exists(inc_path):
        for line in open(inc_path).readlines():
            if "ObjLists+" in line:
                val = int(line.split("ObjLists+")[1].strip())
                obj_list_offsets.append(val)

    def wrap_arr(arr, per_line=16, fmt="0x{:02X}"):
        lines = []
        for i in range(0, len(arr), per_line):
            chunk = arr[i:i+per_line]
            lines.append("    " + ", ".join(fmt.format(x) for x in chunk))
        return ",\n".join(lines)

    col_offsets_str = wrap_arr(col_offsets, per_line=8, fmt="0x{:04X}")

    header = f"""/* Zelda PC Engine Overworld 128-Room Engine Tables - Generated by convert_zelda.py */
#ifndef _OW_TABLES_H
#define _OW_TABLES_H

static const unsigned char ow_room_layout_ids[128] = {{
{wrap_arr(layout_ids)}
}};

static const unsigned char ow_room_attr_a[128] = {{
{wrap_arr(attr_a)}
}};

static const unsigned char ow_room_attr_b[128] = {{
{wrap_arr(attr_b)}
}};

static const unsigned char ow_level_block_a[128] = {{
{wrap_arr(raw_a)}
}};

static const unsigned char ow_level_block_b[128] = {{
{wrap_arr(raw_b)}
}};

static const unsigned char ow_level_block_c[128] = {{
{wrap_arr(raw_c)}
}};

static const unsigned char ow_level_block_d[128] = {{
{wrap_arr(raw_d)}
}};

static const unsigned char ow_level_block_e[128] = {{
{wrap_arr(raw_e)}
}};

static const unsigned char ow_level_block_f[128] = {{
{wrap_arr(raw_f)}
}};

static const unsigned char ow_foe_counts[4] = {{ 1, 4, 5, 6 }};

static const unsigned char ow_obj_lists[{len(obj_lists_dat)}] = {{
{wrap_arr(obj_lists_dat)}
}};

static const unsigned char ow_obj_list_offsets[{len(obj_list_offsets)}] = {{
{wrap_arr(obj_list_offsets)}
}};

static const unsigned char ow_room_layouts[{len(room_layouts_ow)}] = {{
{wrap_arr(room_layouts_ow)}
}};

static const unsigned char ow_column_heaps[{len(all_heap_bytes)}] = {{
{wrap_arr(all_heap_bytes)}
}};

static const unsigned int ow_col_offsets[256] = {{
{col_offsets_str}
}};

static const unsigned char ow_primary_squares[{len(primary_bytes)}] = {{
{wrap_arr(primary_bytes)}
}};

static const unsigned char ow_secondary_squares[{len(secondary_bytes)}] = {{
{wrap_arr(secondary_bytes)}
}};

static const unsigned char ow_tile_obj_sub[6] = {{
    0xC8, 0xD8, 0xC4, 0xBC, 0xC0, 0xC0
}};

// NES overworld palette selector (0..3) to PC Engine VCE BG palette index
// 0: Graveyard (Pal 8)
// 1: Brown Rock / Mountain (Pal 6)
// 2: Green Forest (Pal 0)
// 3: Brown Trees / Coast (Pal 7)
static const unsigned char ow_pal_map[4] = {{ 8, 6, 0, 7 }};

// Authentic Cave Tables (all 20 cave rooms)
// 0 = Old Man, 1 = Old Woman, 2 = Merchant, 3 = Moblin, 4 = Secret/Pond
static const unsigned char ow_cave_type[20] = {{
    0, 0, 0, 0, 4, 0, 0, 0, 0, 0, 1, 0, 0, 2, 2, 2, 2, 3, 3, 3
}};

static const unsigned char ow_cave_item[60] = {{
    63,  1, 63,  32, 63, 26,  63,  2, 63,  63,  3, 63,
    63, 63, 63,  63, 63, 63,  24, 24, 24,  63, 63, 63,
    63, 21, 63,  63, 63, 63,  31, 63, 32,  24, 24, 24,
    24, 24, 24,  28,  0,  8,  28, 25,  6,  28,  4, 34,
    25, 18,  4,  63, 24, 63,  63, 24, 63,  63, 24, 63
}};

static const unsigned char ow_cave_price[60] = {{
     0,   0,  0,   0,   0,  0,   0,   0,  0,   0,   0,  0,
     0,   0,  0,   0,   0,  0,  10,  10, 10,   0,   0,  0,
     0,   0,  0,   0,   0,  0,  40,   0, 68,   5,  10, 20,
    10,  30, 50, 130,  20, 80, 160, 100, 60,  90, 100, 10,
    80, 250, 60,   0,  30,  0,   0, 100,  0,   0,  10,  0
}};

static const char *ow_cave_texts[40] = {{
    /* Cave  0 */ "IT'S DANGEROUS TO GO", "ALONE! TAKE THIS.",
    /* Cave  1 */ "TAKE ANY ONE YOU WANT.", "",
    /* Cave  2 */ "MASTER USING IT AND", "YOU CAN HAVE THIS.",
    /* Cave  3 */ "MASTER USING IT AND", "YOU CAN HAVE THIS.",
    /* Cave  4 */ "TAKE ANY ROAD YOU WANT.", "",
    /* Cave  5 */ "SECRET IS IN THE TREE", "AT THE DEAD-END.",
    /* Cave  6 */ "LET'S PLAY MONEY", "MAKING GAME.",
    /* Cave  7 */ "PAY ME FOR THE DOOR", "REPAIR CHARGE.",
    /* Cave  8 */ "SHOW THIS TO THE", "OLD WOMAN.",
    /* Cave  9 */ "MEET THE OLD MAN", "AT THE GRAVE.",
    /* Cave 10 */ "BUY MEDICINE BEFORE", "YOU GO.",
    /* Cave 11 */ "PAY ME AND I'LL TALK.", "",
    /* Cave 12 */ "PAY ME AND I'LL TALK.", "",
    /* Cave 13 */ "BUY SOMETHIN' WILL YA!", "",
    /* Cave 14 */ "BUY SOMETHIN' WILL YA!", "",
    /* Cave 15 */ "BOY? THIS IS", "REALLY EXPENSIVE!",
    /* Cave 16 */ "BOY? THIS IS", "REALLY EXPENSIVE!",
    /* Cave 17 */ "IT'S A SECRET", "TO EVERYBODY.",
    /* Cave 18 */ "IT'S A SECRET", "TO EVERYBODY.",
    /* Cave 19 */ "IT'S A SECRET", "TO EVERYBODY."
}};

#endif
"""
    ow_path = os.path.join(OUT_DIR, "ow_tables.h")
    with open(ow_path, "w") as f:
        f.write(header)
    print(f"Wrote Overworld 128-room tables -> {ow_path}")


def main():
    print("=== Converting Zelda NES Assets to PC Engine Format ===")

    with open(os.path.join(DAT_DIR, "CommonBackgroundPatterns.dat"), "rb") as f:
        common_bg = f.read() # 112 tiles: 0x00..0x6F
    with open(os.path.join(DAT_DIR, "DemoBackgroundPatterns.dat"), "rb") as f:
        demo_bg = f.read()   # 130 tiles: 0x70..0xF1 (Title Screen)
    with open(os.path.join(DAT_DIR, "PatternBlockOWBG.dat"), "rb") as f:
        ow_bg = f.read()     # 130 tiles: 0x70..0xF1 (Overworld)
    with open(os.path.join(DAT_DIR, "CommonMiscPatterns.dat"), "rb") as f:
        misc_bg = f.read()   # 14 tiles:  0xF2..0xFF

    # 1. Title Screen BG Tiles (256 tiles: 0x00..0xFF)
    title_bg_vram = bytearray()
    for i in range(len(common_bg) // 16):
        title_bg_vram.extend(nes_tile_to_pce_vram(common_bg[i*16:(i+1)*16]))
    for i in range(len(demo_bg) // 16):
        title_bg_vram.extend(nes_tile_to_pce_vram(demo_bg[i*16:(i+1)*16]))
    for i in range(len(misc_bg) // 16):
        title_bg_vram.extend(nes_tile_to_pce_vram(misc_bg[i*16:(i+1)*16]))

    title_bg_path = os.path.join(OUT_DIR, "title_bg_tiles.bin")
    with open(title_bg_path, "wb") as f:
        f.write(title_bg_vram)
    print(f"Wrote Title Screen BG tiles -> {title_bg_path} ({len(title_bg_vram)} bytes)")

    # 2. Overworld BG Tiles (256 tiles: 0x00..0xFF)
    # Inject authentic Minimap Green Locator Dot tile at Tile 0xFE (unused in CommonMiscPatterns)
    misc_bg_mod = bytearray(misc_bg)
    dot_offset = (0xFE - 0xF2) * 16
    dot_plane0 = [0x00, 0x00, 0x00, 0x00, 0x00, 0x0E, 0x0E, 0x0E]
    dot_plane1 = [0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xF1, 0xF1, 0xF1]
    misc_bg_mod[dot_offset : dot_offset + 8] = bytes(dot_plane0)
    misc_bg_mod[dot_offset + 8 : dot_offset + 16] = bytes(dot_plane1)

    ow_bg_vram = bytearray()
    for i in range(len(common_bg) // 16):
        ow_bg_vram.extend(nes_tile_to_pce_vram(common_bg[i*16:(i+1)*16]))
    for i in range(len(ow_bg) // 16):
        ow_bg_vram.extend(nes_tile_to_pce_vram(ow_bg[i*16:(i+1)*16]))
    for i in range(len(misc_bg_mod) // 16):
        ow_bg_vram.extend(nes_tile_to_pce_vram(misc_bg_mod[i*16:(i+1)*16]))

    ow_bg_path = os.path.join(OUT_DIR, "ow_bg_tiles.bin")
    with open(ow_bg_path, "wb") as f:
        f.write(ow_bg_vram)
    print(f"Wrote Overworld BG tiles -> {ow_bg_path} ({len(ow_bg_vram)} bytes)")

    # 2b. Underworld BG Tiles (256 tiles: 0x00..0xFF)
    with open(os.path.join(DAT_DIR, "PatternBlockUWBG.dat"), "rb") as f:
        uw_bg = f.read()

    uw_bg_vram = bytearray()
    for i in range(len(common_bg) // 16):
        uw_bg_vram.extend(nes_tile_to_pce_vram(common_bg[i*16:(i+1)*16]))
    for i in range(len(uw_bg) // 16):
        uw_bg_vram.extend(nes_tile_to_pce_vram(uw_bg[i*16:(i+1)*16]))
    for i in range(len(misc_bg_mod) // 16):
        uw_bg_vram.extend(nes_tile_to_pce_vram(misc_bg_mod[i*16:(i+1)*16]))

    uw_bg_path = os.path.join(OUT_DIR, "uw_bg_tiles.bin")
    with open(uw_bg_path, "wb") as f:
        f.write(uw_bg_vram)
    print(f"Wrote Underworld BG tiles -> {uw_bg_path} ({len(uw_bg_vram)} bytes)")

    generate_uw_tables_header()


    # 3. Title Screen BAT (32x28)
    unpack_title_screen_bat()

    # 4. File Selection Screen BAT (32x28, Mode 1, Image 2)
    unpack_select_screen_bat()

    # 4b. Story Scroll BAT (32x64)
    unpack_story_scroll_bat()

    # 4c. Title Screen Sprites (Corners, Sword Hilt, Sparkles, Waterfall Waves/Crests)
    unpack_title_sprites()

    # 4d. Treasures BAT, Sprites & Palettes
    from generate_treasures import generate_treasures
    generate_treasures()

    # 5. Overworld BAT (32x28: HUD rows 0..5, Room 0x77 rows 6..27) matching Image 1
    bat = [0] * (32 * 28)

    def set_cell(x, y, tile, pal=0):
        if 0 <= x < 32 and 0 <= y < 28:
            bat[y * 32 + x] = ((0x0100 + (tile & 0x0FFF)) & 0x0FFF) | ((pal & 0x0F) << 12)

    # Initialize all HUD rows 0..5 with black space tile 0x24 (Pal 0)
    for y in range(6):
        for x in range(32):
            set_cell(x, y, 0x24, pal=0)

    # Authentic HUD Layout (matching Image 1):
    # 1. Overworld Minimap (Cols 2..9, Rows 1..4)
    for my in range(1, 5):
        for mx in range(2, 10):
            if my == 4 and mx == 5:
                set_cell(mx, my, 0xFE, pal=5) # Tile 0xFE: Grey with authentic Green Locator Dot
            else:
                set_cell(mx, my, 0xF5, pal=1) # Tile 0xF5: Solid Grey minimap

    # 2. Rupee Counter: Row 1
    set_cell(11, 1, 0xF7, pal=4) # Rupee icon (Orange/Gold)
    set_cell(12, 1, 0x21, pal=1) # 'X'
    set_cell(13, 1, 0x00, pal=1) # '0'

    # 3. Key Counter: Row 3
    set_cell(11, 3, 0xF9, pal=4) # Key icon (Orange/Gold)
    set_cell(12, 3, 0x21, pal=1) # 'X'
    set_cell(13, 3, 0x00, pal=1) # '0'

    # 4. Bomb Counter: Row 4
    set_cell(11, 4, 0x61, pal=2) # Bomb icon (Blue/White)
    set_cell(12, 4, 0x21, pal=1) # 'X'
    set_cell(13, 4, 0x00, pal=1) # '0'

    # 5. Blue Item Boxes B (Cols 15..17) and A (Cols 18..20)
    for bx, letter in [(15, 0x0B), (18, 0x0A)]:
        # Top: corner 0x69, letter ('B' or 'A'), corner 0x6B
        set_cell(bx, 1, 0x69, pal=2)
        set_cell(bx + 1, 1, letter, pal=2)
        set_cell(bx + 2, 1, 0x6B, pal=2)
        # Sides
        for my in (2, 3):
            set_cell(bx, my, 0x6C, pal=2)
            set_cell(bx + 1, my, 0x24, pal=2)
            set_cell(bx + 2, my, 0x6C, pal=2)
        # Bottom
        set_cell(bx, 4, 0x6E, pal=2)
        set_cell(bx + 1, 4, 0x6A, pal=2)
        set_cell(bx + 2, 4, 0x6D, pal=2)

    # 6. Red -LIFE- Text: Row 1, Cols 22..27
    life_chars = [0x2F, 0x15, 0x12, 0x0F, 0x0E, 0x2F] # '-', 'L', 'I', 'F', 'E', '-'
    for i, ch in enumerate(life_chars):
        set_cell(22 + i, 1, ch, pal=3)

    # 7. Red Full Hearts: Row 4, Cols 22..24
    for i in range(3):
        set_cell(22 + i, 4, 0xF2, pal=3)

    # Authentic Playfield (Rows 6..27, 22 rows from authentic Room 0x77 layout)
    ow_grid = unpack_start_room_0x77()
    for ry in range(22):
        for rx in range(32):
            tile = ow_grid[ry][rx]
            # Overworld screen 0x77 palette mapping:
            # Trees, grass/sand clearing (0x26), cave arch (0xF3) & mouth (0x24): Palette 0
            # Rock cliff tiles: Palette 6
            if (0xBC <= tile <= 0xBF) or (0xE0 <= tile <= 0xE3):
                pal = 6
            else:
                pal = 0
            set_cell(rx, 6 + ry, tile, pal)

    ow_bat_bytes = bytearray()
    for word in bat:
        ow_bat_bytes.extend(struct.pack("<H", word))

    ow_bat_path = os.path.join(OUT_DIR, "start_room_bat.bin")
    with open(ow_bat_path, "wb") as f:
        f.write(ow_bat_bytes)
    print(f"Wrote authentic Overworld BAT -> {ow_bat_path} ({len(ow_bat_bytes)} bytes)")

    hud_bat_bytes = ow_bat_bytes[: 192 * 2]
    hud_bat_path = os.path.join(OUT_DIR, "hud_bat.bin")
    with open(hud_bat_path, "wb") as f:
        f.write(hud_bat_bytes)
    print(f"Wrote authentic HUD BAT -> {hud_bat_path} ({len(hud_bat_bytes)} bytes)")

    # 6. Authentic Cave BAT (Room 0x77 Sword Cave with Old Man & Flames)
    unpack_cave_bat()

    # 7. Generate Overworld 128-Room Tables Header
    generate_ow_tables_header()

    # 8. Assemble 16x16 Hardware Sprites (Link, Heart Cursor, Old Man, Flame, Sword)
    with open(os.path.join(DAT_DIR, "CommonSpritePatterns.dat"), "rb") as f:
        sp = f.read()

    def get_tile(idx):
        return decode_nes_tile_pixels(sp[idx*16:(idx+1)*16])

    def make_spr_pair_16x16(idx_left, idx_right, flip_h=False):
        tl0 = get_tile(idx_left)
        tl1 = get_tile(idx_left + 1)
        tr0 = get_tile(idx_right)
        tr1 = get_tile(idx_right + 1)
        grid = []
        for y in range(8):
            grid.append(tl0[y] + tr0[y])
        for y in range(8):
            grid.append(tl1[y] + tr1[y])
        if flip_h:
            grid = [row[::-1] for row in grid]
        return make_pce_sprite_16x16(grid)

    sprites_pce = bytearray()
    # Sprite 0 (0x2000): Link Down Stand (Pair 8, 10)
    sprites_pce.extend(make_spr_pair_16x16(8, 10, flip_h=False))
    # Sprite 1 (0x2040): Link Down Step (Pair 8, 10 flipped horizontally)
    sprites_pce.extend(make_spr_pair_16x16(8, 10, flip_h=True))
    # Sprite 2 (0x2080): Link Up Stand (Pair 12, 14)
    sprites_pce.extend(make_spr_pair_16x16(12, 14, flip_h=False))
    # Sprite 3 (0x20C0): Link Up Step (Pair 12, 14 flipped horizontally)
    sprites_pce.extend(make_spr_pair_16x16(12, 14, flip_h=True))
    # Sprite 4 (0x2100): Link Side Walk 0 (Pair 0, 2)
    sprites_pce.extend(make_spr_pair_16x16(0, 2, flip_h=False))
    # Sprite 5 (0x2140): Link Side Walk 1 (Pair 4, 6)
    sprites_pce.extend(make_spr_pair_16x16(4, 6, flip_h=False))

    # Sprite 6 (0x2180): Link Thrust DOWN (Pair 16, 18)
    sprites_pce.extend(make_spr_pair_16x16(16, 18, flip_h=False))

    # Sprite 7 (0x21C0): Link Thrust UP (Pair 24, 26)
    sprites_pce.extend(make_spr_pair_16x16(24, 26, flip_h=False))

    # Sprite 8 (0x2200): Link Thrust SIDE (Pair 20, 22) (facing Right, FLIP_X for Left)
    sprites_pce.extend(make_spr_pair_16x16(20, 22, flip_h=False))

    # Sprite 9 (0x2240): Heart Cursor 16x16 (with authentic Heart centered)
    misc_dat = open(os.path.join(DAT_DIR, "CommonMiscPatterns.dat"), "rb").read()
    heart8 = decode_nes_tile_pixels(misc_dat[0:16])
    heart16 = [[0] * 16 for _ in range(16)]
    for y in range(8):
        for x in range(8):
            heart16[y + 4][x + 4] = heart8[y][x]
    sprites_pce.extend(make_pce_sprite_16x16(heart16))

    # Sprite 10 (0x2280): Old Man 16x16 (from PatternBlockUWSP.dat tiles 10, 11 horizontally mirrored)
    uwsp_dat = open(os.path.join(DAT_DIR, "PatternBlockUWSP.dat"), "rb").read()
    om0 = decode_nes_tile_pixels(uwsp_dat[10*16 : 11*16])
    om1 = decode_nes_tile_pixels(uwsp_dat[11*16 : 12*16])
    old_man16 = [om0[y] + om0[y][::-1] for y in range(8)] + [om1[y] + om1[y][::-1] for y in range(8)]
    sprites_pce.extend(make_pce_sprite_16x16(old_man16))

    # Sprite 11 (0x22C0): Fire 16x16 (from PatternBlockUWSP.dat tiles 0, 1 left and 2, 3 right)
    fl0 = decode_nes_tile_pixels(uwsp_dat[0*16 : 1*16])
    fl1 = decode_nes_tile_pixels(uwsp_dat[1*16 : 2*16])
    fr0 = decode_nes_tile_pixels(uwsp_dat[2*16 : 3*16])
    fr1 = decode_nes_tile_pixels(uwsp_dat[3*16 : 4*16])
    fire16 = [fl0[y] + fr0[y] for y in range(8)] + [fl1[y] + fr1[y] for y in range(8)]
    sprites_pce.extend(make_pce_sprite_16x16(fire16))

    # Sprite 12 (0x2300): Wooden Sword 16x16 Vertical (pointing UP; FLIP_Y for DOWN)
    sw0 = decode_nes_tile_pixels(sp[32*16 : 33*16])
    sw1 = decode_nes_tile_pixels(sp[33*16 : 34*16])
    sword16 = [[0]*4 + sw0[y] + [0]*4 for y in range(8)] + [[0]*4 + sw1[y] + [0]*4 for y in range(8)]
    sprites_pce.extend(make_pce_sprite_16x16(sword16))

    # Sprite 13 (0x2340): Horizontal Wooden Sword 16x16 (pointing RIGHT; FLIP_X for LEFT)
    sword16_horiz = [[0]*16 for _ in range(16)]
    for y in range(16):
        for x in range(16):
            sword16_horiz[x][15 - y] = sword16[y][x]
    sprites_pce.extend(make_pce_sprite_16x16(sword16_horiz))

    # Authentic 16x16 NES Octorok Frames (100% accurate to original NES The Legend of Zelda)
    # Load authentic NES sprite tiles from CommonMiscPatterns and PatternBlockOWSP
    with open(os.path.join(DAT_DIR, "CommonMiscPatterns.dat"), "rb") as f:
        cmp_sp = f.read()
    with open(os.path.join(DAT_DIR, "PatternBlockOWSP.dat"), "rb") as f:
        owsp_dat = f.read()

    def get_cmp_tile(idx):
        return decode_nes_tile_pixels(cmp_sp[idx*16:(idx+1)*16])

    def get_owsp_tile(idx):
        return decode_nes_tile_pixels(owsp_dat[idx*16:(idx+1)*16])

    def make_16x16_owsp(tl, bl, tr, br, flip_h=False):
        t0 = get_owsp_tile(tl)
        b0 = get_owsp_tile(bl)
        t1 = get_owsp_tile(tr)
        b1 = get_owsp_tile(br)
        grid = []
        for y in range(8):
            row = t0[y] + t1[y]
            if flip_h:
                row = row[::-1]
            grid.append(row)
        for y in range(8):
            row = b0[y] + b1[y]
            if flip_h:
                row = row[::-1]
            grid.append(row)
        return grid

    def make_mirrored_owsp(top_idx, bot_idx):
        top = get_owsp_tile(top_idx)
        bot = get_owsp_tile(bot_idx)
        grid = []
        for y in range(8):
            grid.append(top[y] + top[y][::-1])
        for y in range(8):
            grid.append(bot[y] + bot[y][::-1])
        return grid

    # Sprite 14 (0x2380): Octorok Down/Up Frame A — Authentic OWSP Tile 34 top, 35 bot mirrored
    # Engine uses FLIP_Y for up direction. make_mirrored because NES uses Anim_WriteMirroredSpritePair for vertical.
    sprites_pce.extend(make_pce_sprite_16x16(make_mirrored_owsp(34, 35)))

    # Sprite 15 (0x23C0): Octorok Down/Up Frame B — Authentic OWSP Tile 36 top, 37 bot mirrored
    sprites_pce.extend(make_pce_sprite_16x16(make_mirrored_owsp(36, 37)))

    # Sprite 16 (0x2400): Octorok Side Frame A (left) — Authentic OWSP 38, 39 left, 40, 41 right
    # Engine uses FLIP_X for right direction.
    sprites_pce.extend(make_pce_sprite_16x16(make_16x16_owsp(38, 39, 40, 41)))

    # Sprite 17 (0x2440): Octorok Side Frame B (left) — Authentic OWSP 42, 43 left, 44, 45 right
    sprites_pce.extend(make_pce_sprite_16x16(make_16x16_owsp(42, 43, 44, 45)))

    # Sprite 18 (0x2480): Defeat Puff / Sparkle (CommonSpritePatterns.dat Tiles 100, 101 mirrored)
    def make_mirrored_csp(idx_top, idx_bottom):
        t0 = get_tile(idx_top)
        t1 = get_tile(idx_bottom)
        return [t0[y] + t0[y][::-1] for y in range(8)] + [t1[y] + t1[y][::-1] for y in range(8)]

    sprites_pce.extend(make_pce_sprite_16x16(make_mirrored_csp(100, 101)))

    # Sprite 19 (0x24C0): Octorok Rock projectile (Authentic NES rock matching Image 1)
    # 0 = transparent, 1 = Brown Outline / Shadow, 2 = Warm Tan/Orange Highlight
    rock_pattern = [
        [0, 0, 2, 2, 1, 0, 0, 0],
        [0, 1, 1, 2, 2, 1, 0, 0],
        [1, 2, 1, 2, 2, 1, 1, 0],
        [1, 2, 2, 2, 1, 1, 1, 0],
        [1, 2, 1, 2, 2, 1, 2, 1],
        [2, 2, 2, 1, 2, 1, 2, 1],
        [2, 2, 2, 2, 1, 1, 1, 1],
        [2, 1, 2, 2, 1, 1, 1, 0],
        [0, 1, 1, 1, 1, 1, 1, 0],
        [0, 0, 0, 1, 1, 0, 0, 0]
    ]
    rock16 = [[0]*16 for _ in range(16)]
    for y in range(10):
        for x in range(8):
            rock16[y + 3][x + 4] = rock_pattern[y][x]
    sprites_pce.extend(make_pce_sprite_16x16(rock16))

    # Sprite 20 (0x2500): Heart item pickup (CMP Tile 0 centered 8x8 in 16x16)
    heart16 = [[0]*16 for _ in range(16)]
    heart8 = get_cmp_tile(0)
    for y in range(8):
        for x in range(8):
            heart16[y+4][x+4] = heart8[y][x]
    sprites_pce.extend(make_pce_sprite_16x16(heart16))

    # Sprite 21 (0x2540): Rupee item pickup (CSP Tile 68 top, Tile 69 bot, centered 8x16 in 16x16)
    rupee16 = [[0]*16 for _ in range(16)]
    r_top = get_tile(68)
    r_bot = get_tile(69)
    for y in range(8):
        for x in range(8):
            rupee16[y][x+4] = r_top[y][x]
            rupee16[y+8][x+4] = r_bot[y][x]
    sprites_pce.extend(make_pce_sprite_16x16(rupee16))

    # Sprite 22 (0x2580): Tektite Crouch (Authentic OWSP Tile 60 top, 61 bot mirrored)
    sprites_pce.extend(make_pce_sprite_16x16(make_mirrored_owsp(60, 61)))

    # Sprite 23 (0x25C0): Tektite Jump (Authentic OWSP Tile 62 top, 63 bot mirrored)
    sprites_pce.extend(make_pce_sprite_16x16(make_mirrored_owsp(62, 63)))

    # Sprite 24 (0x2600): Moblin Frame 0 (Authentic OWSP 98, 99 left, 100, 101 right)
    sprites_pce.extend(make_pce_sprite_16x16(make_16x16_owsp(98, 99, 100, 101)))

    # Sprite 25 (0x2640): Moblin Frame 1 (Authentic OWSP 102, 103 left, 104, 105 right)
    sprites_pce.extend(make_pce_sprite_16x16(make_16x16_owsp(102, 103, 104, 105)))

    # Sprite 26 (0x2680): Key pickup (CSP Tile 45 top, Tile 47 bot, centered 8x16 in 16x16)
    key16 = [[0]*16 for _ in range(16)]
    k_top = get_tile(45)
    k_bot = get_tile(47)
    for y in range(8):
        for x in range(8):
            key16[y][x+4] = k_top[y][x]
            key16[y+8][x+4] = k_bot[y][x]
    sprites_pce.extend(make_pce_sprite_16x16(key16))

    # Additional Underworld Sprites (Sprites 27..31)
    with open(os.path.join(DAT_DIR, "PatternBlockUWSP.dat"), "rb") as f:
        uwsp_base = f.read()
    with open(os.path.join(DAT_DIR, "PatternBlockUWSP127.dat"), "rb") as f:
        uwsp127 = f.read()

    def get_uwsp_base_tile(idx):
        return decode_nes_tile_pixels(uwsp_base[idx*16:(idx+1)*16])

    def get_uwsp127_tile(idx):
        return decode_nes_tile_pixels(uwsp127[idx*16:(idx+1)*16])

    def make_mirrored_uwsp(data_fn, top_idx, bot_idx):
        top = data_fn(top_idx)
        bot = data_fn(bot_idx)
        grid = []
        for y in range(8):
            grid.append(top[y] + top[y][::-1])
        for y in range(8):
            grid.append(bot[y] + bot[y][::-1])
        return grid

    # Sprite 27 (0x26C0): Keese Wings Open (UWSP Tile 12 top, 13 bot mirrored)
    sprites_pce.extend(make_pce_sprite_16x16(make_mirrored_uwsp(get_uwsp_base_tile, 12, 13)))

    # Sprite 28 (0x2700): Keese Wings Folded (UWSP Tile 14 top, 15 bot mirrored)
    sprites_pce.extend(make_pce_sprite_16x16(make_mirrored_uwsp(get_uwsp_base_tile, 14, 15)))

    # Sprite 29 (0x2740): Gel Slime (UWSP Tile 4 top, 5 bot mirrored)
    sprites_pce.extend(make_pce_sprite_16x16(make_mirrored_uwsp(get_uwsp_base_tile, 4, 5)))

    # Sprite 30 (0x2780): Stalfos Skeleton (UWSP127 Tile 10 top, 11 bot mirrored)
    sprites_pce.extend(make_pce_sprite_16x16(make_mirrored_uwsp(get_uwsp127_tile, 10, 11)))

    # Sprite 31 (0x27C0): Triforce Piece (CSP Tile 76 top, Tile 77 bot, centered 8x16 in 16x16)
    tri16 = [[0]*16 for _ in range(16)]
    t_top = get_tile(76)
    t_bot = get_tile(77)
    for y in range(8):
        for x in range(8):
            tri16[y][x+4] = t_top[y][x]
            tri16[y+8][x+4] = t_bot[y][x]
    sprites_pce.extend(make_pce_sprite_16x16(tri16))

    # Sprite 32 (0x2800): Link 1-handed item lift pose (raising right arm up holding sword)
    lift_matrix = [
        [0, 3, 2, 2, 0, 0, 0, 1, 1, 1, 1, 1, 1, 0, 0, 0],
        [0, 3, 2, 2, 2, 0, 1, 3, 3, 2, 1, 1, 1, 1, 0, 0],
        [0, 0, 3, 3, 0, 1, 3, 3, 3, 3, 3, 3, 3, 1, 0, 2],
        [0, 0, 3, 3, 2, 3, 2, 1, 1, 3, 3, 3, 3, 3, 0, 2],
        [0, 0, 3, 3, 2, 2, 2, 3, 2, 2, 2, 1, 2, 3, 2, 2],
        [0, 0, 0, 3, 3, 2, 2, 2, 2, 2, 3, 3, 2, 3, 2, 2],
        [0, 0, 0, 3, 3, 3, 2, 2, 3, 2, 2, 2, 2, 2, 2, 3],
        [0, 0, 0, 3, 3, 3, 1, 2, 3, 3, 2, 2, 2, 1, 3, 3],
        [0, 0, 0, 0, 3, 1, 1, 1, 1, 1, 2, 2, 1, 1, 1, 2],
        [0, 0, 0, 0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2],
        [0, 0, 0, 0, 1, 1, 1, 3, 3, 3, 3, 3, 1, 1, 3, 0],
        [0, 0, 0, 0, 3, 3, 3, 3, 2, 1, 0, 3, 3, 3, 1, 0],
        [0, 0, 0, 0, 1, 1, 1, 3, 3, 3, 3, 3, 1, 1, 1, 0],
        [0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 3, 0, 0],
        [0, 0, 0, 0, 0, 3, 3, 3, 0, 0, 0, 3, 3, 3, 0, 0],
        [0, 0, 0, 0, 0, 3, 3, 3, 0, 0, 0, 3, 3, 3, 0, 0]
    ]
    sprites_pce.extend(make_pce_sprite_16x16(lift_matrix))

    spr_path = os.path.join(OUT_DIR, "link_sprites.bin")
    with open(spr_path, "wb") as f:
        f.write(sprites_pce)
    print(f"Wrote Link & NPC sprites -> {spr_path} ({len(sprites_pce)} bytes, {len(sprites_pce)//128} sprites)")

    # 9. Zelda Palettes (Title, File Select, Overworld, and Cave)
    pal_h = """/* Zelda PC Engine VCE Palettes - Generated by convert_zelda.py */
#ifndef _ZELDA_PALETTES_H
#define _ZELDA_PALETTES_H


// Set Palettes for Title Screen (Image 1)
void set_title_palettes(void)
{
    // Backdrop / Peach Sky: (7, 5, 5)
    // BG Palette 0: Cliffs and Text (Peach, Black, Dark Gray, Light Gray)
    set_color_rgb(0, 7, 5, 5); // Backdrop Peach Sky
    set_color_rgb(1, 0, 0, 0); // Black Text
    set_color_rgb(2, 3, 3, 3); // Dark Gray Cliff
    set_color_rgb(3, 5, 5, 5); // Light Gray Cliff Highlight

    // BG Palette 1: Triforce and ZELDA Lettering (Peach, Dark Gold, Bright Gold, Black)
    set_color_rgb(16, 7, 5, 5); // Peach Sky
    set_color_rgb(17, 5, 3, 0); // Dark Gold / Brown
    set_color_rgb(18, 7, 6, 1); // Bright Gold / Yellow Highlight
    set_color_rgb(19, 0, 0, 0); // Black Lettering Border

    // BG Palette 2: Leaf Wreath Border (Peach, Dark Green, Bright Green, Yellow-Green)
    set_color_rgb(32, 7, 5, 5); // Peach Sky
    set_color_rgb(33, 0, 3, 0); // Dark Forest Green
    set_color_rgb(34, 1, 6, 1); // Bright Green
    set_color_rgb(35, 5, 7, 1); // Yellow-Green Leaf Highlight

    // BG Palette 3: Waterfall and Sword (Peach, White, Pale Mint, Aqua Blue)
    set_color_rgb(48, 7, 5, 5); // Peach Sky
    set_color_rgb(49, 7, 7, 7); // Pure White Foam & Sword Blade
    set_color_rgb(50, 4, 7, 6); // Pale Mint Water
    set_color_rgb(51, 1, 4, 6); // Aqua Blue Water Spray

    // Sprite Palette 0 (VCE subpalette 16): Sparkle Glint / Highlights
    set_color_rgb(256, 0, 0, 0); // Transparent
    set_color_rgb(257, 7, 7, 7); // Pure White
    set_color_rgb(258, 4, 7, 6); // Pale Mint
    set_color_rgb(259, 7, 4, 1); // Orange / Gold

    // Sprite Palette 1 (VCE subpalette 17): Sword Hilt (Gold)
    set_color_rgb(272, 0, 0, 0); // Transparent
    set_color_rgb(273, 5, 3, 0); // Dark Gold / Brown
    set_color_rgb(274, 7, 6, 1); // Bright Gold
    set_color_rgb(275, 0, 0, 0); // Black

    // Sprite Palette 2 (VCE subpalette 18): Leaf Wreath Corners (matches BG Pal 2)
    set_color_rgb(288, 0, 0, 0); // Transparent
    set_color_rgb(289, 0, 3, 0); // Dark Forest Green
    set_color_rgb(290, 1, 6, 1); // Bright Green
    set_color_rgb(291, 5, 7, 1); // Yellow-Green Leaf Highlight

    // Sprite Palette 3 (VCE subpalette 19): Waterfall Waves & Crest (matches BG Pal 3)
    set_color_rgb(304, 0, 0, 0); // Transparent
    set_color_rgb(305, 7, 7, 7); // Pure White Foam
    set_color_rgb(306, 4, 7, 6); // Pale Mint Water
    set_color_rgb(307, 1, 4, 6); // Aqua Blue Water Spray
}

// Set Palettes for Story Prologue Scroll Screen
void set_story_palettes(void)
{
    // BG Palette 0: Pure White text on Black
    set_color_rgb(0, 0, 0, 0);
    set_color_rgb(1, 7, 7, 7);
    set_color_rgb(2, 7, 7, 7);
    set_color_rgb(3, 7, 7, 7);

    // BG Palette 1: Light Blue text on Black
    set_color_rgb(16, 0, 0, 0);
    set_color_rgb(17, 2, 4, 7);
    set_color_rgb(18, 7, 7, 7);
    set_color_rgb(19, 7, 7, 7);

    // BG Palette 2: Red text & title on Black
    set_color_rgb(32, 0, 0, 0);
    set_color_rgb(33, 6, 1, 1);
    set_color_rgb(34, 7, 7, 7);
    set_color_rgb(35, 7, 7, 7);

    // BG Palette 3: Green pillars and frame borders
    set_color_rgb(48, 0, 0, 0);
    set_color_rgb(49, 3, 7, 2);
    set_color_rgb(50, 1, 6, 1);
    set_color_rgb(51, 0, 3, 0);
}

// Set Palettes for All of Treasures Showcase
void set_treasures_palettes(void)
{
    // BG Palettes same as story
    set_story_palettes();

    // Sprite Palette 0 (VCE 16): Green, Yellow/Gold, Brown
    set_color_rgb(256, 0, 0, 0); // Transparent
    set_color_rgb(257, 0, 5, 0); // Green
    set_color_rgb(258, 7, 6, 4); // Yellow/Beige
    set_color_rgb(259, 6, 2, 0); // Brown/Orange

    // Sprite Palette 1 (VCE 17): Dark Blue, Light Blue, White
    set_color_rgb(272, 0, 0, 0); // Transparent
    set_color_rgb(273, 0, 0, 5); // Dark Blue
    set_color_rgb(274, 2, 4, 7); // Light Blue
    set_color_rgb(275, 7, 7, 7); // White

    // Sprite Palette 2 (VCE 18): Crimson Red, Peach, White
    set_color_rgb(288, 0, 0, 0); // Transparent
    set_color_rgb(289, 6, 0, 2); // Crimson Red
    set_color_rgb(290, 7, 4, 2); // Peach/Orange
    set_color_rgb(291, 7, 7, 7); // White

    // Sprite Palette 3 (VCE 19): Dark Green, Green, Light Green
    set_color_rgb(304, 0, 0, 0); // Transparent
    set_color_rgb(305, 0, 3, 0); // Dark Green
    set_color_rgb(306, 0, 5, 2); // Green
    set_color_rgb(307, 2, 7, 4); // Light Green
}

// Set Palettes for File Select Screen (Mode 1, Image 2)
void set_select_palettes(void)
{
    // BG Palette 0: White text on Black background
    set_color_rgb(0, 0, 0, 0); // Black background
    set_color_rgb(1, 7, 7, 7); // Pure White text
    set_color_rgb(2, 4, 4, 4); // Gray
    set_color_rgb(3, 0, 0, 0); // Black

    // BG Palette 1: Royal Blue Box Frame
    set_color_rgb(16, 0, 0, 0); // Black
    set_color_rgb(17, 1, 2, 7); // Royal Blue
    set_color_rgb(18, 2, 5, 7); // Azure / Bright Blue
    set_color_rgb(19, 7, 7, 7); // White Highlight

    // BG Palette 2: Life Hearts (Red)
    set_color_rgb(32, 0, 0, 0); // Black
    set_color_rgb(33, 7, 1, 1); // Bright Crimson Red
    set_color_rgb(34, 4, 0, 0); // Dark Red
    set_color_rgb(35, 7, 7, 7); // White

    // Sprite Palette 0 (VCE subpalette 16): Link Save Slot Icon
    set_color_rgb(256, 0, 0, 0); // Transparent
    set_color_rgb(257, 1, 6, 1); // Green Tunic & Cap
    set_color_rgb(258, 7, 6, 4); // Skin Tone / Peach
    set_color_rgb(259, 5, 2, 0); // Brown Shield & Belt

    // Sprite Palette 1 (VCE subpalette 17): Heart Cursor
    set_color_rgb(272, 0, 0, 0); // Transparent
    set_color_rgb(273, 7, 1, 1); // Bright Crimson Red
    set_color_rgb(274, 4, 0, 0); // Dark Crimson Red
    set_color_rgb(275, 7, 7, 7); // White
}

// Set Palettes for In-Game Overworld and Caves (matching authentic NES palettes)
// Set Palettes for Underworld (Levels 1..9)
void set_underworld_palettes(unsigned char level)
{
    // BG Palette 0: Level 1 Turquoise / Teal Wall & Floor (NES 0x0C, 0x1C, 0x2C)
    set_color_rgb(0, 0, 0, 0); // Black
    set_color_rgb(1, 0, 3, 4); // Dark Teal
    set_color_rgb(2, 0, 5, 5); // Cyan / Teal
    set_color_rgb(3, 4, 7, 7); // Light Teal / White

    // BG Palette 1: HUD White Text & Minimap Grey
    set_color_rgb(16, 0, 0, 0);
    set_color_rgb(17, 7, 7, 7);
    set_color_rgb(18, 2, 2, 2);
    set_color_rgb(19, 7, 7, 7);

    // BG Palette 2: Blue Item Boxes 'B' and 'A'
    set_color_rgb(32, 0, 0, 0);
    set_color_rgb(33, 7, 7, 7);
    set_color_rgb(34, 2, 4, 7);
    set_color_rgb(35, 1, 2, 7);

    // BG Palette 3: HUD Red '-LIFE-' & Hearts
    set_color_rgb(48, 0, 0, 0);
    set_color_rgb(49, 6, 1, 1);
    set_color_rgb(50, 3, 0, 0);
    set_color_rgb(51, 7, 5, 5); // NES Pink ($26) for half-heart right side

    // BG Palette 4: Orange Rupee & Key Icons
    set_color_rgb(64, 0, 0, 0);
    set_color_rgb(65, 7, 7, 7);
    set_color_rgb(66, 6, 4, 1);
    set_color_rgb(67, 4, 2, 0);

    // BG Palette 5: Minimap Green Locator Dot
    set_color_rgb(80, 0, 0, 0);
    set_color_rgb(81, 1, 6, 1);
    set_color_rgb(82, 2, 2, 2);
    set_color_rgb(83, 7, 7, 7);

    // Sprite Palette 0 (subpal 16): Link
    set_color_rgb(256, 0, 0, 0);
    set_color_rgb(257, 0, 4, 0);
    set_color_rgb(258, 6, 5, 4);
    set_color_rgb(259, 4, 2, 0);

    // Sprite Palette 1 (subpal 17): Red Monster / Stalfos / Flame
    set_color_rgb(272, 0, 0, 0);
    set_color_rgb(273, 6, 1, 1);
    set_color_rgb(274, 7, 4, 1);
    set_color_rgb(275, 7, 7, 7);

    // Sprite Palette 2 (subpal 18): Heart Cursor / Red Link / Items
    set_color_rgb(288, 0, 0, 0);
    set_color_rgb(289, 6, 1, 1);
    set_color_rgb(290, 3, 0, 0);
    set_color_rgb(291, 7, 7, 7);

    // Sprite Palette 3 (subpal 19): Wooden Sword
    set_color_rgb(304, 0, 0, 0);
    set_color_rgb(305, 0, 5, 0); // Green Guard
    set_color_rgb(306, 6, 4, 1); // Tan Grip
    set_color_rgb(307, 4, 2, 0); // Brown Wood Blade

    // Sprite Palette 4 (subpal 20): Blue Monster / Blue Keese / Goriya
    set_color_rgb(320, 0, 0, 0);
    set_color_rgb(321, 1, 3, 7);
    set_color_rgb(322, 2, 5, 7);
    set_color_rgb(323, 7, 7, 7);
}

void set_game_palettes(void)
{
    // BG Palette 0: Overworld Green Forest (NES pal_sel 2)
    set_color_rgb(0, 0, 0, 0); // Black Outline / Cave Mouth / Empty Space
    set_color_rgb(1, 0, 3, 0); // Green Tree Foliage (NES 0x1A)
    set_color_rgb(2, 6, 6, 3); // Warm Sand Tan Ground (NES 0x37)
    set_color_rgb(3, 1, 2, 6); // Authentic Water Blue (NES 0x12)

    // BG Palette 1: HUD White Text & Minimap Grey (and Cave Text)
    set_color_rgb(16, 0, 0, 0); // Black HUD Background
    set_color_rgb(17, 7, 7, 7); // Pure White Text ('X', '0', Dialogue)
    set_color_rgb(18, 2, 2, 2); // Minimap Grey (Tile 0xF5)
    set_color_rgb(19, 7, 7, 7); // White

    // BG Palette 2: Blue Item Boxes 'B' and 'A'
    set_color_rgb(32, 0, 0, 0); // Black Background
    set_color_rgb(33, 7, 7, 7); // White Letters ('B' and 'A')
    set_color_rgb(34, 2, 4, 7); // Azure / Bright Blue
    set_color_rgb(35, 1, 2, 7); // Royal Blue Box Borders (Tiles 69..6E)

    // BG Palette 3: HUD Red '-LIFE-' & Hearts
    set_color_rgb(48, 0, 0, 0); // Black Background
    set_color_rgb(49, 6, 1, 1); // Crimson Red ('-LIFE-' and hearts 0xF2)
    set_color_rgb(50, 3, 0, 0); // Dark Red
    set_color_rgb(51, 7, 5, 5); // NES Pink ($26) for half-heart right side

    // BG Palette 4: Orange Rupee & Key Icons
    set_color_rgb(64, 0, 0, 0); // Black
    set_color_rgb(65, 7, 7, 7); // White Highlight
    set_color_rgb(66, 6, 4, 1); // Orange / Gold (Rupee 0xF7, Key 0xF9)
    set_color_rgb(67, 4, 2, 0); // Dark Gold

    // BG Palette 5: Minimap Green Locator Dot (Tile 0xFE)
    set_color_rgb(80, 0, 0, 0); // Black
    set_color_rgb(81, 1, 6, 1); // Bright Green Locator Dot (pixel 1)
    set_color_rgb(82, 2, 2, 2); // Minimap Grey (pixel 2)
    set_color_rgb(83, 7, 7, 7); // White

    // BG Palette 6: Cliff Rocks / Mountains (NES pal_sel 1)
    set_color_rgb(96, 0, 0, 0); // Black Outline
    set_color_rgb(97, 3, 2, 0); // Brown Mountains (NES 0x17)
    set_color_rgb(98, 6, 6, 3); // Warm Sand Tan Ground (NES 0x37)
    set_color_rgb(99, 1, 2, 6); // Authentic Water Blue (NES 0x12)

    // BG Palette 7: Brown Trees / Coast (NES pal_sel 3)
    set_color_rgb(112, 0, 0, 0); // Black Outline
    set_color_rgb(113, 3, 2, 0); // Brown Tree Foliage (NES 0x17)
    set_color_rgb(114, 6, 6, 3); // Warm Sand Tan Ground (NES 0x37)
    set_color_rgb(115, 1, 2, 6); // Authentic Water Blue (NES 0x12)

    // BG Palette 8: Graveyard / White / Gray (NES pal_sel 0)
    set_color_rgb(128, 0, 0, 0); // Black Outline
    set_color_rgb(129, 5, 5, 5); // White / Light Gray
    set_color_rgb(130, 6, 5, 4); // Sand Tan Ground
    set_color_rgb(131, 1, 2, 6); // Authentic Water Blue (NES 0x12)

    // BG Palette 9: Cave Walls (Brown Rock Walls matching Image 2)
    set_color_rgb(144, 0, 0, 0); // Black
    set_color_rgb(145, 4, 1, 0); // Dark Red/Brown
    set_color_rgb(146, 6, 4, 1); // Light Brown
    set_color_rgb(147, 7, 6, 5); // Light Buff

    // Sprite Palette 0 (VCE subpalette 16): Link
    set_color_rgb(256, 0, 0, 0); // Transparent
    set_color_rgb(257, 0, 4, 0); // Link Green Tunic & Cap
    set_color_rgb(258, 6, 5, 4); // Skin Tone / Peach
    set_color_rgb(259, 4, 2, 0); // Brown Belt / Shield

    // Sprite Palette 1 (VCE subpalette 17): Red Monster / Old Man / Fire
    set_color_rgb(272, 0, 0, 0); // Transparent
    set_color_rgb(273, 6, 1, 1); // Color 1: Crimson Red (Monster Body, Old Man Robe, Fire outer flame)
    set_color_rgb(274, 7, 4, 1); // Color 2: Orange / Peach (Monster Eyes/Iris, Old Man Skin, Fire body)
    set_color_rgb(275, 7, 7, 7); // Color 3: Pure White (Monster Belly/Snout, Old Man Beard, Fire core)

    // Sprite Palette 2 (VCE subpalette 18): Heart Cursor / Red Link
    set_color_rgb(288, 0, 0, 0); // Transparent
    set_color_rgb(289, 6, 1, 1); // Crimson Red
    set_color_rgb(290, 3, 0, 0); // Dark Crimson Red
    set_color_rgb(291, 7, 7, 7); // Pure White

    // Sprite Palette 3 (VCE subpalette 19): Wooden Sword
    set_color_rgb(304, 0, 0, 0); // Transparent
    set_color_rgb(305, 0, 5, 0); // Green Guard
    set_color_rgb(306, 6, 4, 1); // Tan Grip
    set_color_rgb(307, 4, 2, 0); // Brown Wood Blade

    // Sprite Palette 4 (VCE subpalette 20): Blue Monster
    set_color_rgb(320, 0, 0, 0); // Transparent
    set_color_rgb(321, 1, 3, 7); // Color 1: Royal Blue Body
    set_color_rgb(322, 2, 5, 7); // Color 2: Cyan / Light Blue Eyes
    set_color_rgb(323, 7, 7, 7); // Color 3: Pure White Belly & Snout
}

#endif
"""
    pal_path = os.path.join(OUT_DIR, "zelda_palettes.h")
    with open(pal_path, "w") as f:
        f.write(pal_h)
    print(f"Wrote Zelda VCE palettes -> {pal_path}")

    # 8. Generate Multi-Channel PSG Sound Driver
    generate_zelda_music_header()

    print("=== Asset conversion complete! ===")

if __name__ == "__main__":
    main()

