#include "huc.h"
#include "zelda_palettes.h"
#include "zelda_music.h"
#include "ow_tables.h"

#incbin(title_bg_tiles, "title_bg_tiles.bin");
#incbin(title_bat, "title_bat.bin");
#incbin(select_bat, "select_bat.bin");
#incbin(ow_bg_tiles, "ow_bg_tiles.bin");
#incbin(hud_bat, "hud_bat.bin");
#incbin(cave_bat, "cave_bat.bin");
#incbin(uw_bg_tiles, "uw_bg_tiles.bin");
#include "uw_tables.h"
#incbin(link_sprites, "link_sprites.bin");
#incbin(title_sprites, "title_sprites.bin");
#incbin(story_scroll_bat, "story_scroll_bat.bin");
#incbin(treasures_sprites, "treasures_sprites.bin");
#incbin(subscreen_bat, "subscreen_bat.bin");
#include "treasures_data.h"

#define STATE_TITLE            0
#define STATE_SELECT           1
#define STATE_GAME             2
#define STATE_INVENTORY        3
#define STATE_TITLE_STORY      4
#define STATE_TITLE_TREASURES  5

#define DIR_DOWN  0
#define DIR_UP    1
#define DIR_RIGHT 2
#define DIR_LEFT  3

#define ENEMY_OCTOROK 0
#define ENEMY_TEKTITE 1
#define ENEMY_MOBLIN  2
#define ENEMY_STALFOS 3
#define ENEMY_KEESE   4
#define ENEMY_GEL     5

#define ITEM_NONE  0
#define ITEM_HEART 1
#define ITEM_RUPEE 2
#define ITEM_KEY   3

static const unsigned int select_cursor_y[5] = {
    84,  // Slot 1 (AL)
    108, // Slot 2
    132, // Slot 3
    164, // REGISTER YOUR NAME
    180  // ELIMINATION MODE
};

// Authentic NES Zelda Walkable Tiles table (Z_07.asm line 2137)
static const unsigned char walkable_tiles[9] = {
    0x8D, 0x91, 0x9C, 0xAC, 0xAD, 0xCC, 0xD2, 0xD5, 0xDF
};

// 32 columns x 22 rows playfield grid in RAM (704 bytes)
static unsigned char room_grid[704];
static unsigned char current_room = 0x77;
static unsigned char in_cave = 0;
static unsigned char in_dungeon = 0;
static unsigned char dungeon_level = 0;
static unsigned char dungeon_room = 0x73;
// Overworld position to restore when Link exits south from the dungeon entry room
static unsigned char dungeon_return_room = 0x77;
static int           dungeon_return_x    = 120;
static int           dungeon_return_y    = 112;
// Underworld bitmask for permanently unlocked doors: bit 0=E, bit 1=W, bit 2=S, bit 3=N
static unsigned char dungeon_unlocked_doors[128];
static unsigned char has_sword = 0;
static unsigned char link_hp = 6;     // 6 half-hearts = 3 full hearts
static unsigned char link_rupees = 0;
static unsigned char link_keys = 0;
static unsigned char link_invincible = 0;
static unsigned char current_cave_idx = 0;
static unsigned char cave_item_taken[32]; // Persists items collected across caves (e.g. Sword in cave 0)
static unsigned char cave_text_timer = 0;
static unsigned char cave_text_line = 0;
static unsigned char cave_text_char_idx = 0;
static unsigned char cave_text_done = 0;
static unsigned char cave_blink_timer = 0;
static unsigned char cave_lift_timer = 0;
static unsigned char world_kill_count = 0;
static unsigned char world_kill_cycle = 0;
static unsigned char help_drop_count = 0;
static unsigned char help_drop_val = 0;
static unsigned int  link_x = 120;
static unsigned int  link_y = 128;
static unsigned char link_dir = DIR_UP;
static unsigned char anim_counter = 0;
static unsigned char frame_counter = 0;
static unsigned char inv_cursor_x = 0;
static unsigned char inv_cursor_y = 0;
static unsigned char inv_cursor_timer = 0;
static unsigned char flame_flicker = 0;

static unsigned char game_state = STATE_TITLE;
static unsigned char select_slot = 0;
static unsigned int  title_anim = 0;
static unsigned int  title_idle = 0;
static int           story_v_scroll = 0;
static unsigned int  story_timer = 0;
static int           treasures_scroll_y = 0;
static unsigned int  treasures_timer = 0;
static unsigned int  treasures_row_words[32];
static unsigned char wave_y[3] = { 182, 200, 216 };

static const int spawn_x[4] = { 64, 184,  80, 160 };
static const int spawn_y[4] = { 80,  88, 152, 160 };

static unsigned char enemy_active[4];
static int           enemy_x[4];
static int           enemy_y[4];
static unsigned char enemy_dir[4];
static unsigned char enemy_kind[4];  // ENEMY_OCTOROK, ENEMY_TEKTITE, ENEMY_MOBLIN
static unsigned char enemy_color[4]; // 0 = Red, 1 = Blue
static char          enemy_hp[4];
static unsigned char enemy_timer[4];
static unsigned char enemy_puff[4];
static unsigned char enemy_jump[4];  // For Tektite hop state

// Enemy Projectile (Rock shot by Octorok)
static unsigned char rock_active = 0;
static int           rock_x = 0;
static int           rock_y = 0;
static unsigned char rock_dir = 0;

// Dropped Item on Screen
static unsigned char drop_active = 0;
static unsigned char drop_type = ITEM_NONE;
static int           drop_x = 0;
static int           drop_y = 0;
static unsigned char drop_timer = 0;

static unsigned char attack_timer = 0;

// -----------------------------------------------------------------------
// Authentic NES Overworld Enemy Respawn State Machine
// -----------------------------------------------------------------------
// Bit-field: ow_cleared[room_id >> 3] bit (room_id & 7) = 1 means room
// was fully cleared (all enemies killed). Cleared rooms don't repopulate
// until they are evicted from the 10-screen history ring buffer.
static unsigned char ow_cleared[16];          // 128-bit bitmask, one per room
// Per-room saved enemy count and obj_id after a PARTIAL clear (enemies left).
static unsigned char ow_room_remaining[128];  // number of enemies still alive
static unsigned char ow_room_obj_id[128];     // obj_id used for that room
// 10-screen FIFO ring buffer of recently visited/cleared rooms.
// Fully cleared rooms placed here do NOT respawn while still inside.
// Once evicted (11th screen visited) the room is eligible to respawn.
#define OW_HISTORY_LEN 10
static unsigned char ow_history[OW_HISTORY_LEN]; // ring buffer of room IDs
static unsigned char ow_history_head = 0;         // next write position
static unsigned char ow_history_count = 0;        // how many entries filled

// Mark a bit in ow_cleared[] for room_id
void ow_set_cleared(unsigned char room_id)
{
    ow_cleared[room_id >> 3] |= (1 << (room_id & 7));
}

// Query cleared bit
unsigned char ow_is_cleared(unsigned char room_id)
{
    return (ow_cleared[room_id >> 3] >> (room_id & 7)) & 1;
}

// Clear the cleared bit (room becomes eligible to spawn again)
void ow_unset_cleared(unsigned char room_id)
{
    ow_cleared[room_id >> 3] &= ~(1 << (room_id & 7));
}

// Query whether room_id is currently in the recent-visit FIFO.
// Returns 1 if found (room is "protected" from respawn), 0 if not.
unsigned char ow_in_history(unsigned char room_id)
{
    unsigned char k;
    for (k = 0; k < ow_history_count; k++) {
        if (ow_history[k] == room_id) return 1;
    }
    return 0;
}

// Push a room into the FIFO. If the buffer is full, the oldest entry is
// evicted and its cleared-bit is removed so it can respawn fresh enemies.
void ow_push_history(unsigned char room_id)
{
    unsigned char evicted;
    unsigned char k;
    // Don't add duplicates (e.g. same room re-visited quickly)
    for (k = 0; k < ow_history_count; k++) {
        if (ow_history[k] == room_id) return;
    }
    if (ow_history_count < OW_HISTORY_LEN) {
        // Still filling the ring
        ow_history[ow_history_count] = room_id;
        ow_history_count++;
    } else {
        // Ring full: evict oldest entry, allow it to respawn
        evicted = ow_history[ow_history_head];
        ow_unset_cleared(evicted);
        ow_room_remaining[evicted] = 0; // full reset
        ow_history[ow_history_head] = room_id;
        ow_history_head = (ow_history_head + 1) % OW_HISTORY_LEN;
    }
}

// Save the current live enemy count for partial-clear rooms.
// Call this just BEFORE transitioning away from current_room.
void ow_save_room_state(unsigned char room_id)
{
    unsigned char alive;
    unsigned char i;
    unsigned char c_val;
    unsigned char d_val;
    if (in_dungeon || in_cave) return;
    // Count remaining active enemies
    alive = 0;
    for (i = 0; i < 4; i++) {
        if (enemy_active[i] == 1) alive++;
    }
    if (alive == 0) {
        // Full clear! Mark as cleared and push into history.
        ow_set_cleared(room_id);
        ow_room_remaining[room_id] = 0;
        ow_push_history(room_id);
    } else {
        // Partial clear: persist surviving enemy count.
        // Also push room into history so it won't respawn full roster.
        ow_room_remaining[room_id] = alive;
        // Preserve obj_id for this room (already set at spawn time)
        c_val = ow_level_block_c[room_id];
        d_val = ow_level_block_d[room_id];
        ow_room_obj_id[room_id] = (c_val & 0x3F) | ((d_val & 0x80) >> 1);
        ow_push_history(room_id);
    }
}

static const unsigned char drop_item_table[40] = {
    2, 1, 2, 1, 1, 1, 2, 2, 1, 1,
    2, 1, 2, 1, 2, 2, 2, 1, 1, 1,
    2, 0, 1, 2, 1, 2, 0, 1, 0, 2,
    2, 2, 1, 1, 2, 1, 2, 2, 2, 1
};

unsigned char get_enemy_drop(unsigned char kind, unsigned char col)
{
    unsigned char drop_row;
    unsigned char drop_entry;
    world_kill_count++;
    if (world_kill_count >= 16) {
        world_kill_count = 0;
        return ITEM_HEART;
    }
    if ((rand() & 0xFF) < 0x60) {
        world_kill_cycle = (world_kill_cycle + 1) % 10;
        return ITEM_NONE;
    }
    if (kind == ENEMY_OCTOROK) {
        drop_row = (col == 1) ? 1 : 0;
    } else if (kind == ENEMY_TEKTITE) {
        drop_row = 1;
    } else if (kind == ENEMY_MOBLIN) {
        drop_row = (col == 1) ? 3 : 2;
    } else {
        drop_row = 0;
    }
    drop_entry = drop_item_table[drop_row * 10 + world_kill_cycle];
    world_kill_cycle = (world_kill_cycle + 1) % 10;
    return drop_entry;
}





void update_hud_hearts(unsigned char hp)
{
    unsigned char i;
    unsigned char t;
    for (i = 0; i < 3; i++) {
        if (hp >= (i + 1) * 2) {
            t = 0xF2; // Full heart
        } else if (hp == i * 2 + 1) {
            t = 0x65; // Authentic NES half heart (Tile 0x65)
        } else {
            t = 0x24; // Empty (black)
        }
        put_vram((4 << 5) + 22 + i, (0x0100 + t) | (3 << 12));
    }
}

void update_hud_rupees(unsigned char r)
{
    unsigned char tens;
    unsigned char ones;
    tens = (r / 10) % 10;
    ones = r % 10;
    put_vram((2 << 5) + 14, (0x0100 + tens) | (0 << 12));
    put_vram((2 << 5) + 15, (0x0100 + ones) | (0 << 12));
}

void update_hud_keys(unsigned char k)
{
    unsigned char tens;
    unsigned char ones;
    tens = (k / 10) % 10;
    ones = k % 10;
    put_vram((3 << 5) + 14, (0x0100 + tens) | (0 << 12));
    put_vram((3 << 5) + 15, (0x0100 + ones) | (0 << 12));
}

void update_hud_sword(void)
{
    // Clear Box B interior (col 16, rows 2..3)
    put_vram((2 << 5) + 16, (0x0100 + 0x24) | (1 << 12));
    put_vram((3 << 5) + 16, (0x0100 + 0x24) | (1 << 12));

    // Display Wooden Sword inside Box A (cols 18..20, rows 2..3)
    if (has_sword) {
        spr_set(11);
        spr_x(148);
        spr_y(16);
        spr_pattern(0x2300); // 16x16 Sprite 12: Vertical Sword
        spr_pal(3);          // Palette 3: Wooden Sword
        spr_pri(1);
        spr_ctrl(0, 0);
        spr_show();
    } else {
        spr_set(11);
        spr_hide();
    }
}

void update_subscreen_hud(void)
{
    unsigned char i;
    unsigned char t;
    unsigned char tens, ones;

    tens = (link_rupees / 10) % 10;
    ones = link_rupees % 10;
    put_vram(((22 + 2) << 5) + 14, (0x0100 + tens) | (0 << 12));
    put_vram(((22 + 2) << 5) + 15, (0x0100 + ones) | (0 << 12));

    tens = (link_keys / 10) % 10;
    ones = link_keys % 10;
    put_vram(((22 + 3) << 5) + 14, (0x0100 + tens) | (0 << 12));
    put_vram(((22 + 3) << 5) + 15, (0x0100 + ones) | (0 << 12));

    for (i = 0; i < 3; i++) {
        if (link_hp >= (i + 1) * 2) {
            t = 0xF2;
        } else if (link_hp == i * 2 + 1) {
            t = 0x65;
        } else {
            t = 0x24;
        }
        put_vram(((22 + 4) << 5) + 22 + i, (0x0100 + t) | (3 << 12));
    }
}

unsigned char is_walkable(int px, int py)
{
    int tx;
    int ty;
    unsigned char tile;
    unsigned char k;
    unsigned char attr_a, attr_b;
    unsigned char dt_n, dt_s, dt_w, dt_e;

    if (in_cave) {
        // Cave doorway: centered at x ~120, doorway spans cols 14..17 (x in 112..143) down to bottom
        if (px >= 110 && px <= 140) {
            if (py < 104 || py > 216) return 0;
            return 1;
        }
        // Cave internal room floor boundaries
        if (px < 40 || px > 200 || py < 104 || py > 184) return 0;
        return 1;
    }

    if (in_dungeon) {
        // Underworld doorway corridors (seamless from floor to screen edge)
        // North doorway: cols 14..17 (X: 112..143), rows 0..3 (Y: 48..79)
        if (px >= 112 && px <= 143 && py <= 79) {
            attr_a = uw_level_block_a[dungeon_room];
            dt_n = (attr_a >> 5) & 7;
            if ((dungeon_unlocked_doors[dungeon_room] & 8) || dt_n == 0) return 1;
            return 0; // Solid wall or locked door
        }
        // South doorway: cols 14..17 (X: 112..143), rows 18..21 (Y: 192..223)
        if (px >= 112 && px <= 143 && py >= 192) {
            attr_a = uw_level_block_a[dungeon_room];
            dt_s = (attr_a >> 2) & 7;
            if ((dungeon_unlocked_doors[dungeon_room] & 4) || dt_s == 0) return 1;
            return 0;
        }
        // West doorway: cols 0..3 (X: 0..31), rows 9..12 (Y: 120..151, with tolerance 116..156)
        if (px <= 31 && py >= 116 && py <= 156) {
            attr_b = uw_level_block_b[dungeon_room];
            dt_w = (attr_b >> 5) & 7;
            if ((dungeon_unlocked_doors[dungeon_room] & 2) || dt_w == 0) return 1;
            return 0;
        }
        // East doorway: cols 28..31 (X: 224..255), rows 9..12 (Y: 120..151, with tolerance 116..156)
        if (px >= 224 && py >= 116 && py <= 156) {
            attr_b = uw_level_block_b[dungeon_room];
            dt_e = (attr_b >> 2) & 7;
            if ((dungeon_unlocked_doors[dungeon_room] & 1) || dt_e == 0) return 1;
            return 0;
        }

        // Inside floor boundary (cols 4..27, rows 4..17)
        if (px < 32 || px > 224 || py < 80 || py > 191) return 0;

        tx = px >> 3;
        ty = (py - 48) >> 3;
        if (ty >= 0 && ty < 22 && tx >= 0 && tx < 32) {
            tile = room_grid[(ty << 5) + tx];
            // NES UW: ObjectFirstUnwalkableTile = 0x78 (ObjectRoomBoundsUW[4])
            // Tiles 0x24 (open floor) and < 0x78 are walkable
            if (tile < 0x78) {
                return 1;
            }
            return 0; // Wall/block tile
        }
        return 1;
    }

    // Off-screen edges are walkable so Link can transition between rooms
    if (py < 48 || py >= 224 || px < 0 || px >= 256) {
        return 1;
    }

    tx = px >> 3;
    ty = (py - 48) >> 3;
    if (ty < 0 || ty >= 22 || tx < 0 || tx >= 32) {
        return 1;
    }

    tile = room_grid[(ty << 5) + tx];

    // NES OW: WalkableTiles[] entries are normalized to 0x26 before compare.
    // ObjectFirstUnwalkableTile = 0x89 (ObjectRoomBoundsOW[4] from Z_05.asm:6438).
    // Baseline walkable: common ground + stairs (0x70..0x75) + bridge planks (0x76..0x77)
    //   + shorelines (0x78..0x83) + desert sand (0x84..0x87) + any tile < 0x89.
    if (tile < 0x89 || tile == 0xF3) {
        return 1;
    }

    // NOTE: 0xC8..0xCB = brown dead trees/rocks (Primary Square 0x13)
    //       0xBC..0xBF = green dead trees (Primary Square 0x14)
    // Both are solid obstacles (>= 0x89). Authentic NES bridges use plank
    // tiles 0x76..0x77, already handled by tile < 0x89 above.

    // Authentic NES WalkableTiles table: these higher-numbered tiles are
    // normalized to 0x26 (walkable) by GetCollidingTileMoving in OW only.
    for (k = 0; k < 9; k++) {
        if (tile == walkable_tiles[k]) {
            return 1;
        }
    }

    // Tile >= 0x89 or solid obstacle
    return 0;
}

void load_overworld_room(unsigned char room_id)
{
    unsigned char layout_id;
    unsigned char attr_a;
    unsigned char attr_b;
    unsigned char outer_pal;
    unsigned char inner_pal;
    unsigned char col;
    unsigned char row;
    unsigned char cdesc;
    unsigned int  ptr;
    unsigned char desc;
    unsigned char sq;
    unsigned char t0;
    unsigned char t1;
    unsigned char t2;
    unsigned char t3;
    unsigned char repeat;
    unsigned char rx;
    unsigned char ry;
    unsigned char tile;
    unsigned char pal;
    unsigned int  vaddr;
    unsigned char mx;
    unsigned char my;
    unsigned char dot_col;
    unsigned char dot_row;
    unsigned char i;
    int           sx;
    int           sy;
    unsigned char c_val;
    unsigned char d_val;
    unsigned char raw_foes;
    unsigned char obj_id;
    unsigned char num_enemies;
    unsigned char placed;
    int           cx;
    int           cy;
    int           tx;
    int           ty;
    unsigned char overlap;
    unsigned char k;

    disp_off();
    vsync();

    current_room = room_id;
    in_cave = 0;
    in_dungeon = 0;
    rock_active = 0;
    drop_active = 0;

    layout_id = ow_room_layout_ids[room_id];
    attr_a    = ow_room_attr_a[room_id];
    attr_b    = ow_room_attr_b[room_id];
    outer_pal = ow_pal_map[attr_a];
    inner_pal = ow_pal_map[attr_b];

    // Decode 16 columns of 11 metatiles into room_grid
    for (col = 0; col < 16; col++) {
        cdesc = ow_room_layouts[(layout_id << 4) + col];
        ptr = ow_col_offsets[cdesc];
        row = 0;
        repeat = 0;
        while (row < 11) {
            desc = ow_column_heaps[ptr];
            sq = desc & 0x3F;
            if (sq >= 0x10) {
                t0 = ow_primary_squares[sq];
                if (t0 >= 0xE5 && t0 <= 0xEA) {
                    t0 = ow_tile_obj_sub[t0 - 0xE5];
                }
                t1 = t0 + 1;
                t2 = t0 + 2;
                t3 = t0 + 3;
            } else {
                t0 = ow_secondary_squares[sq << 2];
                t1 = ow_secondary_squares[(sq << 2) + 1];
                t2 = ow_secondary_squares[(sq << 2) + 2];
                t3 = ow_secondary_squares[(sq << 2) + 3];
            }

            rx = col << 1;
            ry = row << 1;
            room_grid[(ry << 5) + rx]           = t0;
            room_grid[((ry + 1) << 5) + rx]     = t1;
            room_grid[(ry << 5) + rx + 1]       = t2;
            room_grid[((ry + 1) << 5) + rx + 1] = t3;

            if (desc & 0x40) {
                repeat = !repeat;
                if (!repeat) ptr++;
            } else {
                ptr++;
            }
            row++;
        }
    }

    // Write playfield (Rows 6..27, Cols 0..31) into VRAM BAT
    for (ry = 0; ry < 22; ry++) {
        vaddr = (6 + ry) << 5;
        for (rx = 0; rx < 32; rx++) {
            tile = room_grid[(ry << 5) + rx];
            // Inner vs Outer palette area
            if ((rx >= 4 && rx < 28) && (ry >= 4 && ry < 18)) {
                pal = inner_pal;
            } else {
                pal = outer_pal;
            }
            // Brown rock cliff tiles always use Pal 6
            if ((tile >= 0xBC && tile <= 0xBF) || (tile >= 0xE0 && tile <= 0xE3)) {
                pal = 6;
            }
            put_vram(vaddr + rx, (0x0100 + tile) | (pal << 12));
        }
    }

    // Update Minimap locator dot in HUD (Rows 1..4, Cols 2..9)
    dot_col = 2 + ((room_id & 0x0F) >> 1);
    dot_row = 1 + (room_id >> 5);
    for (my = 1; my <= 4; my++) {
        vaddr = my << 5;
        for (mx = 2; mx <= 9; mx++) {
            if (mx == dot_col && my == dot_row) {
                put_vram(vaddr + mx, (0x0100 + 0xFE) | (5 << 12));
            } else {
                put_vram(vaddr + mx, (0x0100 + 0xF5) | (1 << 12));
            }
        }
    }

    // Refresh HUD status (Hearts, Rupees, Sword)
    update_hud_hearts(link_hp);
    update_hud_rupees(link_rupees);
    if (has_sword) update_hud_sword();

    // Read authentic Enemy Spawns from LevelBlockOW tables
    c_val = ow_level_block_c[room_id];
    d_val = ow_level_block_d[room_id];
    raw_foes = ow_foe_counts[(c_val & 0xC0) >> 6];
    obj_id = (c_val & 0x3F) | ((d_val & 0x80) >> 1);

    if (obj_id == 0 || room_id == 0x77) {
        // Peaceful screen (e.g. Start screen 0x77)
        num_enemies = 0;
    } else if (ow_is_cleared(room_id) && ow_in_history(room_id)) {
        // Fully cleared AND still in recent-visit history: no respawn
        num_enemies = 0;
    } else if (ow_room_remaining[room_id] > 0) {
        // Partial clear: restore only the enemies that survived
        num_enemies = ow_room_remaining[room_id];
        obj_id = ow_room_obj_id[room_id]; // restore their type
        if (num_enemies > 4) num_enemies = 4;
    } else {
        // Normal full spawn
        num_enemies = raw_foes;
        if (num_enemies > 4) num_enemies = 4;
    }

    // Store obj_id for potential partial-clear save later
    ow_room_obj_id[room_id] = obj_id;

    for (i = 0; i < 4; i++) {
        if (i < num_enemies) {
            // --- 4-corner walkable spawn search ---
            // Try each hardcoded spawn point with full 4-corner footprint check.
            // If none work, scan the open playfield for a walkable position.
            sx = spawn_x[i];
            sy = spawn_y[i];
            if (is_walkable(sx + 1, sy + 1) && is_walkable(sx + 14, sy + 1) &&
                is_walkable(sx + 1, sy + 14) && is_walkable(sx + 14, sy + 14)) {
                enemy_active[i] = 1;
                enemy_x[i] = sx;
                enemy_y[i] = sy;
            } else {
                // Grid scan: test candidate positions across the room
                // in 24-pixel steps, choosing first fully walkable cell.
                placed = 0;
                for (cy = 68; cy <= 196 && !placed; cy += 24) {
                    for (cx = 24; cx <= 220 && !placed; cx += 24) {
                        // Offset candidates by slot index to spread enemies out
                        tx = cx + ((i & 1) ? 12 : 0);
                        ty = cy + ((i & 2) ? 12 : 0);
                        if (tx > 220) tx = 220;
                        if (ty > 196) ty = 196;
                        if (is_walkable(tx + 1, ty + 1) &&
                            is_walkable(tx + 14, ty + 1) &&
                            is_walkable(tx + 1, ty + 14) &&
                            is_walkable(tx + 14, ty + 14)) {
                            // Make sure this cell isn't already used by a previous enemy
                            overlap = 0;
                            for (k = 0; k < i; k++) {
                                if (enemy_active[k] &&
                                    tx + 12 >= enemy_x[k] + 4 &&
                                    tx + 4  <= enemy_x[k] + 12) {
                                    overlap = 1;
                                    break;
                                }
                            }
                            if (!overlap) {
                                enemy_active[i] = 1;
                                enemy_x[i] = tx;
                                enemy_y[i] = ty;
                                placed = 1;
                            }
                        }
                    }
                }
                if (!placed) {
                    enemy_active[i] = 0;
                }
            }

            if (enemy_active[i]) {
                enemy_dir[i] = (i + room_id) & 3;
                enemy_timer[i] = 20 + ((i * 13) & 31);
                enemy_puff[i] = 0;
                enemy_jump[i] = 0;

                // Authentic enemy type identification:
                if (obj_id >= 7 && obj_id <= 10) {
                    // Octoroks
                    enemy_kind[i] = ENEMY_OCTOROK;
                    enemy_color[i] = (obj_id & 1); // 0 = Red, 1 = Blue
                    enemy_hp[i] = (enemy_color[i] == 1) ? 2 : 1;
                } else if (obj_id == 13 || obj_id == 14) {
                    // Tektites
                    enemy_kind[i] = ENEMY_TEKTITE;
                    enemy_color[i] = (obj_id == 14) ? 1 : 0;
                    enemy_hp[i] = (enemy_color[i] == 1) ? 2 : 1;
                } else if (obj_id == 3 || obj_id == 4) {
                    // Moblins
                    enemy_kind[i] = ENEMY_MOBLIN;
                    enemy_color[i] = (obj_id == 4) ? 1 : 0;
                    enemy_hp[i] = (enemy_color[i] == 1) ? 3 : 2;
                } else {
                    // Default to Octorok
                    enemy_kind[i] = ENEMY_OCTOROK;
                    enemy_color[i] = (i == 3) ? 1 : 0;
                    enemy_hp[i] = (enemy_color[i] == 1) ? 2 : 1;
                }
            } else {
                spr_set(6 + i);
                spr_hide();
            }
        } else {
            enemy_active[i] = 0;
            spr_set(6 + i);
            spr_hide();
        }
    }

    // Hide dropped item and projectile
    spr_set(5);
    spr_hide();
    spr_set(10);
    spr_hide();

    disp_on();
}

void try_unlock_dungeon_doors(void)
{
    unsigned char attr_a, attr_b;
    unsigned char dt_n, dt_s, dt_w, dt_e;
    unsigned char col, row, i;
    unsigned char did_unlock;

    if (!in_dungeon || link_keys == 0) return;

    attr_a = uw_level_block_a[dungeon_room];
    attr_b = uw_level_block_b[dungeon_room];
    dt_n = (attr_a >> 5) & 7;
    dt_s = (attr_a >> 2) & 7;
    dt_w = (attr_b >> 5) & 7;
    dt_e = (attr_b >> 2) & 7;

    did_unlock = 0;

    // North door: Link is facing UP near doorway cols 14..17, rows 3..4 (y ~70..84, x ~110..138)
    if (link_dir == DIR_UP && (dt_n == 5 || dt_n == 6) && !(dungeon_unlocked_doors[dungeon_room] & 8)) {
        if (link_x >= 110 && link_x <= 138 && link_y >= 70 && link_y <= 84) {
            dungeon_unlocked_doors[dungeon_room] |= 8;
            if (dungeon_room >= 16) {
                dungeon_unlocked_doors[dungeon_room - 16] |= 4; // South door of North neighbor
            }
            did_unlock = 1;
            // Re-stamp North door as Open (face 0)
            i = 0;
            for (col = 14; col <= 17; col++) {
                for (row = 1; row <= 3; row++) {
                    room_grid[(row << 5) + col] = door_face_tiles_n[i++];
                    put_vram(((6 + row) << 5) + col, (0x0100 + room_grid[(row << 5) + col]) | (0 << 12));
                }
            }
        }
    }
    // South door: Link is facing DOWN near doorway cols 14..17, rows 17..18 (y ~180..194, x ~110..138)
    else if (link_dir == DIR_DOWN && (dt_s == 5 || dt_s == 6) && !(dungeon_unlocked_doors[dungeon_room] & 4)) {
        if (link_x >= 110 && link_x <= 138 && link_y >= 180 && link_y <= 194) {
            dungeon_unlocked_doors[dungeon_room] |= 4;
            if (dungeon_room < 112) {
                dungeon_unlocked_doors[dungeon_room + 16] |= 8; // North door of South neighbor
            }
            did_unlock = 1;
            // Re-stamp South door as Open (face 0)
            i = 0;
            for (col = 14; col <= 17; col++) {
                for (row = 18; row <= 20; row++) {
                    room_grid[(row << 5) + col] = door_face_tiles_s[i++];
                    put_vram(((6 + row) << 5) + col, (0x0100 + room_grid[(row << 5) + col]) | (0 << 12));
                }
            }
        }
    }
    // West door: Link is facing LEFT near doorway rows 9..12, cols 3..5 (x ~28..42, y ~118..146)
    else if (link_dir == DIR_LEFT && (dt_w == 5 || dt_w == 6) && !(dungeon_unlocked_doors[dungeon_room] & 2)) {
        if (link_y >= 118 && link_y <= 146 && link_x >= 28 && link_x <= 42) {
            dungeon_unlocked_doors[dungeon_room] |= 2;
            if ((dungeon_room & 0x0F) > 0) {
                dungeon_unlocked_doors[dungeon_room - 1] |= 1; // East door of West neighbor
            }
            did_unlock = 1;
            // Re-stamp West door as Open (face 0)
            i = 0;
            for (col = 1; col <= 3; col++) {
                for (row = 9; row <= 10; row++) {
                    room_grid[(row << 5) + col] = door_face_tiles_w[i++];
                    put_vram(((6 + row) << 5) + col, (0x0100 + room_grid[(row << 5) + col]) | (0 << 12));
                }
            }
            for (col = 1; col <= 3; col++) {
                for (row = 11; row <= 12; row++) {
                    room_grid[(row << 5) + col] = door_face_tiles_w[i++];
                    put_vram(((6 + row) << 5) + col, (0x0100 + room_grid[(row << 5) + col]) | (0 << 12));
                }
            }
        }
    }
    // East door: Link is facing RIGHT near doorway rows 9..12, cols 26..28 (x ~210..226, y ~118..146)
    else if (link_dir == DIR_RIGHT && (dt_e == 5 || dt_e == 6) && !(dungeon_unlocked_doors[dungeon_room] & 1)) {
        if (link_y >= 118 && link_y <= 146 && link_x >= 210 && link_x <= 226) {
            dungeon_unlocked_doors[dungeon_room] |= 1;
            if ((dungeon_room & 0x0F) < 15) {
                dungeon_unlocked_doors[dungeon_room + 1] |= 2; // West door of East neighbor
            }
            did_unlock = 1;
            // Re-stamp East door as Open (face 0)
            i = 0;
            for (col = 28; col <= 30; col++) {
                for (row = 9; row <= 10; row++) {
                    room_grid[(row << 5) + col] = door_face_tiles_e[i++];
                    put_vram(((6 + row) << 5) + col, (0x0100 + room_grid[(row << 5) + col]) | (0 << 12));
                }
            }
            for (col = 28; col <= 30; col++) {
                for (row = 11; row <= 12; row++) {
                    room_grid[(row << 5) + col] = door_face_tiles_e[i++];
                    put_vram(((6 + row) << 5) + col, (0x0100 + room_grid[(row << 5) + col]) | (0 << 12));
                }
            }
        }
    }

    if (did_unlock) {
        link_keys--;
        update_hud_keys(link_keys);
        sfx_item();
    }
}

void load_underworld_room(unsigned char room_id)
{
    unsigned char layout_id;
    unsigned char col;
    unsigned char row;
    unsigned char cdesc;
    unsigned int  ptr;
    unsigned char desc;
    unsigned char sq;
    unsigned char prim;
    unsigned char t0;
    unsigned char t1;
    unsigned char t2;
    unsigned char t3;
    unsigned char rx;
    unsigned char ry;
    unsigned char attr_a;
    unsigned char attr_b;
    unsigned char dt_n, dt_s, dt_w, dt_e;
    unsigned char face_n, face_s, face_w, face_e;
    unsigned int  i;
    unsigned int  vaddr;
    unsigned char dot_col;
    unsigned char dot_row;
    unsigned char mx, my;
    unsigned char num_enemies;
    int           sx, sy;

    disp_off();
    vsync();

    dungeon_room = room_id;
    in_cave = 0;
    in_dungeon = 1;  // Stay in dungeon mode while rendering
    rock_active = 0;
    drop_active = 0;

    // 1. Initialize room_grid with authentic constant Underworld Wall template
    for (i = 0; i < 704; i++) {
        room_grid[i] = uw_wall_template[i];
    }

    // 2. Decode the 12x7 floor squares from RoomLayoutsUW & Column heaps
    layout_id = uw_level_block_d[room_id] & 0x3F;
    for (col = 0; col < 12; col++) {
        cdesc = uw_room_layouts[(layout_id * 12) + col];
        ptr = uw_col_offsets[cdesc];
        row = 0;
        while (row < 7) {
            desc = uw_column_heaps[ptr++];
            sq = desc & 0x07;
            prim = uw_primary_squares[sq];
            for (i = 0; i <= ((desc & 0x70) >> 4); i++) {
                if (prim < 0x70 || prim >= 0xF3) {
                    t0 = prim; t1 = prim; t2 = prim; t3 = prim;
                } else {
                    t0 = prim; t1 = prim + 1; t2 = prim + 2; t3 = prim + 3;
                }
                rx = 4 + (col << 1);
                ry = 4 + (row << 1);
                room_grid[(ry << 5) + rx]           = t0;
                room_grid[((ry + 1) << 5) + rx]     = t1;
                room_grid[(ry << 5) + rx + 1]       = t2;
                room_grid[((ry + 1) << 5) + rx + 1] = t3;
                row++;
                if (row >= 7) break;
            }
        }
    }

    // 3. Stamp authentic doors (N, S, W, E) based on LevelBlockUW attributes
    attr_a = uw_level_block_a[room_id];
    attr_b = uw_level_block_b[room_id];
    dt_n = (attr_a >> 5) & 7; face_n = (dungeon_unlocked_doors[room_id] & 8) ? 0 : dt_to_face[dt_n];
    dt_s = (attr_a >> 2) & 7; face_s = (dungeon_unlocked_doors[room_id] & 4) ? 0 : dt_to_face[dt_s];
    dt_w = (attr_b >> 5) & 7; face_w = (dungeon_unlocked_doors[room_id] & 2) ? 0 : dt_to_face[dt_w];
    dt_e = (attr_b >> 2) & 7; face_e = (dungeon_unlocked_doors[room_id] & 1) ? 0 : dt_to_face[dt_e];

    // North door (cols 14..17, rows 1..3)
    i = 0;
    for (col = 14; col <= 17; col++) {
        for (row = 1; row <= 3; row++) {
            room_grid[(row << 5) + col] = door_face_tiles_n[(face_n * 12) + i++];
        }
    }

    // South door (cols 14..17, rows 18..20)
    i = 0;
    for (col = 14; col <= 17; col++) {
        for (row = 18; row <= 20; row++) {
            room_grid[(row << 5) + col] = door_face_tiles_s[(face_s * 12) + i++];
        }
    }

    // West door (cols 1..3, rows 9..12)
    i = 0;
    for (col = 1; col <= 3; col++) {
        for (row = 9; row <= 10; row++) {
            room_grid[(row << 5) + col] = door_face_tiles_w[(face_w * 12) + i++];
        }
    }
    for (col = 1; col <= 3; col++) {
        for (row = 11; row <= 12; row++) {
            room_grid[(row << 5) + col] = door_face_tiles_w[(face_w * 12) + i++];
        }
    }

    // East door (cols 28..30, rows 9..12)
    i = 0;
    for (col = 28; col <= 30; col++) {
        for (row = 9; row <= 10; row++) {
            room_grid[(row << 5) + col] = door_face_tiles_e[(face_e * 12) + i++];
        }
    }
    for (col = 28; col <= 30; col++) {
        for (row = 11; row <= 12; row++) {
            room_grid[(row << 5) + col] = door_face_tiles_e[(face_e * 12) + i++];
        }
    }

    // 4. Stream playfield into VRAM BAT (Rows 6..27, Cols 0..31), subpalette 0 (Level 1 Turquoise)
    for (ry = 0; ry < 22; ry++) {
        vaddr = (6 + ry) << 5;
        for (rx = 0; rx < 32; rx++) {
            put_vram(vaddr + rx, (0x0100 + room_grid[(ry << 5) + rx]) | (0 << 12));
        }
    }

    // 5. Update Minimap locator dot in HUD (Rows 1..4, Cols 2..9)
    dot_col = 2 + ((room_id & 0x0F) >> 1);
    dot_row = 1 + (room_id >> 5);
    for (my = 1; my <= 4; my++) {
        vaddr = my << 5;
        for (mx = 2; mx <= 9; mx++) {
            if (mx == dot_col && my == dot_row) {
                put_vram(vaddr + mx, (0x0100 + 0xFE) | (5 << 12));
            } else {
                put_vram(vaddr + mx, (0x0100 + 0xF5) | (1 << 12));
            }
        }
    }

    // 6. Refresh HUD status
    update_hud_hearts(link_hp);
    update_hud_rupees(link_rupees);
    update_hud_keys(link_keys);
    if (has_sword) update_hud_sword();

    // 7. Spawn Underworld enemies
    if (room_id == 0x73) {
        num_enemies = 0;
    } else if (room_id == 0x72) {
        num_enemies = 3;
        for (i = 0; i < 3; i++) {
            enemy_kind[i] = ENEMY_STALFOS;
            enemy_color[i] = 0; // Stalfos
            enemy_hp[i] = 2;
        }
    } else if (room_id == 0x74) {
        num_enemies = 4;
        for (i = 0; i < 4; i++) {
            enemy_kind[i] = ENEMY_KEESE;
            enemy_color[i] = (i & 1); // Red / Blue
            enemy_hp[i] = 1;
        }
    } else {
        num_enemies = 3;
        for (i = 0; i < 3; i++) {
            enemy_kind[i] = ENEMY_GEL;
            enemy_color[i] = 0;
            enemy_hp[i] = 1;
        }
    }

    for (i = 0; i < 4; i++) {
        if (i < num_enemies) {
            sx = spawn_x[i];
            sy = spawn_y[i];
            enemy_active[i] = 1;
            enemy_x[i] = sx;
            enemy_y[i] = sy;
            enemy_dir[i] = i & 3;
            enemy_timer[i] = 20 + i * 10;
            enemy_puff[i] = 0;
            enemy_jump[i] = 0;
        } else {
            enemy_active[i] = 0;
            spr_set(6 + i);
            spr_hide();
        }
    }

    spr_set(5); spr_hide();
    spr_set(10); spr_hide();

    disp_on();
}

void cave_print_num(unsigned char tx, unsigned char ty, unsigned char val)
{
    unsigned char hundreds;
    unsigned char tens;
    unsigned char ones;
    hundreds = val / 100;
    tens = (val / 10) % 10;
    ones = val % 10;
    if (hundreds > 0) {
        put_vram(((6 + ty) << 5) + tx, (0x0100 + hundreds) | (1 << 12));
        put_vram(((6 + ty) << 5) + tx + 1, (0x0100 + tens) | (1 << 12));
        put_vram(((6 + ty) << 5) + tx + 2, (0x0100 + ones) | (1 << 12));
    } else if (tens > 0) {
        put_vram(((6 + ty) << 5) + tx + 1, (0x0100 + tens) | (1 << 12));
        put_vram(((6 + ty) << 5) + tx + 2, (0x0100 + ones) | (1 << 12));
    } else {
        put_vram(((6 + ty) << 5) + tx + 2, (0x0100 + ones) | (1 << 12));
    }
}

void cave_print_char(unsigned char tx, unsigned char ty, char c)
{
    unsigned char t;
    if (c >= 'A' && c <= 'Z') {
        t = 10 + (c - 'A');
    } else if (c >= '0' && c <= '9') {
        t = c - '0';
    } else if (c == '\'') {
        t = 0x2A;
    } else if (c == '!') {
        t = 0x29;
    } else if (c == '?') {
        t = 0x28;
    } else if (c == '.') {
        t = 0x2C;
    } else if (c == '-') {
        t = 0x2F;
    } else {
        t = 0x24; // Space
    }
    put_vram(((6 + ty) << 5) + tx, (0x0100 + t) | (1 << 12));
}

void cave_clear_dialogue(void)
{
    unsigned char x;
    for (x = 3; x <= 28; x++) {
        put_vram(((6 + 4) << 5) + x, (0x0100 + 0x24) | (0 << 12));
        put_vram(((6 + 6) << 5) + x, (0x0100 + 0x24) | (0 << 12));
    }
}

void cave_print_line(unsigned char tx, unsigned char ty, const char *s)
{
    unsigned char i;
    char c;
    unsigned char t;
    i = 0;
    while (s[i] != '\0') {
        c = s[i];
        if (c >= 'A' && c <= 'Z') {
            t = 10 + (c - 'A');
        } else if (c >= '0' && c <= '9') {
            t = c - '0';
        } else if (c == '\'') {
            t = 0x2A;
        } else if (c == '!') {
            t = 0x29;
        } else if (c == '?') {
            t = 0x28;
        } else if (c == '.') {
            t = 0x2C;
        } else if (c == '-') {
            t = 0x2F;
        } else {
            t = 0x24; // Space
        }
        put_vram(((6 + ty) << 5) + tx + i, (0x0100 + t) | (1 << 12));
        i++;
    }
}

unsigned int get_item_sprite_pattern(unsigned char item_id)
{
    if (item_id == 1 || item_id == 2 || item_id == 3) {
        return 0x2300; // Wooden Sword
    } else if (item_id == 24) {
        return 0x2540; // Rupee
    } else if (item_id == 26) {
        return 0x2500; // Heart Container
    } else if (item_id == 32) {
        return 0x2500; // Red/Blue Potion
    } else if (item_id == 28) {
        return 0x2500; // Shield
    } else if (item_id == 0) {
        return 0x24C0; // Bomb
    } else if (item_id == 25) {
        return 0x2680; // Key
    } else if (item_id == 21) {
        return 0x2540; // Letter
    }
    return 0x2540;
}

unsigned char get_item_sprite_pal(unsigned char item_id)
{
    if (item_id == 1 || item_id == 2 || item_id == 3) {
        return 3; // Wooden Sword Palette
    } else if (item_id == 24) {
        return 2; // Rupee Palette
    } else if (item_id == 26) {
        return 1; // Heart Container Palette (Red)
    } else if (item_id == 32) {
        return 1; // Potion Palette
    }
    return 2;
}

void update_enemies(void)
{
    unsigned char i;
    int nx;
    int ny;
    unsigned char ef;

    for (i = 0; i < 4; i++) {
        if (enemy_active[i] == 1) {
            if (enemy_timer[i] > 0) {
                enemy_timer[i]--;
            } else {
                enemy_dir[i] = (enemy_dir[i] + 1 + (frame_counter & 1)) & 3;
                if (in_dungeon) {
                    enemy_timer[i] = 30 + ((frame_counter * 7 + i * 13) & 31);
                } else {
                    enemy_timer[i] = 25 + ((frame_counter * 5 + i * 11) & 31);
                }

                // Octorok shoots rock projectile (OW only)
                if (!in_dungeon && enemy_kind[i] == ENEMY_OCTOROK && !rock_active) {
                    rock_active = 1;
                    rock_x = enemy_x[i];
                    rock_y = enemy_y[i];
                    rock_dir = enemy_dir[i];
                }
            }

            // Tektite jump hopping
            if (enemy_kind[i] == ENEMY_TEKTITE) {
                if ((frame_counter & 15) == 0) {
                    enemy_jump[i] = !enemy_jump[i];
                }
            }

            // Movement update
            if ((frame_counter + i) & 1) {
                nx = enemy_x[i];
                ny = enemy_y[i];
                if (enemy_dir[i] == DIR_DOWN)  ny++;
                else if (enemy_dir[i] == DIR_UP) ny--;
                else if (enemy_dir[i] == DIR_LEFT) nx--;
                else if (enemy_dir[i] == DIR_RIGHT) nx++;

                if (in_dungeon) {
                    if (nx >= 0x21 && nx <= 0xD0 && ny >= 0x5E && ny <= 0xBD &&
                        is_walkable(nx + 4, ny + 8) && is_walkable(nx + 11, ny + 14)) {
                        enemy_x[i] = nx;
                        enemy_y[i] = ny;
                    } else {
                        enemy_dir[i] = (enemy_dir[i] + 2) & 3;
                        enemy_timer[i] = 20;
                    }
                } else {
                    if (nx >= 16 && nx <= 228 && ny >= 58 && ny <= 204 &&
                        is_walkable(nx + 4, ny + 8) && is_walkable(nx + 11, ny + 14)) {
                        enemy_x[i] = nx;
                        enemy_y[i] = ny;
                    } else {
                        enemy_dir[i] = (enemy_dir[i] + 2) & 3;
                        enemy_timer[i] = 16;
                    }
                }
            }

            // Enemy touch damage to Link
            if (link_invincible == 0 && attack_timer == 0) {
                if (link_x + 12 >= enemy_x[i] + 3 &&
                    link_x + 3  <= enemy_x[i] + 12 &&
                    link_y + 15 >= enemy_y[i] + 4 &&
                    link_y + 6  <= enemy_y[i] + 14) {
                    if (link_hp > 0) link_hp--;
                    update_hud_hearts(link_hp);
                    if (link_hp == 0) {
                        handle_player_death();
                        return;
                    }
                    link_invincible = 30; // 30 frames of invincibility
                    sfx_hit();
                }
            }

            // Render Enemy Sprite
            spr_set(6 + i);
            spr_x(enemy_x[i]);
            spr_y(enemy_y[i]);
            ef = (frame_counter >> 3) & 1;

            if (enemy_kind[i] == ENEMY_STALFOS) {
                spr_pattern(0x2780);
                spr_ctrl(FLIP_X_MASK | FLIP_Y_MASK, (frame_counter & 8) ? (FLIP_X | NO_FLIP_Y) : (NO_FLIP_X | NO_FLIP_Y));
            } else if (enemy_kind[i] == ENEMY_KEESE) {
                spr_pattern((frame_counter & 8) ? 0x26C0 : 0x2700);
                spr_ctrl(FLIP_X_MASK | FLIP_Y_MASK, NO_FLIP_X | NO_FLIP_Y);
            } else if (enemy_kind[i] == ENEMY_GEL) {
                spr_pattern(0x2740);
                spr_ctrl(FLIP_X_MASK | FLIP_Y_MASK, NO_FLIP_X | NO_FLIP_Y);
            } else if (enemy_kind[i] == ENEMY_TEKTITE) {
                spr_pattern(enemy_jump[i] ? 0x25C0 : 0x2580);
                spr_ctrl(FLIP_X_MASK | FLIP_Y_MASK, NO_FLIP_X | NO_FLIP_Y);
            } else if (enemy_kind[i] == ENEMY_MOBLIN) {
                spr_pattern(ef ? 0x2640 : 0x2600);
                spr_ctrl(FLIP_X_MASK | FLIP_Y_MASK, (enemy_dir[i] == DIR_RIGHT) ? (FLIP_X | NO_FLIP_Y) : (NO_FLIP_X | NO_FLIP_Y));
            } else {
                if (enemy_dir[i] == DIR_DOWN) {
                    spr_pattern(ef ? 0x23C0 : 0x2380);
                    spr_ctrl(FLIP_X_MASK | FLIP_Y_MASK, NO_FLIP_X | NO_FLIP_Y);
                } else if (enemy_dir[i] == DIR_UP) {
                    spr_pattern(ef ? 0x23C0 : 0x2380);
                    spr_ctrl(FLIP_X_MASK | FLIP_Y_MASK, NO_FLIP_X | FLIP_Y);
                } else if (enemy_dir[i] == DIR_LEFT) {
                    spr_pattern(ef ? 0x2440 : 0x2400);
                    spr_ctrl(FLIP_X_MASK | FLIP_Y_MASK, NO_FLIP_X | NO_FLIP_Y);
                } else {
                    spr_pattern(ef ? 0x2440 : 0x2400);
                    spr_ctrl(FLIP_X_MASK | FLIP_Y_MASK, FLIP_X | NO_FLIP_Y);
                }
            }
            spr_pal((enemy_color[i] == 1) ? 4 : 1);
            spr_pri(1);
            spr_show();
        } else if (enemy_active[i] == 2) {
            // Defeat Sparkle animation
            if (enemy_puff[i] > 0) {
                enemy_puff[i]--;
                spr_set(6 + i);
                spr_x(enemy_x[i]);
                spr_y(enemy_y[i]);
                spr_pattern(0x2480); // Sprite 18: Defeat Sparkle
                spr_pal(1);
                spr_pri(1);
                spr_ctrl(FLIP_X_MASK | FLIP_Y_MASK, (enemy_puff[i] & 4) ? (FLIP_X | FLIP_Y) : (NO_FLIP_X | NO_FLIP_Y));
                spr_show();
            } else {
                enemy_active[i] = 0;
                spr_set(6 + i);
                spr_hide();

                if (!drop_active) {
                    drop_timer = 240; // 4 seconds
                    if (in_dungeon) {
                        drop_type = ITEM_KEY;
                        drop_active = 1;
                        drop_x = enemy_x[i];
                        drop_y = enemy_y[i];
                    } else {
                        drop_type = get_enemy_drop(enemy_kind[i], enemy_color[i]);
                        if (drop_type != ITEM_NONE) {
                            drop_active = 1;
                            drop_x = enemy_x[i];
                            drop_y = enemy_y[i];
                        }
                    }
                }

                // Check if this was the last active enemy (full clear)
                if (!in_dungeon && !in_cave) {
                    unsigned char any_alive;
                    unsigned char k;
                    any_alive = 0;
                    for (k = 0; k < 4; k++) {
                        if (enemy_active[k] == 1) { any_alive = 1; break; }
                    }
                    if (!any_alive) {
                        // Full clear: mark room cleared and push to FIFO
                        ow_set_cleared(current_room);
                        ow_room_remaining[current_room] = 0;
                        ow_push_history(current_room);
                    }
                }
            }
        } else {
            spr_set(6 + i);
            spr_hide();
        }
    }
}

void load_cave(unsigned char cave_idx)
{
    unsigned char i;
    unsigned char cave_t;
    unsigned char item0;
    unsigned char item1;
    unsigned char item2;
    unsigned int  npc_pat;
    unsigned char npc_pal;
    const char *line1;
    const char *line2;

    disp_off();
    vsync();

    in_cave = 1;
    in_dungeon = 0;
    rock_active = 0;
    drop_active = 0;
    current_cave_idx = cave_idx;

    // Clear any overworld enemies
    for (i = 0; i < 4; i++) {
        enemy_active[i] = 0;
        spr_set(6 + i);
        spr_hide();
    }
    spr_set(10);
    spr_hide();

    // Load authentic Cave BAT base (walls and floor)
    load_vram(0x0000, cave_bat, 896);

    cave_t = ow_cave_type[cave_idx];
    item0 = ow_cave_item[cave_idx * 3];
    item1 = ow_cave_item[cave_idx * 3 + 1];
    item2 = ow_cave_item[cave_idx * 3 + 2];

    // Select NPC Sprite and Palette based on cave type:
    // 0: Old Man (0x2280, Pal 1)
    // 1: Old Woman (0x2280, Pal 4)
    // 2: Merchant (0x2280, Pal 4)
    // 3: Moblin (0x2600, Pal 1)
    if (cave_t == 1 || cave_t == 2) {
        npc_pat = 0x2280;
        npc_pal = 4;
    } else if (cave_t == 3) {
        npc_pat = 0x2600;
        npc_pal = 1;
    } else {
        npc_pat = 0x2280;
        npc_pal = 1;
    }

    // Check if cave item was already taken (e.g. Wooden Sword taken from Cave 0)
    if (cave_item_taken[cave_idx]) {
        // Person, dialogue, and taken items are gone!
        spr_set(1); spr_hide();
        spr_set(4); spr_hide();
        spr_set(5); spr_hide();
        spr_set(10); spr_hide();
        cave_text_done = 1;
    } else {
        // Sprite 1: Cave NPC (120, 96 in authentic NES coordinates)
        spr_set(1);
        spr_x(120);
        spr_y(96);
        spr_pattern(npc_pat);
        spr_pal(npc_pal);
        spr_pri(1);
        spr_ctrl(FLIP_X_MASK, NO_FLIP_X);
        spr_show();

        // Sprite 4: Center Item (Item 1, e.g. Wooden Sword at 120, 112)
        spr_set(4);
        if (item1 != 63) {
            spr_x(120);
            spr_y(112);
            spr_pattern(get_item_sprite_pattern(item1));
            spr_pal(get_item_sprite_pal(item1));
            spr_pri(1);
            spr_ctrl(FLIP_X_MASK, NO_FLIP_X);
            spr_show();
        } else {
            spr_hide();
        }

        // Sprite 5: Left Item (Item 0)
        spr_set(5);
        if (item0 != 63) {
            spr_x(88);
            spr_y(112);
            spr_pattern(get_item_sprite_pattern(item0));
            spr_pal(get_item_sprite_pal(item0));
            spr_pri(1);
            spr_ctrl(FLIP_X_MASK, NO_FLIP_X);
            spr_show();
        } else {
            spr_hide();
        }

        // Sprite 10: Right Item (Item 2)
        spr_set(10);
        if (item2 != 63) {
            spr_x(152);
            spr_y(112);
            spr_pattern(get_item_sprite_pattern(item2));
            spr_pal(get_item_sprite_pal(item2));
            spr_pri(1);
            spr_ctrl(FLIP_X_MASK, NO_FLIP_X);
            spr_show();
        } else {
            spr_hide();
        }

        // Print Ware Prices below pedestals if any
        if (ow_cave_price[cave_idx * 3] > 0) {
            cave_print_num(10, 10, ow_cave_price[cave_idx * 3]);
        }
        if (ow_cave_price[cave_idx * 3 + 1] > 0) {
            cave_print_num(14, 10, ow_cave_price[cave_idx * 3 + 1]);
        }
        if (ow_cave_price[cave_idx * 3 + 2] > 0) {
            cave_print_num(18, 10, ow_cave_price[cave_idx * 3 + 2]);
        }

        // Initialize typewriter text effect
        cave_text_line = 0;
        cave_text_char_idx = 0;
        cave_text_timer = 4;
        cave_text_done = 0;
    }

    // Sprite 2: Left Fire (72, 96 in authentic NES coordinates)
    spr_set(2);
    spr_x(72);
    spr_y(96);
    spr_pattern(0x22C0); // Sprite 11: Fire
    spr_pal(1);
    spr_pri(1);
    spr_ctrl(FLIP_X_MASK, NO_FLIP_X);
    spr_show();

    // Sprite 3: Right Fire (168, 96 in authentic NES coordinates)
    spr_set(3);
    spr_x(168);
    spr_y(96);
    spr_pattern(0x22C0); // Sprite 11: Fire
    spr_pal(1);
    spr_pri(1);
    spr_ctrl(FLIP_X_MASK, FLIP_X);
    spr_show();

    disp_on();
}

void handle_player_death(void)
{
    unsigned char step;
    unsigned char rot;
    unsigned char i;

    // 1. Play death sound effect & stop current background music
    music_stop();
    sfx_die();

    // 2. Hide any weapon, enemy projectile, or item drops
    spr_set(4);  spr_hide();
    spr_set(5);  spr_hide();
    spr_set(10); spr_hide();
    rock_active = 0;
    drop_active = 0;
    attack_timer = 0;
    link_invincible = 0;

    // 3. Death spin animation (Link spins in all 4 directions 4 times)
    for (step = 0; step < 16; step++) {
        rot = step & 3;
        spr_set(0);
        spr_x(link_x);
        spr_y(link_y);
        spr_pal(0);
        spr_pri(1);
        if (rot == 0) {
            spr_pattern(0x2000); // Face DOWN
            spr_ctrl(FLIP_X_MASK, NO_FLIP_X);
        } else if (rot == 1) {
            spr_pattern(0x2100); // Face LEFT
            spr_ctrl(FLIP_X_MASK, FLIP_X);
        } else if (rot == 2) {
            spr_pattern(0x2080); // Face UP
            spr_ctrl(FLIP_X_MASK, NO_FLIP_X);
        } else {
            spr_pattern(0x2100); // Face RIGHT
            spr_ctrl(FLIP_X_MASK, NO_FLIP_X);
        }
        spr_show();
        satb_update();
        for (i = 0; i < 4; i++) {
            vsync();
            update_zelda_music();
        }
    }

    // 4. Brief pause / collapse
    for (i = 0; i < 30; i++) {
        vsync();
        update_zelda_music();
    }

    // 5. Restore full starting health (3 hearts = 6 half-hearts)
    link_hp = 6;
    link_invincible = 60;

    // 6. Respawn at entrance of dungeon or overworld
    if (in_dungeon) {
        dungeon_room = 0x73;
        link_x = 120;
        link_y = 188;
        link_dir = DIR_UP;
        load_underworld_room(0x73);
        music_play(TRACK_UNDERWORLD);
    } else {
        in_cave = 0;
        current_room = 0x77;
        link_x = 120;
        link_y = 128;
        link_dir = DIR_UP;
        load_vram(0x0000, hud_bat, 192);
        load_overworld_room(0x77);
        music_play(TRACK_OVERWORLD);
    }

    // 7. Refresh HUD hearts & sword
    update_hud_hearts(link_hp);
    if (has_sword) update_hud_sword();

    // 8. Place Link sprite safely facing UP
    spr_set(0);
    spr_x(link_x);
    spr_y(link_y);
    spr_pattern(0x2080);
    spr_pal(0);
    spr_pri(1);
    spr_ctrl(FLIP_X_MASK, NO_FLIP_X);
    spr_show();
    satb_update();
}

void enter_select_screen(void)
{
    unsigned char i;
    disp_off();
    vsync();
    set_screen_size(SCR_SIZE_32x32);
    scroll(0, 0, 0, 0, 223, 0xC0);

    for (i = 0; i < 64; i++) {
        spr_set(i);
        spr_hide();
    }
    satb_update();

    set_select_palettes();
    load_vram(0x1000, title_bg_tiles, 4096);
    load_vram(0x0000, select_bat, 896);
    load_vram(0x2000, link_sprites, 4224);

    // Sprite 0: Heart Cursor
    spr_set(0);
    spr_x(36);
    spr_y(select_cursor_y[0]);
    spr_pattern(0x2240); // Sprite 9: Heart Cursor
    spr_pal(1);
    spr_pri(1);
    spr_ctrl(FLIP_X_MASK, NO_FLIP_X);
    spr_show();

    // Save Slot Link Icons
    for (i = 1; i <= 3; i++) {
        spr_set(i);
        spr_x(48);
        spr_y(56 + i * 24);
        spr_pattern(0x2000);
        spr_pal(0);
        spr_pri(1);
        spr_ctrl(FLIP_X_MASK, NO_FLIP_X);
        spr_show();
    }

    for (i = 4; i < 64; i++) {
        spr_set(i);
        spr_hide();
    }
    satb_update();

    select_slot = 0;
    disp_on();
    game_state = STATE_SELECT;
}

void enter_title_screen(void)
{
    unsigned char i;
    disp_off();
    vsync();
    set_screen_size(SCR_SIZE_32x32);
    scroll(0, 0, 0, 0, 223, 0xC0);

    for (i = 0; i < 64; i++) {
        spr_set(i);
        spr_hide();
    }

    set_title_palettes();
    load_vram(0x1000, title_bg_tiles, 4096);
    load_vram(0x0000, title_bat, 896);
    load_vram(0x2000, title_sprites, 896);

    // Authentic Title Screen Sprites (Ornate Corners & Sword Hilt)
    spr_set(1); spr_x(40);  spr_y(39);  spr_pattern(0x2000); spr_pal(2); spr_pri(1); spr_ctrl(FLIP_MAS, NO_FLIP); spr_show();
    spr_set(2); spr_x(200); spr_y(39);  spr_pattern(0x2000); spr_pal(2); spr_pri(1); spr_ctrl(FLIP_MAS, FLIP_X); spr_show();
    spr_set(3); spr_x(40);  spr_y(119); spr_pattern(0x2000); spr_pal(2); spr_pri(1); spr_ctrl(FLIP_MAS, FLIP_Y); spr_show();
    spr_set(4); spr_x(200); spr_y(119); spr_pattern(0x2000); spr_pal(2); spr_pri(1); spr_ctrl(FLIP_MAS, FLIP_X | FLIP_Y); spr_show();
    spr_set(5); spr_x(116); spr_y(87);  spr_pattern(0x2040); spr_pal(1); spr_pri(1); spr_ctrl(FLIP_MAS, NO_FLIP); spr_show();
    for (i = 6; i < 64; i++) {
        spr_set(i);
        spr_hide();
    }
    satb_update();

    wave_y[0] = 182;
    wave_y[1] = 200;
    wave_y[2] = 216;
    title_anim = 0;
    title_idle = 0;
    disp_on();
    game_state = STATE_TITLE;
}

void enter_title_story(void)
{
    unsigned char i;
    disp_off();
    vsync();

    for (i = 0; i < 64; i++) {
        spr_set(i);
        spr_hide();
    }
    satb_update();

    set_story_palettes();
    set_screen_size(SCR_SIZE_32x64);
    load_vram(0x0000, story_scroll_bat, 2048);
    story_v_scroll = 0;
    story_timer = 0;
    scroll(0, 0, 0, 0, 223, 0xC0);
    disp_on();
    game_state = STATE_TITLE_STORY;
}

void update_title_screen(void)
{
    unsigned char crest_frame;
    unsigned char w_idx, w_y;
    unsigned int  w_left_pat, w_right_pat;
    unsigned int  jt;

    title_anim++;
    title_idle++;

    // Authentic Triforce color cycling
    if ((title_anim & 7) == 0) {
        if ((title_anim >> 3) & 1) {
            set_color_rgb(17, 7, 6, 1);
            set_color_rgb(18, 7, 7, 4);
        } else {
            set_color_rgb(17, 5, 3, 0);
            set_color_rgb(18, 7, 6, 1);
        }
    }
    // Authentic Waterfall wave animation
    if ((title_anim & 3) == 0) {
        if ((title_anim >> 2) & 1) {
            set_color_rgb(50, 4, 7, 6);
            set_color_rgb(51, 1, 4, 6);
        } else {
            set_color_rgb(50, 1, 4, 6);
            set_color_rgb(51, 4, 7, 6);
        }
    }

    // Authentic Sword Sparkle Glint at (116, 87)
    spr_set(6);
    if ((title_anim & 63) < 8) {
        spr_x(116);
        spr_y(87);
        spr_pattern(0x2080);
        spr_pal(0);
        spr_pri(1);
        spr_ctrl(FLIP_MAS, NO_FLIP);
        spr_show();
    } else if ((title_anim & 63) < 16) {
        spr_x(116);
        spr_y(87);
        spr_pattern(0x20C0);
        spr_pal(0);
        spr_pri(1);
        spr_ctrl(FLIP_MAS, NO_FLIP);
        spr_show();
    } else {
        spr_hide();
    }

    // Authentic Waterfall Crest at Y = 168 (alternates every 16 frames)
    crest_frame = (title_anim >> 4) & 1;
    spr_set(7);
    spr_x(80);
    spr_y(168);
    spr_pattern(crest_frame ? 0x2180 : 0x2100);
    spr_pal(3);
    spr_pri(1);
    spr_ctrl(FLIP_MAS, NO_FLIP);
    spr_show();

    spr_set(8);
    spr_x(96);
    spr_y(168);
    spr_pattern(crest_frame ? 0x21C0 : 0x2140);
    spr_pal(3);
    spr_pri(1);
    spr_ctrl(FLIP_MAS, NO_FLIP);
    spr_show();

    // Authentic Waterfall Waves rolling down
    if ((title_anim & 1) == 0) {
        for (w_idx = 0; w_idx < 3; w_idx++) {
            wave_y[w_idx] += 2;
            if (wave_y[w_idx] >= 226) wave_y[w_idx] = 178;
        }
    }
    for (w_idx = 0; w_idx < 3; w_idx++) {
        w_y = wave_y[w_idx];
        if (w_y < 185) {
            w_left_pat = 0x2200;
            w_right_pat = 0x2240;
        } else if (w_y < 194) {
            w_left_pat = 0x2280;
            w_right_pat = 0x22C0;
        } else {
            w_left_pat = 0x2300;
            w_right_pat = 0x2340;
        }
        spr_set(9 + w_idx * 2);
        spr_x(80);
        spr_y(w_y);
        spr_pattern(w_left_pat);
        spr_pal(3);
        spr_pri(1);
        spr_ctrl(FLIP_MAS, NO_FLIP);
        spr_show();

        spr_set(10 + w_idx * 2);
        spr_x(96);
        spr_y(w_y);
        spr_pattern(w_right_pat);
        spr_pal(3);
        spr_pri(1);
        spr_ctrl(FLIP_MAS, NO_FLIP);
        spr_show();
    }

    satb_update();

    jt = joytrg(0);
    if (jt & (JOY_STRT | JOY_A | JOY_B | JOY_I | JOY_II | JOY_SLCT)) {
        enter_select_screen();
        return;
    }

    if (title_idle >= 480) {
        enter_title_story();
        return;
    }
}

void update_title_story(void)
{
    unsigned int jt;
    jt = joytrg(0);
    if (jt & (JOY_STRT | JOY_A | JOY_B | JOY_I | JOY_II | JOY_SLCT)) {
        enter_select_screen();
        return;
    }

    story_timer++;
    if (story_v_scroll < 224) {
        if ((story_timer & 1) == 0) {
            story_v_scroll++;
            scroll(0, 0, story_v_scroll, 0, 223, 0xC0);
        }
    } else if (story_timer < (448 + 360)) {
        scroll(0, 0, 224, 0, 223, 0xC0);
    } else if (story_v_scroll < 448) {
        if ((story_timer & 1) == 0) {
            story_v_scroll++;
            scroll(0, 0, story_v_scroll, 0, 223, 0xC0);
        }
    } else {
        enter_title_treasures();
        return;
    }
}

void stream_treasures_row(unsigned int row)
{
    unsigned char c;
    unsigned int vram_addr;
    unsigned char col;
    unsigned char i;
    char ch;
    unsigned int tile;
    const unsigned char *txt;

    vram_addr = (row & 63) * 32;

    if (row == 2) {
        // Ivy garland (pal 3) + " ALL OF TREASURES " (pal 0) + Ivy garland (pal 3)
        treasures_row_words[0] = 0x31E4;
        treasures_row_words[1] = 0x31E5;
        treasures_row_words[2] = 0x31E4;
        treasures_row_words[3] = 0x31E5;
        treasures_row_words[4] = 0x31E4;
        treasures_row_words[5] = 0x31E5;
        treasures_row_words[6] = 0x31E6;

        treasures_row_words[7]  = 0x0124; // ' '
        treasures_row_words[8]  = 0x010A; // 'A'
        treasures_row_words[9]  = 0x0115; // 'L'
        treasures_row_words[10] = 0x0115; // 'L'
        treasures_row_words[11] = 0x0124; // ' '
        treasures_row_words[12] = 0x0118; // 'O'
        treasures_row_words[13] = 0x010F; // 'F'
        treasures_row_words[14] = 0x0124; // ' '
        treasures_row_words[15] = 0x011D; // 'T'
        treasures_row_words[16] = 0x011B; // 'R'
        treasures_row_words[17] = 0x010E; // 'E'
        treasures_row_words[18] = 0x010A; // 'A'
        treasures_row_words[19] = 0x011C; // 'S'
        treasures_row_words[20] = 0x011E; // 'U'
        treasures_row_words[21] = 0x011B; // 'R'
        treasures_row_words[22] = 0x010E; // 'E'
        treasures_row_words[23] = 0x011C; // 'S'
        treasures_row_words[24] = 0x0124; // ' '

        treasures_row_words[25] = 0x31E6;
        treasures_row_words[26] = 0x31E4;
        treasures_row_words[27] = 0x31E5;
        treasures_row_words[28] = 0x31E4;
        treasures_row_words[29] = 0x31E5;
        treasures_row_words[30] = 0x31E4;
        treasures_row_words[31] = 0x31E5;
    } else {
        for (c = 0; c < 32; c++) {
            treasures_row_words[c] = 0x0124;
        }
        for (c = 0; c < NUM_TREASURE_TEXTS; c++) {
            if (treasure_text_row[c] == row) {
                col = treasure_text_col[c];
                txt = treasure_text_buf + treasure_text_offset[c];
                for (i = 0; txt[i] != 0; i++) {
                    ch = txt[i];
                    if (ch == ' ') tile = 0x24;
                    else if (ch >= '0' && ch <= '9') tile = ch - '0';
                    else tile = 0x0A + (ch - 'A');
                    treasures_row_words[col + i] = 0x0100 + tile;
                }
            }
        }
    }
    load_vram(vram_addr, treasures_row_words, 32);
}

void enter_title_treasures(void)
{
    unsigned char i;
    disp_off();
    vsync();

    for (i = 0; i < 64; i++) {
        spr_set(i);
        spr_hide();
    }
    satb_update();

    set_treasures_palettes();
    set_screen_size(SCR_SIZE_32x64);

    for (i = 0; i < 64; i++) {
        stream_treasures_row(i);
    }

    load_vram(0x2000, treasures_sprites, 2880);

    treasures_scroll_y = 0;
    treasures_timer = 0;
    scroll(0, 0, 0, 0, 223, 0xC0);
    disp_on();
    game_state = STATE_TITLE_TREASURES;
}

void update_title_treasures(void)
{
    unsigned int jt;
    unsigned char i;
    unsigned int incoming_row;
    int sy;
    int world_y;
    int piece_y;
    unsigned char spr_num;
    unsigned char sx_idx, sy_idx;

    jt = joytrg(0);
    if (jt & (JOY_STRT | JOY_A | JOY_B | JOY_I | JOY_II | JOY_SLCT)) {
        enter_select_screen();
        return;
    }

    treasures_timer++;

    if (treasures_scroll_y < 1136) {
        if ((treasures_timer & 1) == 0) {
            treasures_scroll_y++;
            scroll(0, 0, treasures_scroll_y, 0, 223, 0xC0);

            if ((treasures_scroll_y & 7) == 0) {
                incoming_row = (treasures_scroll_y + 224) >> 3;
                if (incoming_row < 185) {
                    stream_treasures_row(incoming_row);
                }
            }
        }
    } else if (treasures_timer < (1136 * 2 + 360)) {
        scroll(0, 0, 1136, 0, 223, 0xC0);
    } else {
        for (i = 0; i < 64; i++) {
            spr_set(i);
            spr_hide();
        }
        satb_update();
        enter_title_screen();
        return;
    }

    // Update item hardware sprites
    for (i = 0; i < 18; i++) {
        world_y = 80 + i * 64;
        sy = world_y - treasures_scroll_y;

        if (sy >= 0 && sy <= 224) {
            if (i == 17) {
                spr_set(i * 2 + 1);
                spr_hide();
            } else {
                spr_set(i * 2 + 1);
                spr_x(68);
                spr_y(sy);
                spr_pattern(0x2000 + (i * 2) * 0x40);
                spr_pal(treasures_left_pals[i]);
                spr_pri(1);
                spr_ctrl(FLIP_MAS, NO_FLIP);
                spr_show();
            }

            spr_set(i * 2 + 2);
            spr_x(i == 17 ? 120 : 172);
            spr_y(sy);
            spr_pattern(0x2000 + (i * 2 + 1) * 0x40);
            spr_pal(treasures_right_pals[i]);
            spr_pri(1);
            spr_ctrl(FLIP_MAS, NO_FLIP);
            spr_show();
        } else {
            spr_set(i * 2 + 1);
            spr_hide();
            spr_set(i * 2 + 2);
            spr_hide();
        }
    }

    // Update Link holding sign (3x3 sprites at world Y = 1272)
    sy = 1272 - treasures_scroll_y;
    if (sy >= -48 && sy <= 224) {
        for (sy_idx = 0; sy_idx < 3; sy_idx++) {
            for (sx_idx = 0; sx_idx < 3; sx_idx++) {
                spr_num = 37 + sy_idx * 3 + sx_idx;
                piece_y = sy + sy_idx * 16;
                if (piece_y >= 0 && piece_y <= 224) {
                    spr_set(spr_num);
                    spr_x(104 + sx_idx * 16);
                    spr_y(piece_y);
                    spr_pattern(0x2000 + (36 + sy_idx * 3 + sx_idx) * 0x40);
                    spr_pal(0);
                    spr_pri(1);
                    spr_ctrl(FLIP_MAS, NO_FLIP);
                    spr_show();
                } else {
                    spr_set(spr_num);
                    spr_hide();
                }
            }
        }
    } else {
        for (i = 37; i <= 45; i++) {
            spr_set(i);
            spr_hide();
        }
    }

    satb_update();
}


main()
{
    unsigned char walk_frame;
    unsigned int  j;
    unsigned int  jt;
    unsigned int  spr_pattern_addr;
    unsigned char spr_flip;
    unsigned char i;
    int           sword_x;
    int           sword_y;
    unsigned int  sword_pat;
    unsigned char sword_ctrl;
    int           tile_x;
    int           tile_y;
    unsigned char standing_tile;
    unsigned char cave_val;
    char          ch;
    const char   *c_line1;
    const char   *c_line2;
    unsigned char l1_len;

    init_256x224();
    disp_off();
    vsync();

    init_satb();
    init_zelda_sound();

    link_x = 120;
    link_y = 128;
    link_dir = DIR_UP;
    walk_frame = 0;
    anim_counter = 0;
    frame_counter = 0;
    in_cave = 0;
    has_sword = 0;
    flame_flicker = 0;
    link_hp = 6;
    link_rupees = 0;
    link_invincible = 0;

    enter_title_screen();

    while (1) {
        vsync();
        update_zelda_music();

        if (game_state == STATE_TITLE) {
            update_title_screen();
        } else if (game_state == STATE_TITLE_STORY) {
            update_title_story();
        } else if (game_state == STATE_TITLE_TREASURES) {
            update_title_treasures();
        } else if (game_state == STATE_SELECT) {
            jt = joytrg(0);
            if (jt & JOY_UP) {
                if (select_slot > 0) select_slot--;
                else select_slot = 4;
                spr_set(0);
                spr_y(select_cursor_y[select_slot]);
                satb_update();
            } else if (jt & (JOY_DOWN | JOY_SLCT)) {
                if (select_slot < 4) select_slot++;
                else select_slot = 0;
                spr_set(0);
                spr_y(select_cursor_y[select_slot]);
                satb_update();
            } else if (jt & (JOY_STRT | JOY_A | JOY_I)) {
                if (select_slot == 0) {
                    disp_off();
                    vsync();

                    set_game_palettes();
                    load_vram(0x1000, ow_bg_tiles, 4096);
                    load_vram(0x2000, link_sprites, 4224);

                    for (i = 1; i < 16; i++) {
                        spr_set(i);
                        spr_hide();
                    }

                    in_cave = 0;
                    has_sword = 0;
                    flame_flicker = 0;
    title_anim = 0;
                    link_hp = 6;
                    link_rupees = 0;
                    link_invincible = 0;

                    // Load authentic HUD BAT into Rows 0..5 (192 words = 6 rows * 32 cols)
                    load_vram(0x0000, hud_bat, 192);

                    // Load authentic Overworld starting room 0x77
                    load_overworld_room(0x77);

                    link_x = 120;
                    link_y = 128;
                    link_dir = DIR_UP;

                    spr_set(0);
                    spr_x(link_x);
                    spr_y(link_y);
                    spr_pattern(0x2080);
                    spr_pal(0);
                    spr_pri(1);
                    spr_ctrl(FLIP_X_MASK, NO_FLIP_X);
                    spr_show();

                    satb_update();
                    disp_on();
                    music_play(TRACK_OVERWORLD);
                    game_state = STATE_GAME;
                }
            }
        } else if (game_state == STATE_INVENTORY) {
            // Inventory Subscreen Loop
            jt = joytrg(0);
            if (jt & JOY_LEFT) {
                if (inv_cursor_x > 0) inv_cursor_x--;
                else inv_cursor_x = 3;
            }
            if (jt & JOY_RIGHT) {
                if (inv_cursor_x < 3) inv_cursor_x++;
                else inv_cursor_x = 0;
            }
            if (jt & (JOY_UP | JOY_DOWN)) {
                inv_cursor_y = 1 - inv_cursor_y;
            }

            // Keep weapons box clean as in reference screenshot
            spr_set(12);
            spr_hide();

            // Link stands inside Triforce facing UP
            spr_set(0);
            spr_x(120);
            spr_y(128);
            spr_pattern(0x2080);
            spr_pal(0);
            spr_pri(1);
            spr_ctrl(FLIP_X_MASK, NO_FLIP_X);
            spr_show();

            // Bottom HUD Sword in Box A
            spr_set(11);
            if (has_sword) {
                spr_x(148);
                spr_y(192);
                spr_pattern(0x2300);
                spr_pal(3);
                spr_pri(1);
                spr_ctrl(0, 0);
                spr_show();
            } else {
                spr_hide();
            }

            satb_update();

            // Press START to exit Inventory Subscreen and return to game
            if (jt & JOY_STRT) {
                sfx_pause();
                spr_set(12);
                spr_hide();

                // Restore HUD at top (0x0000)
                load_vram(0x0000, hud_bat, 192);
                update_hud_hearts(link_hp);
                update_hud_rupees(link_rupees);
                update_hud_keys(link_keys);
                if (has_sword) update_hud_sword();

                // Restore playfield
                if (in_cave) {
                    load_cave(current_cave_idx);
                } else if (in_dungeon) {
                    load_underworld_room(dungeon_room);
                } else {
                    load_overworld_room(current_room);
                }

                // Restore Link sprite
                spr_set(0);
                spr_x(link_x);
                spr_y(link_y);
                spr_show();
                satb_update();
                game_state = STATE_GAME;
                continue;
            }
        } else {
            // Gameplay Mode
            frame_counter++;
            j = joy(0);
            jt = joytrg(0);

            // Press START in gameplay mode to enter Inventory Subscreen
            if (jt & JOY_STRT) {
                sfx_pause();
                // Hide gameplay sprites (enemies, rocks, drops)
                for (i = 0; i < 4; i++) {
                    spr_set(i + 1); spr_hide();
                }
                spr_set(5); spr_hide();
                spr_set(10); spr_hide();
                spr_set(12); spr_hide();

                // Move HUD Sword Sprite 11 to bottom HUD if acquired
                spr_set(11);
                if (has_sword) {
                    spr_x(148);
                    spr_y(192);
                    spr_pattern(0x2300);
                    spr_pal(3);
                    spr_pri(1);
                    spr_ctrl(0, 0);
                    spr_show();
                } else {
                    spr_hide();
                }

                // Link stands inside Triforce
                spr_set(0);
                spr_x(120);
                spr_y(128);
                spr_pattern(0x2080);
                spr_pal(0);
                spr_pri(1);
                spr_ctrl(FLIP_X_MASK, NO_FLIP_X);
                spr_show();

                // Load 32 cols x 28 rows Subscreen BAT into VRAM 0x0000
                load_vram(0x0000, subscreen_bat, 896);
                update_subscreen_hud();
                satb_update();
                game_state = STATE_INVENTORY;
                continue;
            }

            // Press SELECT to test: 1) half-heart display, 2) sword in Box A, 3) Room 0x65 bridge, 4) Room 0x2D ladder
            if (jt & JOY_SLCT) {
                if (link_hp == 6 && !has_sword && current_room == 0x77) {
                    link_hp = 5;
                    update_hud_hearts(link_hp);
                } else if (!has_sword && current_room == 0x77) {
                    has_sword = 1;
                    update_hud_sword();
                } else if (current_room == 0x77) {
                    current_room = 0x65;
                    load_overworld_room(0x65);
                    link_x = 128;
                    link_y = 128;
                    link_dir = DIR_LEFT;
                } else if (current_room == 0x65) {
                    current_room = 0x2D;
                    load_overworld_room(0x2D);
                    link_x = 36;
                    link_y = 128;
                    link_dir = DIR_UP;
                } else {
                    current_room = 0x77;
                    load_overworld_room(0x77);
                    link_x = 120;
                    link_y = 128;
                    link_hp = 6;
                    has_sword = 0;
                    update_hud_hearts(link_hp);
                    update_hud_sword();
                }
            }

            if (link_invincible > 0) {
                link_invincible--;
            }

            // Check attack button if Link has sword and not attacking and not in cave
            if (has_sword && attack_timer == 0 && !in_cave) {
                if (jt & (JOY_A | JOY_B | JOY_I | JOY_II)) {
                    attack_timer = 12;
                    sfx_sword();
                }
            }

            if (attack_timer > 0) {
                attack_timer--;
                // Authentic NES Link thrust sword positions
                if (link_dir == DIR_UP) {
                    sword_x = link_x - 1;
                    sword_y = link_y - 10;
                    sword_pat = 0x2300; // Vertical Sword (Sprite 12)
                    sword_ctrl = NO_FLIP_X | NO_FLIP_Y;
                } else if (link_dir == DIR_DOWN) {
                    sword_x = link_x + 1;
                    sword_y = link_y + 13;
                    sword_pat = 0x2300; // Vertical Sword flipped Y
                    sword_ctrl = NO_FLIP_X | FLIP_Y;
                } else if (link_dir == DIR_RIGHT) {
                    sword_x = link_x + 11;
                    sword_y = link_y + 3;
                    sword_pat = 0x2340; // Horizontal Sword (Sprite 13)
                    sword_ctrl = NO_FLIP_X | NO_FLIP_Y;
                } else { // DIR_LEFT
                    sword_x = link_x - 11;
                    sword_y = link_y + 3;
                    sword_pat = 0x2340; // Horizontal Sword flipped X
                    sword_ctrl = FLIP_X | NO_FLIP_Y;
                }

                spr_set(4);
                spr_x(sword_x);
                spr_y(sword_y);
                spr_pattern(sword_pat);
                spr_pal(3); // Wooden Sword
                spr_pri(1);
                spr_ctrl(FLIP_X_MASK | FLIP_Y_MASK, sword_ctrl);
                spr_show();

                // Hit detection against active enemies
                for (i = 0; i < 4; i++) {
                    if (enemy_active[i] == 1) {
                        if (sword_x + 14 >= enemy_x[i] + 2 &&
                            sword_x + 2  <= enemy_x[i] + 14 &&
                            sword_y + 14 >= enemy_y[i] + 2 &&
                            sword_y + 2  <= enemy_y[i] + 14) {
                            enemy_hp[i]--;
                            sfx_hit();

                            // Knockback away from sword thrust
                            if (link_dir == DIR_UP)         enemy_y[i] -= 16;
                            else if (link_dir == DIR_DOWN)  enemy_y[i] += 16;
                            else if (link_dir == DIR_LEFT)  enemy_x[i] -= 16;
                            else if (link_dir == DIR_RIGHT) enemy_x[i] += 16;

                            if (enemy_hp[i] <= 0) {
                                enemy_active[i] = 2; // Defeat puff state
                                enemy_puff[i] = 16;
                            }
                        }
                    }
                }
            } else if (cave_lift_timer > 0) {
                // Link is locked in place lifting the item aloft
                anim_counter = 0;
            } else {
                if (!in_cave || has_sword) {
                    spr_set(4);
                    spr_hide();
                }

                if (j & JOY_UP) {
                    link_dir = DIR_UP;
                    if (is_walkable(link_x + 3, link_y + 7) && is_walkable(link_x + 12, link_y + 7)) {
                        link_y--;
                    }
                    anim_counter++;
                } else if (j & JOY_DOWN) {
                    link_dir = DIR_DOWN;
                    if (is_walkable(link_x + 3, link_y + 16) && is_walkable(link_x + 12, link_y + 16)) {
                        link_y++;
                    }
                    anim_counter++;
                } else if (j & JOY_LEFT) {
                    link_dir = DIR_LEFT;
                    if (is_walkable(link_x - 1, link_y + 8) && is_walkable(link_x - 1, link_y + 15)) {
                        link_x--;
                    }
                    anim_counter++;
                } else if (j & JOY_RIGHT) {
                    link_dir = DIR_RIGHT;
                    if (is_walkable(link_x + 16, link_y + 8) && is_walkable(link_x + 16, link_y + 15)) {
                        link_x++;
                    }
                    anim_counter++;
                } else {
                    anim_counter = 0;
                }
            }

            walk_frame = (anim_counter >> 3) & 1;
            if (cave_lift_timer > 0) {
                spr_pattern_addr = 0x2800; // Sprite 32: Link 1-handed item lift pose
                spr_flip = NO_FLIP_X;
            } else {
                switch (link_dir) {
                    case DIR_DOWN:
                        // 0x2180 = Sprite 6: Link Thrust DOWN
                        spr_pattern_addr = (attack_timer > 0) ? 0x2180 : (walk_frame ? 0x2040 : 0x2000);
                        spr_flip = NO_FLIP_X;
                        break;
                    case DIR_UP:
                        // 0x21C0 = Sprite 7: Link Thrust UP
                        spr_pattern_addr = (attack_timer > 0) ? 0x21C0 : (walk_frame ? 0x20C0 : 0x2080);
                        spr_flip = NO_FLIP_X;
                        break;
                    case DIR_RIGHT:
                        // 0x2200 = Sprite 8: Link Thrust SIDE
                        spr_pattern_addr = (attack_timer > 0) ? 0x2200 : (walk_frame ? 0x2140 : 0x2100);
                        spr_flip = NO_FLIP_X;
                        break;
                    case DIR_LEFT:
                        // 0x2200 = Sprite 8: Link Thrust SIDE (flipped X)
                        spr_pattern_addr = (attack_timer > 0) ? 0x2200 : (walk_frame ? 0x2140 : 0x2100);
                        spr_flip = FLIP_X;
                        break;
                }
            }

            if (in_dungeon) {
                // Underworld Door Unlocking & 4-Direction Room Transitions
                try_unlock_dungeon_doors();

                if (link_y <= 54 && link_dir == DIR_UP) {
                    if (dungeon_room >= 16) {
                        dungeon_room -= 16;
                        link_y = 188;
                        link_x = 120;
                        load_underworld_room(dungeon_room);
                    } else {
                        link_y = 54;
                    }
                } else if (link_y >= 200 && link_dir == DIR_DOWN) {
                    if (dungeon_room == 0x73) {
                        // Exit back to the overworld room we came from
                        in_dungeon = 0;
                        disp_off();
                        vsync();
                        set_game_palettes();
                        load_vram(0x1000, ow_bg_tiles, 4096);
                        load_vram(0x0000, hud_bat, 192);
                        if (has_sword) update_hud_sword();
                        load_overworld_room(dungeon_return_room);
                        music_play(TRACK_OVERWORLD);
                        link_x = dungeon_return_x;
                        link_y = dungeon_return_y;
                        link_dir = DIR_DOWN;
                        disp_on();
                        continue;
                    } else if (dungeon_room < 112) {
                        dungeon_room += 16;
                        link_y = 60;
                        link_x = 120;
                        load_underworld_room(dungeon_room);
                    } else {
                        link_y = 200;
                    }
                } else if (link_x <= 24 && link_dir == DIR_LEFT) {
                    if ((dungeon_room & 0x0F) > 0) {
                        dungeon_room -= 1;
                        link_x = 216;
                        link_y = 132;
                        load_underworld_room(dungeon_room);
                    } else {
                        link_x = 24;
                    }
                } else if (link_x >= 216 && link_dir == DIR_RIGHT) {
                    if ((dungeon_room & 0x0F) < 15) {
                        dungeon_room += 1;
                        link_x = 24;
                        link_y = 132;
                        load_underworld_room(dungeon_room);
                    } else {
                        link_x = 216;
                    }
                }

                update_enemies();
            } else if (!in_cave) {
                // Check cave / dungeon entrance tile under Link's center
                tile_x = (link_x + 8) >> 3;
                tile_y = (link_y + 4 - 48) >> 3;
                if (tile_y >= 0 && tile_y < 22 && tile_x >= 0 && tile_x < 32) {
                    standing_tile = room_grid[(tile_y << 5) + tile_x];
                    if ((standing_tile == 0x24 || standing_tile == 0xF3) && link_dir == DIR_UP) {
                        cave_val = ow_level_block_b[current_room] >> 2;
                        if (cave_val >= 16) {
                            // Enter Cave
                            // Save overworld return coordinates
                            dungeon_return_room = current_room;
                            dungeon_return_x    = link_x;
                            dungeon_return_y    = link_y + 16;
                            load_cave(cave_val - 16);
                            link_x = 120;
                            link_y = 156;
                            link_dir = DIR_UP;
                        } else if (cave_val >= 1 && cave_val <= 9) {
                            // Enter Underworld Dungeon 1..9
                            // Save the overworld return coordinates before transitioning
                            dungeon_return_room = current_room;
                            dungeon_return_x    = link_x;
                            dungeon_return_y    = link_y + 16; // just below the entrance
                            in_dungeon = 1;
                            dungeon_level = cave_val;
                            dungeon_room = 0x73;
                            disp_off();
                            vsync();
                            set_underworld_palettes(dungeon_level);
                            load_vram(0x1000, uw_bg_tiles, 4096);
                            load_underworld_room(dungeon_room);
                            link_x = 120;
                            link_y = 188;
                            link_dir = DIR_UP;
                            music_play(TRACK_UNDERWORLD);
                            disp_on();
                        }
                    }
                }

                // Authentic Overworld 4-Direction Room Transitions across all 128 screens
                // Before transitioning: save the current room's enemy state (full/partial clear).
                if (link_x <= 2 && link_dir == DIR_LEFT) {
                    if ((current_room & 0x0F) > 0) {
                        ow_save_room_state(current_room);
                        current_room--;
                        link_x = 238;
                        load_overworld_room(current_room);
                    } else {
                        link_x = 2;
                    }
                } else if (link_x >= 242 && link_dir == DIR_RIGHT) {
                    if ((current_room & 0x0F) < 15) {
                        ow_save_room_state(current_room);
                        current_room++;
                        link_x = 4;
                        load_overworld_room(current_room);
                    } else {
                        link_x = 242;
                    }
                } else if (link_y <= 50 && link_dir == DIR_UP) {
                    if (current_room >= 16) {
                        ow_save_room_state(current_room);
                        current_room -= 16;
                        link_y = 208;
                        load_overworld_room(current_room);
                    } else {
                        link_y = 50;
                    }
                } else if (link_y >= 214 && link_dir == DIR_DOWN) {
                    if (current_room < 112) {
                        ow_save_room_state(current_room);
                        current_room += 16;
                        link_y = 54;
                        load_overworld_room(current_room);
                    } else {
                        link_y = 214;
                    }
                }

                update_enemies();

                // Octorok Rock Projectile Update & Render
                if (rock_active) {
                    if (rock_dir == DIR_DOWN)       rock_y += 2;
                    else if (rock_dir == DIR_UP)    rock_y -= 2;
                    else if (rock_dir == DIR_LEFT)  rock_x -= 2;
                    else if (rock_dir == DIR_RIGHT) rock_x += 2;

                    // Hit test against Link
                    if (link_invincible == 0) {
                        if (link_x + 12 >= rock_x + 4 &&
                            link_x + 4  <= rock_x + 12 &&
                            link_y + 14 >= rock_y + 4 &&
                            link_y + 4  <= rock_y + 12) {
                            if (link_hp > 0) link_hp--;
                            update_hud_hearts(link_hp);
                            rock_active = 0;
                            if (link_hp == 0) {
                                handle_player_death();
                                continue;
                            }
                            link_invincible = 30;
                            sfx_hit();
                        }
                    }

                    if (rock_x < 8 || rock_x > 240 || rock_y < 52 || rock_y > 216) {
                        rock_active = 0;
                    }

                    if (rock_active) {
                        spr_set(10);
                        spr_x(rock_x);
                        spr_y(rock_y);
                        spr_pattern(0x24C0); // Sprite 19: Rock projectile
                        spr_pal(1);
                        spr_pri(1);
                        spr_ctrl(FLIP_X_MASK, NO_FLIP_X);
                        spr_show();
                    } else {
                        spr_set(10);
                        spr_hide();
                    }
                } else {
                    spr_set(10);
                    spr_hide();
                }

                // Dropped Item Collection Update & Render
                if (drop_active) {
                    if (drop_timer > 0) drop_timer--;
                    else drop_active = 0;

                    // Link touches dropped item
                    if (link_x + 12 >= drop_x + 2 &&
                        link_x + 2  <= drop_x + 14 &&
                        link_y + 14 >= drop_y + 2 &&
                        link_y + 4  <= drop_y + 14) {
                        sfx_item();
                        if (drop_type == ITEM_HEART) {
                            if (link_hp < 6) {
                                link_hp += 2;
                                if (link_hp > 6) link_hp = 6;
                                update_hud_hearts(link_hp);
                            }
                        } else if (drop_type == ITEM_RUPEE) {
                            link_rupees++;
                            update_hud_rupees(link_rupees);
                        } else if (drop_type == ITEM_KEY) {
                            link_keys++;
                            update_hud_keys(link_keys);
                        }
                        drop_active = 0;
                    }

                    if (drop_active) {
                        spr_set(5);
                        spr_x(drop_x);
                        spr_y(drop_y);
                        if (drop_type == ITEM_HEART) {
                            spr_pattern(0x2500); // Sprite 20: Heart drop
                            spr_pal(1);
                        } else if (drop_type == ITEM_RUPEE) {
                            spr_pattern(0x2540); // Sprite 21: Rupee drop
                            spr_pal((frame_counter & 4) ? 0 : 2); // Blinking sparkle
                        } else if (drop_type == ITEM_KEY) {
                            spr_pattern(0x2680); // Sprite 26: Key drop
                            spr_pal(4);
                        }
                        spr_pri(1);
                        spr_ctrl(FLIP_X_MASK, NO_FLIP_X);
                        spr_show();
                    } else {
                        spr_set(5);
                        spr_hide();
                    }
                } else {
                    spr_set(5);
                    spr_hide();
                }
            } else {
                // Inside Cave Logic
                // 1. Flames flickering
                flame_flicker++;
                spr_set(2);
                spr_ctrl(FLIP_X_MASK, (flame_flicker & 8) ? FLIP_X : NO_FLIP_X);
                spr_set(3);
                spr_ctrl(FLIP_X_MASK, (flame_flicker & 8) ? NO_FLIP_X : FLIP_X);

                // 2. Old Man Blinking Animation before despawn
                if (cave_blink_timer > 0) {
                    cave_blink_timer--;
                    spr_set(1);
                    if (cave_blink_timer == 0) {
                        spr_hide(); // Despawn completely
                    } else if (cave_blink_timer & 2) {
                        spr_hide();
                    } else {
                        spr_show();
                    }
                }

                // 3. Letter-by-letter Message Typing
                if (!cave_text_done && !cave_item_taken[current_cave_idx]) {
                    c_line1 = ow_cave_texts[current_cave_idx << 1];
                    c_line2 = ow_cave_texts[(current_cave_idx << 1) + 1];

                    if (cave_text_timer > 0) {
                        cave_text_timer--;
                    } else {
                        cave_text_timer = 5; // 5-6 frames per character matching NES
                        if (cave_text_line == 0) {
                            if (c_line1[cave_text_char_idx] != '\0') {
                                ch = c_line1[cave_text_char_idx];
                                cave_print_char(6 + cave_text_char_idx, 4, ch);
                                if (ch != ' ') sfx_text_char();
                                cave_text_char_idx++;
                            } else {
                                cave_text_line = 1;
                                cave_text_char_idx = 0;
                            }
                        } else if (cave_text_line == 1) {
                            if (c_line2[cave_text_char_idx] != '\0') {
                                ch = c_line2[cave_text_char_idx];
                                cave_print_char(8 + cave_text_char_idx, 6, ch);
                                if (ch != ' ') sfx_text_char();
                                cave_text_char_idx++;
                            } else {
                                cave_text_done = 1;
                            }
                        }
                    }
                }

                // 4. Link Lifting Item Aloft (Sword Fanfare & Lock)
                if (cave_lift_timer > 0) {
                    cave_lift_timer--;
                    // Sprite 4: Sword held straight up above Link's right hand (x=link_x - 2, y=link_y - 16)
                    spr_set(4);
                    spr_x(link_x - 2);
                    spr_y(link_y - 16);
                    spr_pattern(0x2300); // Wooden Sword Vertical
                    spr_pal(3);          // Pal 3
                    spr_pri(1);
                    spr_ctrl(FLIP_X_MASK | FLIP_Y_MASK, NO_FLIP_X | NO_FLIP_Y);
                    spr_show();

                    if (cave_lift_timer == 0) {
                        // Fanfare complete! Link lowers sword and regains movement
                        spr_set(4);
                        spr_hide();
                        music_stop();
                    }
                }

                // 5. Cave Ware Pickups & Purchases
                // Left Ware (Sprite 5, x=88, y=112)
                if (cave_lift_timer == 0 && !cave_item_taken[current_cave_idx] &&
                    link_x >= 76 && link_x <= 100 && link_y >= 104 && link_y <= 128) {
                    if (ow_cave_item[current_cave_idx * 3] != 63) {
                        if (link_rupees >= ow_cave_price[current_cave_idx * 3]) {
                            link_rupees -= ow_cave_price[current_cave_idx * 3];
                            update_hud_rupees(link_rupees);
                            if (ow_cave_item[current_cave_idx * 3] == 26) {
                                if (link_hp < 6) link_hp = 6;
                                update_hud_hearts(link_hp);
                            }
                            sfx_item();
                            spr_set(5);
                            spr_hide();
                        }
                    }
                }

                // Center Ware (Sprite 4, x=120, y=112) - First Cave Wooden Sword!
                if (cave_lift_timer == 0 && !cave_item_taken[current_cave_idx] &&
                    link_x >= 108 && link_x <= 132 && link_y >= 104 && link_y <= 128) {
                    if (current_cave_idx == 0 && !has_sword) {
                        has_sword = 1;
                        cave_item_taken[0] = 1;
                        cave_clear_dialogue();
                        cave_text_done = 1;
                        cave_blink_timer = 24; // Old Man blinks and disappears
                        cave_lift_timer = 76;  // ~1.3 seconds fanfare lock
                        link_dir = DIR_DOWN;   // Face front
                        update_hud_sword();    // 'A' box in HUD immediately displays Wooden Sword
                        music_play(TRACK_FANFARE); // Play authentic Item Fanfare
                    } else if (ow_cave_item[current_cave_idx * 3 + 1] != 63) {
                        if (link_rupees >= ow_cave_price[current_cave_idx * 3 + 1]) {
                            link_rupees -= ow_cave_price[current_cave_idx * 3 + 1];
                            update_hud_rupees(link_rupees);
                            if (ow_cave_item[current_cave_idx * 3 + 1] == 26) {
                                if (link_hp < 6) link_hp = 6;
                                update_hud_hearts(link_hp);
                            }
                            sfx_item();
                            spr_set(4);
                            spr_hide();
                        }
                    }
                }

                // Right Ware (Sprite 10, x=152, y=112)
                if (cave_lift_timer == 0 && !cave_item_taken[current_cave_idx] &&
                    link_x >= 140 && link_x <= 164 && link_y >= 104 && link_y <= 128) {
                    if (ow_cave_item[current_cave_idx * 3 + 2] != 63) {
                        if (link_rupees >= ow_cave_price[current_cave_idx * 3 + 2]) {
                            link_rupees -= ow_cave_price[current_cave_idx * 3 + 2];
                            update_hud_rupees(link_rupees);
                            if (ow_cave_item[current_cave_idx * 3 + 2] == 26) {
                                if (link_hp < 6) link_hp = 6;
                                update_hud_hearts(link_hp);
                            }
                            sfx_item();
                            spr_set(10);
                            spr_hide();
                        }
                    }
                }

                // 6. Cave -> Overworld Exit (bottom doorway)
                if (cave_lift_timer == 0 && link_y >= 190 && link_dir == DIR_DOWN && link_x >= 104 && link_x <= 146) {
                    in_cave = 0;
                    for (i = 1; i <= 5; i++) {
                        spr_set(i);
                        spr_hide();
                    }
                    spr_set(10);
                    spr_hide();
                    load_vram(0x0000, hud_bat, 192);
                    if (has_sword) update_hud_sword();
                    load_overworld_room(dungeon_return_room);
                    link_x = dungeon_return_x;
                    link_y = dungeon_return_y;
                    link_dir = DIR_DOWN;
                    music_play(TRACK_OVERWORLD); // Resume overworld music
                }
            }

            // Update Link Sprite 0 (flashes when invincible)
            spr_set(0);
            spr_x(link_x);
            spr_y(link_y);
            spr_pattern(spr_pattern_addr);
            spr_pal(0);
            spr_pri(1);
            spr_ctrl(FLIP_X_MASK, spr_flip);
            if (link_invincible & 2) {
                spr_hide();
            } else {
                spr_show();
            }

            satb_update();

            // Safety check: if Link has no heart left, trigger player death
            if (link_hp == 0) {
                handle_player_death();
            }
        }
    }
}
