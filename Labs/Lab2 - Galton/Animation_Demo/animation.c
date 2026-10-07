
/**
 * ECE 4760 Lab 2 -- Digital Galton Board (RP2350 / Pico 2)
 * Built on Hunter Adams' (vha3@cornell.edu) VGA animation demo.
 *
 * Balls drop onto a 16-row peg board and land in a histogram. A rotary
 * encoder sets the ball count, bounciness, or gravity; each peg strike plays
 * a short DMA-driven sound. Both cores update and draw the balls at 60 fps.
 *
 * HARDWARE CONNECTIONS
  - GPIO 16 ---> VGA Hsync
  - GPIO 17 ---> VGA Vsync
  - GPIO 18 ---> VGA Green lo-bit --> 470 ohm resistor --> VGA_Green
  - GPIO 19 ---> VGA Green hi_bit --> 330 ohm resistor --> VGA_Green
  - GPIO 20 ---> 330 ohm resistor ---> VGA-Blue
  - GPIO 21 ---> 330 ohm resistor ---> VGA-Red
  - RP2350 GND ---> VGA-GND

  Rotary encoder
  GPIO 12 green left side.  A
  GPIO 11 yellow right side  B
  GPIO 10 push button (active high)

  MCP4822 DAC (spi1)
  GPIO 13 ---> CS
  GPIO 14 ---> SCK
  GPIO 15 ---> MOSI (SDI)

  GPIO 25 on-board LED: lit when a frame misses the 60 fps deadline
 *
 * RESOURCES USED
 *  - PIO state machines 0, 1, and 2 on PIO instance 0
 *  - DMA channels (VGA, plus 2 for the peg sound) and one DMA pacing timer
 *  - 2 x 153.6 kBytes of RAM (double-buffered pixel data)
 *
 * OPTIMIZATION LOG -- max balls at 60 fps (each step tagged [OPT n] in the code)
 *   OPT 1  O(1) nearest-peg lookup ........ 136 peg tests/substep -> 1   (enabled multi-ball)
 *   OPT 2  Split balls across both cores .. ~2x compute                  (not measured alone)
 *   OPT 3  Precomputed ball sprite ........ 150 MHz:  5,000 balls
 *   OPT 4  Cheaper collision math ......... 150 MHz:  5,200 balls
 *   OPT 5  Parallel clear + auto split .... shipped with OPT 6           (not measured alone)
 *   OPT 6  Overclock 300 -> 350 MHz ....... 300 MHz: 3,150 us spare at 10k; 350 MHz: 13,000 (0 us spare)
 *   OPT 7  Ball struct 24 -> 12 bytes ..... RAM ceiling 8k -> 10.3k -> 12.9k -> ~17k
 *   OPT 8  Hot code in SRAM ............... 350 MHz: 16,000 balls with ~600 us spare
 */

// Include the VGA grahics library
#include "VGA/vga16_graphics_v3.h"
// Include standard libraries
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
// Include Pico libraries
#include "pico/stdlib.h"
#include "pico/divider.h"
#include "pico/multicore.h"
#include "pico/sync.h"
// Include hardware libraries
#include "hardware/pio.h"
#include "hardware/dma.h"
#include "hardware/clocks.h"
#include "hardware/pll.h"
#include "hardware/spi.h"
#include "hardware/vreg.h"
// Include protothreads
#include "pt_cornell_rp2040_v1_4.h"

// === the fixed point macros ========================================
typedef signed int fix15 ;
#define multfix15(a,b) ((fix15)((((signed long long)(a))*((signed long long)(b)))>>15))
#define float2fix15(a) ((fix15)((a)*32768.0f)) // [OPT 3] float, not double: the M33 FPU is single-precision only
#define fix2float15(a) ((float)(a)/32768.0f)
#define absfix15(a) abs(a)
#define int2fix15(a) ((fix15)(a << 15))
#define fix2int15(a) ((int)(a >> 15))
#define char2fix15(a) (fix15)(((fix15)(a)) << 15)
#define divfix(a,b) (fix15)(div_s64s64( (((signed long long)(a)) << 15), ((signed long long)(b))))

// unused (left over from the original demo; frame timing comes from the VGA driver)
#define FRAME_RATE 33000

// =====================================================================
// === ROTARY ENCODER INTERFACE ========================================
// =====================================================================
#define ROT_A  12
#define ROT_B  11
#define ROT_SW 10   // push button: reads HIGH while pressed

// Knob modes; the push button steps BALLS -> BOUNCE -> GRAVITY -> BALLS
#define ROT_MODE_BALLS   0
#define ROT_MODE_BOUNCE  1
#define ROT_MODE_GRAVITY 2
#define ROT_NUM_MODES    3
volatile int rot_mode = ROT_MODE_BALLS ;

#define MIN_BALLS  1
#define MAX_BALLS  16000   // [OPT 8] measured limit: ~600 us spare at 350 MHz (RAM would allow ~17k)
#define INIT_BALLS 100
#define BALL_STEP  100
volatile int rot_counter = INIT_BALLS ;   // = number of balls to animate

// Knob parameters are kept in hundredths for the knob/display, mirrored as fix15 for the physics
#define MIN_BOUNCE  0
#define MAX_BOUNCE  100
#define INIT_BOUNCE 30
#define BOUNCE_STEP 5
volatile int   bounce_pct = INIT_BOUNCE ;
volatile fix15 bounciness = (INIT_BOUNCE << 15) / 100 ;

// Gravity (px/frame^2). Capped at 1.00 so a full-height fall (~29 px/frame)
// stays inside ball_t's +/-32 px/frame velocity range [OPT 7]
#define MIN_GRAV  5
#define MAX_GRAV  100
#define INIT_GRAV 37
#define GRAV_STEP 5
volatile int   grav_pct = INIT_GRAV ;
volatile fix15 gravity  = (INIT_GRAV << 15) / 100 ;

// Set when a knob click changes a parameter; core 0 then clears the histogram
// and the fallen count at the start of the next frame
volatile int stats_reset = 0 ;

static volatile uint8_t rot_prev_state = 3 ; // (A<<1)|B ; 3 = rest (both high)
static volatile int8_t  rot_accum = 0 ;      // steps taken since last rest

// Gray-code step table, index = (prev<<2)|curr: +1 CW, -1 CCW, 0 = no step or bounce
static const int8_t rot_table[16] = {
/* prev=0(00) */  0, -1, +1,  0,
/* prev=1(01) */ +1,  0,  0, -1,
/* prev=2(10) */ -1,  0,  0, +1,
/* prev=3(11) */  0, +1, -1,  0
} ;

// One knob detent: adjust the current mode's value (clamped); request a
// stats reset only if the value actually changed
static void rot_click(int dir)
{
  int changed ;
  if (rot_mode == ROT_MODE_BALLS) {
    int v = MIN(MAX(rot_counter + dir * BALL_STEP, MIN_BALLS), MAX_BALLS) ;
    changed = (v != rot_counter) ;
    rot_counter = v ;
  } else if (rot_mode == ROT_MODE_BOUNCE) {
    int v = MIN(MAX(bounce_pct + dir * BOUNCE_STEP, MIN_BOUNCE), MAX_BOUNCE) ;
    changed = (v != bounce_pct) ;
    bounce_pct = v ;
    bounciness = (v << 15) / 100 ;
  } else {
    int v = MIN(MAX(grav_pct + dir * GRAV_STEP, MIN_GRAV), MAX_GRAV) ;
    changed = (v != grav_pct) ;
    grav_pct = v ;
    gravity  = (v << 15) / 100 ;
  }
  if (changed) stats_reset = 1 ;
}

// Push button, polled once per frame (slower than contact bounce, so no debounce).
// RP2350 erratum E9: the input buffer is enabled only while sampling, or the
// pulled-down pin can latch high after release.
static void pollButton(void)
{
  static int sw_prev = 0 ;
  gpio_set_input_enabled(ROT_SW, true) ;
  busy_wait_us(1) ;                    // let the input synchronizer settle
  int sw = gpio_get(ROT_SW) ;
  gpio_set_input_enabled(ROT_SW, false) ;
  if (sw && !sw_prev) {
    rot_mode = (rot_mode + 1) % ROT_NUM_MODES ;   // BALLS -> BOUNCE -> GRAVITY -> BALLS
    rot_accum = 0 ;                    // don't carry a partial turn into the new mode
  }
  sw_prev = sw ;
}

// Fires on every edge of A or B. A click counts only after 4 steps back at
// rest, so contact bounce (+1 then -1) cancels out.
void rot_ISR(uint gpio, uint32_t events)
{
  uint8_t curr_state = (gpio_get(ROT_A) << 1) | gpio_get(ROT_B) ;
  rot_accum += rot_table[(rot_prev_state << 2) | curr_state] ;
  rot_prev_state = curr_state ;

  if (curr_state == 3) {               // landed back at rest (a full click, or none)
    if      (rot_accum >=  4) rot_click(+1) ;  // CW
    else if (rot_accum <= -4) rot_click(-1) ;  // CCW
    rot_accum = 0 ;                    // discard partial turns / bounce
  }
}

// =====================================================================
// === GALTON BOARD ====================================================
// =====================================================================
// gravity and bounciness (set by the knob) are defined with the rotary encoder above
#define BALL_RADIUS  4   // max 4: drawSpan() writes at most 4 bytes per span [OPT 8]
#define PEG_RADIUS   6
#define PEG_VERT_SEP 19
#define PEG_HORZ_SEP 38
#define SCREEN_W     640
#define SCREEN_H     480
// collision distances in fix15 (center-to-center)
#define COLLIDE_DIST  int2fix15(BALL_RADIUS + PEG_RADIUS)
#define TELEPORT_DIST int2fix15(BALL_RADIUS + PEG_RADIUS + 1)
// [OPT 4] squared collision distance, so the contact test needs no sqrt
#define COLLIDE_DIST2 int2fix15((BALL_RADIUS + PEG_RADIUS) * (BALL_RADIUS + PEG_RADIUS))

// Board layout: row r (0..15) has r+1 pegs, centered on BOARD_TOP_X.
// Bottom row sits at BOARD_TOP_Y + 15*19 = 385, leaving room for the histogram.
#define NUM_ROWS     16
#define NUM_PEGS     (NUM_ROWS * (NUM_ROWS + 1) / 2)   // 136
#define BOARD_TOP_X  (SCREEN_W / 2)
#define BOARD_TOP_Y  100

// Peg centers, indexed row by row: peg = row*(row+1)/2 + col
fix15 peg_x[NUM_PEGS] ;
fix15 peg_y[NUM_PEGS] ;

// Fill in the peg table once at startup
void initPegs()
{
  int peg = 0 ;
  for (int row = 0; row < NUM_ROWS; row++) {
    for (int col = 0; col <= row; col++) {
      // leftmost peg of each row is half a row-width left of center
      peg_x[peg] = int2fix15(BOARD_TOP_X - row * (PEG_HORZ_SEP / 2) + col * PEG_HORZ_SEP) ;
      peg_y[peg] = int2fix15(BOARD_TOP_Y + row * PEG_VERT_SEP) ;
      peg++ ;
    }
  }
}

// =====================================================================
// [OPT 1] O(1) NEAREST-PEG LOOKUP
//   Bottleneck : every ball tested all 136 pegs on every substep.
//   Approach   : rows are 19 px apart and contact needs < 10 px, so only the
//                nearest peg can touch the ball. Compute its row and column
//                directly from (x, y) with two divisions.
//   Effect     : collision search drops from 136 tests to 1 per substep;
//                the step that made a multi-ball board possible.
//   Expected / measured : ~100x less collision work; not measured alone
//                (it predates the multi-ball code).
// =====================================================================
// Returns the index of the peg nearest (x, y), or -1 if none is in range.
int __not_in_flash_func(nearestPeg)(fix15 x, fix15 y)
{
  int yi = fix2int15(y) - BOARD_TOP_Y + (PEG_VERT_SEP / 2) ;
  if (yi < 0) return -1 ;                  // above the board
  int row = yi / PEG_VERT_SEP ;
  if (row >= NUM_ROWS) return -1 ;         // below the board

  int xi = fix2int15(x) - (BOARD_TOP_X - row * (PEG_HORZ_SEP / 2)) + (PEG_HORZ_SEP / 2) ;
  if (xi < 0) return -1 ;                  // left of this row
  int col = xi / PEG_HORZ_SEP ;
  if (col > row) return -1 ;               // right of this row

  return row * (row + 1) / 2 + col ;
}

// =====================================================================
// [OPT 7] BALL STRUCT 24 -> 12 BYTES
//   Bottleneck : RAM. The two VGA frame buffers take 307 KB of the 512 KB
//                SRAM; at 24 bytes/ball the linker overflowed above ~8,000.
//   Approach   : shrink each ball without losing physics accuracy.
//                24 B -> 20 B: narrow last_peg / binned.
//                20 B -> 16 B: pack the flags into spare bits of vx.
//                16 B -> 12 B (below): position keeps full fix15 in bits
//                31..5 (+/-2048 px; balls reach ~1300 px at bounciness 1),
//                the 9 flag bits ("meta" = (last_peg+1)<<1 | binned) live in
//                the 5 low bits of xm and ym, and velocity is fix10
//                (1/1024 px/frame, +/-32 px/frame; max seen ~17).
//   Validation : an earlier fix8 velocity broke the histogram (only 128
//                distinct paths; ~1/128 balls stuck on the top peg). This
//                layout was checked in a PC simulation of this exact physics
//                (20k drops at bounciness 0.3/0.5/0.6/1.0): 0 stuck balls and
//                the same histogram as full fix15, given the two spawnBall()
//                changes (odd vx, sub-pixel drop jitter).
//   Expected / measured : RAM ceiling 8k (24 B) -> 10.3k (20 B) ->
//                12.9k (16 B) -> ~17k (12 B). Measured: 10,300 balls (20 B),
//                12,500 (16 B); at 12 B the CPU became the limit again.
// =====================================================================
typedef struct {
  int32_t xm, ym ;
  int16_t vx, vy ;
} ball_t ;
_Static_assert(sizeof(ball_t) == 12, "ball_t grew -- MAX_BALLS may no longer fit in RAM") ;

#define BALL_POS(m)            ((fix15)((m) >> 5))      // arithmetic shift: exact
#define BALL_META(b)           (((b)->xm & 31) | (((b)->ym & 31) << 5))
#define META_LAST_PEG(m)       (((m) >> 1) - 1)
#define META_BINNED(m)         ((m) & 1)
#define MAKE_META(peg, binned) ((((peg) + 1) << 1) | (binned))
#define POS_LIMIT              int2fix15(2047)
#define vel2fix15(v)           ((fix15)(v) * 32)        // fix10 -> fix15, exact

// [OPT 7] fix15 -> fix10: round to nearest (a plain >> biases balls left/up), saturate to int16
static inline int16_t fix2vel(fix15 a)
{
  a = (a + 16) >> 5 ;
  return (int16_t)MIN(MAX(a, -32767), 32767) ;
}

// [OPT 7] Pack a ball; positions clamped to +/-2047 px so the << 5 can't overflow
static inline void ballStore(ball_t* b, fix15 x, fix15 y, fix15 vx, fix15 vy, int meta)
{
  x = MIN(MAX(x, -POS_LIMIT), POS_LIMIT) ;
  y = MIN(MAX(y, -POS_LIMIT), POS_LIMIT) ;
  b->xm = (int32_t)((uint32_t)x << 5) | (meta & 31) ;
  b->ym = (int32_t)((uint32_t)y << 5) | (meta >> 5) ;
  b->vx = fix2vel(vx) ;
  b->vy = fix2vel(vy) ;
}

ball_t balls[MAX_BALLS] ;
int num_balls = 0 ;     // balls currently animated: balls[0 .. num_balls-1]

// === HISTOGRAM ===
// 16 rows -> 17 landing spots: the 15 gaps between bottom-row pegs, plus one
// past each end. Bin k is centered PEG_HORZ_SEP*k right of BIN0_CENTER_X.
#define NUM_BINS       (NUM_ROWS + 1)
#define BOTTOM_ROW_Y   (BOARD_TOP_Y + (NUM_ROWS - 1) * PEG_VERT_SEP)          // 385
#define BOTTOM_LEFT_X  (BOARD_TOP_X - (NUM_ROWS - 1) * (PEG_HORZ_SEP / 2))    // 35
#define BIN0_CENTER_X  (BOTTOM_LEFT_X - PEG_HORZ_SEP / 2)
// A ball is counted once its top edge clears the bottom row of pegs
#define BIN_LINE_Y     int2fix15(BOTTOM_ROW_Y + PEG_RADIUS + BALL_RADIUS)
// Bars fill the space under the board; the tallest bar is always HIST_H tall
#define HIST_TOP       (BOTTOM_ROW_Y + 15)
#define HIST_BOTTOM    (SCREEN_H - 2)   // fillRect won't draw row 479
#define HIST_H         (HIST_BOTTOM - HIST_TOP + 1)
#define BAR_W          (PEG_HORZ_SEP - 4)

// [OPT 2] One row of counters per core (++ isn't atomic across cores);
// write [get_core_num()], sum both rows to read
int bins_core[2][NUM_BINS] ;
int fallen_core[2] ;

// Drop a ball just above the top peg with a small random vx.
// [OPT 7] vx is forced odd (never 0, which would balance on the top peg
// forever) and x gets +/-0.5 px jitter, keeping enough distinct paths at fix10.
void spawnBall(ball_t* b)
{
  fix15 x  = int2fix15(SCREEN_W / 2) + (fix15)((rand() & 0x7FFF) - 0x4000) ;  // 0x4000 = 0.5 px
  fix15 vx = vel2fix15(((rand() & 0x1FF) - 0x100) | 1) ;                       // 0x100 = 0.25 at fix10
  ballStore(b, x, int2fix15(BOARD_TOP_Y - 50), vx, 0, MAKE_META(-1, 0)) ;      // no peg yet, not binned
}

// Count a ball in the bin it passed through (the caller marks it binned)
void __not_in_flash_func(binBall)(fix15 x)
{
  int xi = fix2int15(x) - BOTTOM_LEFT_X ;          // relative to leftmost bottom peg
  int bin = (xi < 0) ? 0 : (xi / PEG_HORZ_SEP) + 1 ;  // left of it = bin 0
  if (bin > NUM_BINS - 1) bin = NUM_BINS - 1 ;        // right of rightmost peg
  int core = get_core_num() ;                         // [OPT 2] this core's own counters
  bins_core[core][bin]++ ;
  fallen_core[core]++ ;
}

// Draw the histogram under the board, scaled so the fullest bin is HIST_H tall
void drawHistogram()
{
  int bins[NUM_BINS] ;                 // [OPT 2] sum of both cores' counts
  int max_count = 0 ;
  for (int k = 0; k < NUM_BINS; k++) {
    bins[k] = bins_core[0][k] + bins_core[1][k] ;
    if (bins[k] > max_count) max_count = bins[k] ;
  }
  if (max_count == 0) return ;   // nothing to draw yet

  for (int k = 0; k < NUM_BINS; k++) {
    int h = bins[k] * HIST_H / max_count ;
    if (h == 0) continue ;
    // bar centered on its gap, clipped to the screen at the two outer bins
    int left  = BIN0_CENTER_X + k * PEG_HORZ_SEP - BAR_W / 2 ;
    int right = left + BAR_W ;
    if (left < 0) left = 0 ;
    if (right > SCREEN_W) right = SCREEN_W ;
    fillRect(left, HIST_BOTTOM - h + 1, right - left, h, GREEN) ;
  }
}

// =====================================================================
// === DMA  ============================================================
// =====================================================================
// Peg sound: a precomputed table streamed to the DAC by two chained DMA
// channels, so the CPU does no audio work at all.
#define PIN_CS   13
#define PIN_SCK  14
#define PIN_MOSI 15
#define SPI_PORT spi1
// A-channel, 1x gain, active
#define DAC_config_chan_A 0b0011000000000000

#define SOUND_FS       50000    // DAC sample rate (Hz)
#define PEG_SOUND_FREQ 800.0f   // pitch of the "thunk" (Hz)
#define PEG_SOUND_LEN  500      // 500 samples / 50 kHz = 10 ms (short, so more hits get their own sound)
#define PEG_ATTACK     50       // samples to ramp up (avoids a click at the start)

// Precomputed sound, each sample already has the DAC config bits OR'd in
static uint16_t peg_sound[PEG_SOUND_LEN] ;
static uint16_t * peg_sound_addr = &peg_sound[0] ;
static int snd_data_chan ;
static int snd_ctrl_chan ;

// Set up SPI, build the sound table, and configure the DMA
void initPegSound()
{
  // SPI at 20 MHz, 16-bit transfers; CS driven by the SPI hardware
  spi_init(SPI_PORT, 20000000) ;
  spi_set_format(SPI_PORT, 16, 0, 0, 0) ;
  gpio_set_function(PIN_CS,   GPIO_FUNC_SPI) ;
  gpio_set_function(PIN_SCK,  GPIO_FUNC_SPI) ;
  gpio_set_function(PIN_MOSI, GPIO_FUNC_SPI) ;

  // Sine with a short linear attack and a linear decay, centered on mid-scale
  for (int i = 0; i < PEG_SOUND_LEN; i++) {
    float env = (i < PEG_ATTACK) ? (float)i / PEG_ATTACK
                                 : (float)(PEG_SOUND_LEN - i) / (PEG_SOUND_LEN - PEG_ATTACK) ;
    int sample = (int)(2047.0f * env * sinf(6.2832f * PEG_SOUND_FREQ * i / SOUND_FS)) + 2048 ;
    peg_sound[i] = DAC_config_chan_A | (sample & 0x0fff) ;
  }

  // Park the DAC at mid-scale now, so the first sound doesn't start with a pop
  uint16_t mid = DAC_config_chan_A | 2048 ;
  spi_write16_blocking(SPI_PORT, &mid, 1) ;

  snd_data_chan = dma_claim_unused_channel(true) ;
  snd_ctrl_chan = dma_claim_unused_channel(true) ;

  // Control channel: rewinds the data channel to the start of the table, then chains to it
  dma_channel_config c = dma_channel_get_default_config(snd_ctrl_chan) ;
  channel_config_set_transfer_data_size(&c, DMA_SIZE_32) ;
  channel_config_set_read_increment(&c, false) ;
  channel_config_set_write_increment(&c, false) ;
  channel_config_set_chain_to(&c, snd_data_chan) ;
  dma_channel_configure(
    snd_ctrl_chan,
    &c,
    &dma_hw->ch[snd_data_chan].read_addr,   // write: data channel's read address
    &peg_sound_addr,                        // read: POINTER to the sound's address
    1,                                      // one transfer
    false) ;                                // don't start

  // Pacing timer = sys_clk / SOUND_FS; read at runtime, so it follows the overclock [OPT 6]
  int snd_timer = dma_claim_unused_timer(true) ;
  dma_timer_set_fraction(snd_timer, 1, (uint16_t)(clock_get_hz(clk_sys) / SOUND_FS)) ;

  // Data channel: table -> SPI data register, one sample per timer tick
  dma_channel_config c2 = dma_channel_get_default_config(snd_data_chan) ;
  channel_config_set_transfer_data_size(&c2, DMA_SIZE_16) ;
  channel_config_set_read_increment(&c2, true) ;
  channel_config_set_write_increment(&c2, false) ;
  channel_config_set_dreq(&c2, dma_get_timer_dreq(snd_timer)) ;
  dma_channel_configure(
    snd_data_chan, &c2,
    &spi_get_hw(SPI_PORT)->dr,              // write: SPI data register
    peg_sound,                              // read: start of the sound
    PEG_SOUND_LEN,                          // transfers per trigger (reloaded on each trigger)
    false) ;                                // don't start
}

// Start the peg sound; if one is already playing, drop this one (never blocks)
void __not_in_flash_func(playPegSound)()
{
  if (dma_channel_is_busy(snd_data_chan) || dma_channel_is_busy(snd_ctrl_chan)) return ;
  dma_start_channel_mask(1u << snd_ctrl_chan) ;
}

// =====================================================================
// [OPT 4] CHEAPER COLLISION MATH (in updateBall below)
//   Bottleneck : each contact test paid a sqrt, each collision two 64-bit
//                software divides (divfix), every substep re-divided v by
//                the step count, and balls below the board still ran the
//                full substep + peg search.
//   Approach   : (a) compare SQUARED distance against COLLIDE_DIST2, so
//                near-misses never take a sqrt; (b) one hardware-FPU
//                1/sqrtf() per real collision, multiplied into dx and dy;
//                (c) compute step_vx/step_vy once per frame; (d) fast path:
//                below BIN_LINE_Y there are no pegs, so just x += vx.
//   Effect     : (d) alone skips the peg search for about half the balls.
//   Expected / measured : modest gain on top of OPT 3;
//                5,000 -> 5,200 balls at 150 MHz (+4%).
// =====================================================================
// One frame of ball physics. Peg collision: dv = -2 (n.v) n, where n is the
// unit normal from peg to ball (a peg is an infinite-mass ball at rest).
void __not_in_flash_func(updateBall)(ball_t* b)
{
  // [OPT 7] Unpack the 12-byte ball into locals; packed back at the end
  fix15 x       = BALL_POS(b->xm) ;
  fix15 y       = BALL_POS(b->ym) ;
  fix15 vx      = vel2fix15(b->vx) ;
  fix15 vy      = vel2fix15(b->vy) ;
  int meta      = BALL_META(b) ;
  int last_peg  = META_LAST_PEG(meta) ;
  int binned    = META_BINNED(meta) ;

  // [OPT 4d] Below the board: no pegs left to hit, skip substeps and peg search
  if (y > BIN_LINE_Y) {
    x = x + vx ;
    y = y + vy ;
  } else {
    // Substeps of at most ~4 px, so a fast ball can't skip past or sink into a peg
    int speed = fix2int15(MAX(absfix15(vx), absfix15(vy))) ;
    int steps = (speed >> 2) + 1 ;
    fix15 step_vx = vx / steps ;   // [OPT 4c] divide once, not every substep
    fix15 step_vy = vy / steps ;

    for (int s = 0; s < steps; s++) {
      // Move one substep
      x = x + step_vx ;
      y = y + step_vy ;

      // [OPT 1] Only the nearest peg can be in contact
      int peg = nearestPeg(x, y) ;
      if (peg < 0) continue ;
      fix15 dx = x - peg_x[peg] ;
      fix15 dy = y - peg_y[peg] ;

      // Bounding box first, then [OPT 4a] squared distance: no sqrt for near-misses
      if ((absfix15(dx) < COLLIDE_DIST) && (absfix15(dy) < COLLIDE_DIST)) {
        fix15 dist2 = multfix15(dx,dx) + multfix15(dy,dy) ;

        // dist2 > 0 guards the divide if the ball lands exactly on the peg center
        if ((dist2 < COLLIDE_DIST2) && (dist2 > 0)) {
          // [OPT 4b] Unit normal via one FPU 1/sqrt (was two software divfix); dx*inv is already fix15
          float inv_dist = 1.0f / sqrtf(fix2float15(dist2)) ;
          fix15 normal_x = (fix15)(dx * inv_dist) ;
          fix15 normal_y = (fix15)(dy * inv_dist) ;

          // Velocity component along the normal: < 0 means moving INTO the peg
          fix15 v_dot_n = multfix15(normal_x, vx) + multfix15(normal_y, vy) ;

          // Teleport just outside contact range, so the next substep can't re-collide
          x = peg_x[peg] + multfix15(normal_x, TELEPORT_DIST) ;
          y = peg_y[peg] + multfix15(normal_y, TELEPORT_DIST) ;

          // Reflect only if approaching (reflecting a receding ball throws it back in)
          if (v_dot_n < 0) {
            fix15 intermediate_term = multfix15(int2fix15(-2), v_dot_n) ;
            vx = vx + multfix15(normal_x, intermediate_term) ;
            vy = vy + multfix15(normal_y, intermediate_term) ;

            // Damping and sound only on a new peg, not while rolling on the same one
            if (peg != last_peg) {
              playPegSound() ;
              vx = multfix15(bounciness, vx) ;
              vy = multfix15(bounciness, vy) ;
              last_peg = peg ;
            }
          }
        }
      }
    }
  }

  // Count it as it leaves the board (it still drifts sideways below)
  if (!binned && (y > BIN_LINE_Y)) {
    binBall(x) ;
    binned = 1 ;
  }

  // Re-spawn any ball that falls thru the bottom of the SCREEN
  if (y > int2fix15(SCREEN_H)) {
    spawnBall(b) ;
    return ;
  }

  // Apply gravity, then [OPT 7] pack the ball back
  ballStore(b, x, y, vx, vy + gravity, MAKE_META(last_peg, binned)) ;
}

// Ball color (set from the serial thread)
char color = CYAN ;

// =====================================================================
// [OPT 2] SPLIT THE BALLS ACROSS BOTH CORES
//   Bottleneck : core 0 did all the physics and drawing while core 1 sat idle.
//   Approach   : split by index -- core 0 owns balls [0, split), core 1 owns
//                [split, num_balls) -- and each core updates AND draws its own
//                balls (updateAndDrawBall), so there's no lock and no sync
//                inside the frame. Per-core histogram counters remove the only
//                shared write. Semaphores form a fork/join each frame, and
//                core 1 also draws the pegs. Core0/Core1/Spare are shown on
//                screen to find the limit.
//   Effect     : roughly doubles the compute available per frame.
//   Expected / measured : ~2x; not measured alone (first recorded limit was
//                5,000 balls after OPT 3).
// =====================================================================
semaphore_t draw_semaphore ;   // core 0 -> core 1: "new frame, start clearing your half"

// =====================================================================
// [OPT 5] PARALLEL CLEAR + AUTOMATIC SPLIT BALANCE
//   Bottleneck : core 0 cleared the whole 153.6 KB buffer and drew the
//                histogram while core 1 idled (and that time was hidden from
//                core1_us); a fixed 60/40 split is wrong as balls move
//                between the peg area (substeps) and the free-fall area.
//   Approach   : core 0 clears rows 0-239 while core 1 clears rows 240-479 and
//                draws the histogram (entirely in the bottom half), then a
//                two-way barrier (top/bot semaphores) so nobody draws onto an
//                uncleared half. split_pm (per-mille) moves 0.1% of the balls
//                per frame toward whichever core finished first last frame,
//                with a 50 us deadband against noise.
//   Effect     : clear time halved; both cores finish together, and Spare is
//                now an honest margin.
//   Expected / measured : a few hundred us per frame plus better balance;
//                shipped together with OPT 6, not measured alone.
// =====================================================================
semaphore_t top_semaphore ;    // core 0 -> core 1: "top half clear, num_balls/split final"
semaphore_t bot_semaphore ;    // core 1 -> core 0: "bottom half clear, histogram drawn"
semaphore_t done_semaphore ;   // [OPT 2] core 1 -> core 0: "my share is drawn" (don't clear under me)

#define CLEAR_SPLIT_Y 240      // core 0 clears rows [0, 240), core 1 clears [240, 480)

#define SPLIT_PM_INIT  600     // starting guess: core 0 takes 60% of the balls
#define SPLIT_DEADBAND 50      // us: don't chase differences smaller than this
int split_pm = SPLIT_PM_INIT ; // only touched by core 0
volatile int split = 0 ;

// [OPT 2] per-core work time last frame (us); both start at vsync, so they compare finish times
volatile uint32_t core0_us = 0 ;
volatile uint32_t core1_us = 0 ;
#define FRAME_BUDGET_US 16667   // DOUBLE_BUFFER_60 -> 60 fps

// === MISSED-DEADLINE LED ===
// The VGA DMA sets start_flag at every vsync (buffer swap). If it is set again
// before both cores finish, the frame was swapped in half-drawn: deadline missed.
extern int start_flag ;                 // defined in vga16_graphics_v3.c
#define LED_PIN         PICO_DEFAULT_LED_PIN   // GPIO 25 on the Pico 2
#define LED_HOLD_FRAMES 30      // keep the LED lit ~0.5 s after a miss, so even a single missed frame is visible
static int led_hold = 0 ;       // frames left to keep the LED on (core 0 only)
static int missed_frames = 0 ;  // missed deadlines since boot (core 0 only)

// =====================================================================
// [OPT 3] PRECOMPUTED BALL SPRITE
//   Bottleneck : the library circle call redid the same shape for every ball
//                every frame (fillCircle: 5 software sqrts + 10 drawHLine
//                calls, each with range checks and a tiny memset).
//   Approach   : the radius never changes, so compute each row's half-width
//                once (initBallSprite) and write whole bytes (2 px each)
//                straight into the frame buffer. Balls touching the screen
//                edge fall back to the library call, which clips. Also: float
//                literals instead of double in the fix15 macros (M33 FPU is
//                single-precision only).
//   Effect     : the biggest drawing speedup.
//   Expected / measured : 5,000 balls at 150 MHz (with OPT 1 and 2).
//   Balls are now drawn hollow: the sprite is a ring (disk r minus disk r-1),
//   drawn as two spans per row.
// =====================================================================
extern char * current_draw_buffer ;     // defined in vga16_graphics_v3.c
int32_t sqrt_i32(int32_t v) ;           // defined in vga16_graphics_v3.c
static int ball_dx[BALL_RADIUS + 1] ;   // outer half-width of row i above/below center
static int ball_hx[BALL_RADIUS + 1] ;   // hole half-width of row i (0 = solid row)

// Ring half-widths (same formula as fillCircle); every row at least 1 px thick
void initBallSprite(void)
{
  int r2 = BALL_RADIUS * BALL_RADIUS + BALL_RADIUS ;
  int h  = BALL_RADIUS - 1 ;
  int h2 = h * h + h ;
  for (int i = 0; i <= BALL_RADIUS; i++) {
    ball_dx[i] = sqrt_i32(r2 - i * i) ;
    ball_hx[i] = (i <= h) ? sqrt_i32(h2 - i * i) : 0 ;
    // keep every row's outline at least 1 px thick
    if (ball_hx[i] >= ball_dx[i]) ball_hx[i] = ball_dx[i] - 1 ;
  }
}

// Fill pixels [x, x+w) of one 640-px row (2 px/byte: even x = low nibble)
static inline void drawSpan(unsigned char* row, int x, int w, unsigned char c)
{
  if (x & 1) {                                   // lone pixel at the left
    row[x >> 1] = (row[x >> 1] & 0x0F) | (c << 4) ;
    x++ ; w-- ;
  }
  unsigned char* p = row + (x >> 1) ;
  unsigned char both = c | (c << 4) ;
  // [OPT 8] Whole bytes written out (a span is at most 4 bytes): GCC turned a
  // byte loop into memset() calls -- slow for 1-4 bytes, and memset is in flash
  int n = w >> 1 ;
  if (n > 0) p[0] = both ;
  if (n > 1) p[1] = both ;
  if (n > 2) p[2] = both ;
  if (n > 3) p[3] = both ;
  p += n ;
  if (w & 1) *p = (*p & 0xF0) | c ;              // lone pixel at the right
}

// One row of the ring: the two sides, or the whole span where there's no hole
static inline void drawRingRow(unsigned char* row, int x0, int dx, int hx, unsigned char c)
{
  if (hx <= 0) {
    drawSpan(row, x0 - dx, 2 * dx, c) ;
  } else {
    drawSpan(row, x0 - dx, dx - hx, c) ;   // left side
    drawSpan(row, x0 + hx, dx - hx, c) ;   // right side
  }
}

// [OPT 3] Draw one hollow ball from the precomputed sprite
static inline void drawBall(int x0, int y0, char c)
{
  // Fast path only when the whole ball is on screen; drawCircle() clips the rest
  if ((x0 - BALL_RADIUS < 0) || (x0 + BALL_RADIUS > 639) ||
      (y0 - BALL_RADIUS < 0) || (y0 + BALL_RADIUS > 479)) {
    drawCircle(x0, y0, BALL_RADIUS, c) ;
    return ;
  }
  unsigned char* center = (unsigned char*)current_draw_buffer + 320 * y0 ;
  drawRingRow(center, x0, ball_dx[0], ball_hx[0], c) ;
  for (int i = 1; i <= BALL_RADIUS; i++) {
    drawRingRow(center + 320 * i, x0, ball_dx[i], ball_hx[i], c) ;   // row below center
    drawRingRow(center - 320 * i, x0, ball_dx[i], ball_hx[i], c) ;   // row above center
  }
}

// [OPT 2] Physics + draw for one ball, back to back, so the cores never sync mid-frame
static inline void updateAndDrawBall(ball_t* b)
{
  updateBall(b) ;
  drawBall(fix2int15(BALL_POS(b->xm)), fix2int15(BALL_POS(b->ym)), color) ;
}

// =====================================================================
// [OPT 8] HOT CODE IN SRAM
//   Bottleneck : at 13,000 balls Spare was 0. All code ran from flash
//                through ONE 16 KB XIP cache shared by both cores, so the
//                cores stalled on each other's misses; the disassembly also
//                showed 10 memset() calls per ball jumping back to flash.
//   Approach   : run the per-ball path from SRAM. updateAndDrawRange() is
//                __no_inline_not_in_flash_func (no_inline is required: with
//                plain __not_in_flash_func, -Ofast inlined it back into the
//                flash-resident protothreads) and both cores call it, so the
//                inline draw helpers land in SRAM with it. updateBall,
//                nearestPeg, binBall and playPegSound are __not_in_flash_func.
//                drawSpan's loop was replaced by direct stores.
//   Effect     : the per-ball path makes no flash calls except drawCircle
//                (edge balls only) and rand() (respawns). Costs ~2 KB of RAM.
//   Expected / measured : expected +5-20%; measured 13,000 balls at 0 us
//                spare -> 16,000 balls with ~600 us spare (about +25%).
// =====================================================================
void __no_inline_not_in_flash_func(updateAndDrawRange)(int from, int to)
{
  for (int i = from; i < to; i++) updateAndDrawBall(&balls[i]) ;
}

// ==================================================
// === users serial input thread
// ==================================================
// Reads a color (1-15) from the serial port and applies it to the balls
static PT_THREAD (protothread_serial(struct pt *pt))
{
    PT_BEGIN(pt);
    // stores user input
    static int user_input ;
    // wait for 0.1 sec
    PT_YIELD_usec(1000000) ;
    // announce the threader version
    sprintf(pt_serial_out_buffer, "Protothreads RP2040 v1.4\n\r");
    // non-blocking write
    serial_write ;
      while(1) {
        // print prompt
        sprintf(pt_serial_out_buffer, "input a number in the range 1-15: ");
        // non-blocking write
        serial_write ;
        // spawn a thread to do the non-blocking serial read
        serial_read ;
        // convert input string to number
        sscanf(pt_serial_in_buffer,"%d", &user_input) ;
        // update ball color
        if ((user_input > 0) && (user_input < 16)) {
          color = (char)user_input ;
        }
      } // END WHILE(1)
  PT_END(pt);
} // timer thread

// Animation on core 0: frame control, knob handling, its share of the balls, text
static PT_THREAD (protothread_anim(struct pt *pt))
{
    // Mark beginning of thread
    PT_BEGIN(pt);

    // Build the peg table and the ball sprite (balls are added in the loop)
    initPegs() ;
    initBallSprite() ;

    static char text_str[40] ;

    while(1) {
      // Wait for vsync (the DMA has just swapped buffers)
      PT_YIELD_UNTIL(pt, draw_start_signal()) ;
      // [OPT 2] time core 0's share of the frame
      static uint32_t t0 ;
      t0 = time_us_32() ;

      // A knob click changed a parameter: reset the histogram and fallen count.
      // Safe here: core 1 hasn't been woken yet, so nothing is reading or counting.
      if (stats_reset) {
        stats_reset = 0 ;
        memset(bins_core,   0, sizeof(bins_core)) ;
        memset(fallen_core, 0, sizeof(fallen_core)) ;
      }

      // [OPT 5] Wake core 1 now, so both cores clear their half in parallel
      PT_SEM_SDK_SIGNAL(pt, &draw_semaphore) ;
      clearRegion(0, CLEAR_SPLIT_Y, BLACK) ;

      // Knob bookkeeping, before core 1 is released to draw (it then sees the
      // final num_balls/split and never touches a ball being re-spawned)
      pollButton() ;                 // push button: next knob mode on press
      int target = rot_counter ;     // read the ISR's value once
      // Adding balls: all new ones spawn at the same spot above the top peg
      for (int i = num_balls; i < target; i++) {
        spawnBall(&balls[i]) ;
      }
      // Removing balls: the extras just stop being updated/drawn
      num_balls = target ;
      // [OPT 5] Auto-balance: shift 0.1% of the balls toward the core that finished first
      int diff = (int)core1_us - (int)core0_us ;
      if      (diff >  SPLIT_DEADBAND) split_pm = MIN(split_pm + 1, 1000) ;
      else if (diff < -SPLIT_DEADBAND) split_pm = MAX(split_pm - 1, 0) ;
      // [OPT 2] decide which balls each core owns this frame
      split = (num_balls * split_pm) / 1000 ;

      // [OPT 5] Barrier: release core 1, then wait for the bottom half and the histogram
      PT_SEM_SDK_SIGNAL(pt, &top_semaphore) ;
      PT_SEM_SDK_WAIT(pt, &bot_semaphore) ;

      // [OPT 2][OPT 8] Core 0's share of the balls: [0, split), run from SRAM
      updateAndDrawRange(0, split) ;

      // === TEXT === (core times shown are last frame's; core0_us includes the text)
      sprintf(text_str, "Balls:  %d", num_balls) ;
      drawTextVGA437(10, 10, text_str, WHITE, BLACK) ;
      sprintf(text_str, "Fallen: %d", fallen_core[0] + fallen_core[1]) ;
      drawTextVGA437(10, 30, text_str, WHITE, BLACK) ;
      sprintf(text_str, "Time:   %d s", (int)(time_us_64() / 1000000)) ;
      drawTextVGA437(10, 50, text_str, WHITE, BLACK) ;
      // [OPT 2] Per-core times and Spare (set by the slower core; ~0 = at the ball limit)
      static uint32_t slowest ;
      slowest = MAX(core0_us, core1_us) ;
      sprintf(text_str, "Core0: %5d us", (int)core0_us) ;
      drawTextVGA437(10, 70, text_str, WHITE, BLACK) ;
      sprintf(text_str, "Core1: %5d us", (int)core1_us) ;
      drawTextVGA437(10, 90, text_str, WHITE, BLACK) ;
      sprintf(text_str, "Spare: %5d us", (int)FRAME_BUDGET_US - (int)slowest) ;
      drawTextVGA437(10, 110, text_str, WHITE, BLACK) ;
      // Knob mode and parameters (mode names padded so a shorter one overwrites a longer one)
      static const char* const mode_name[ROT_NUM_MODES] = { "BALLS  ", "BOUNCE ", "GRAVITY" } ;
      sprintf(text_str, "Knob:   %s", mode_name[rot_mode]) ;
      drawTextVGA437(10, 130, text_str, WHITE, BLACK) ;
      sprintf(text_str, "Bounce: %d.%02d", bounce_pct / 100, bounce_pct % 100) ;
      drawTextVGA437(10, 150, text_str, WHITE, BLACK) ;
      sprintf(text_str, "Gravity:%d.%02d", grav_pct / 100, grav_pct % 100) ;
      drawTextVGA437(10, 170, text_str, WHITE, BLACK) ;
      // [OPT 5] core 0's current share of the balls
      sprintf(text_str, "Split: %3d.%d%%", split_pm / 10, split_pm % 10) ;
      drawTextVGA437(10, 190, text_str, WHITE, BLACK) ;
      sprintf(text_str, "Missed: %d", missed_frames) ;
      drawTextVGA437(10, 210, text_str, WHITE, BLACK) ;
      core0_us = time_us_32() - t0 ;

      // [OPT 2] Join: wait for core 1, so the next clear can't wipe a buffer it's drawing
      PT_SEM_SDK_WAIT(pt, &done_semaphore) ;

      // Missed-deadline check: vsync already flagged again = this frame was late.
      // Only peek; draw_start_signal() consumes the flag to start the next frame.
      if (*(volatile int*)&start_flag) {
        missed_frames++ ;
        led_hold = LED_HOLD_FRAMES ;
      } else if (led_hold > 0) {
        led_hold-- ;
      }
      gpio_put(LED_PIN, led_hold > 0) ;

     // NEVER exit while
    } // END WHILE(1)
  PT_END(pt);
} // animation thread


// Animation on core 1: bottom-half clear, histogram, pegs, its share of the balls
static PT_THREAD (protothread_anim1(struct pt *pt))
{
    // Mark beginning of thread
    PT_BEGIN(pt);

    while(1) {
      // [OPT 2] Fork: wait for core 0 to start the frame
      PT_SEM_SDK_WAIT(pt, &draw_semaphore) ;
      static uint32_t t1 ;
      t1 = time_us_32() ;

      // [OPT 5] Clear the bottom half while core 0 clears the top, then draw the
      // histogram (bins are stable: core 0 isn't counting balls yet)
      clearLowFrame(CLEAR_SPLIT_Y, BLACK) ;
      drawHistogram() ;

      // [OPT 5] Barrier: bottom done; wait for the top half and final num_balls/split
      PT_SEM_SDK_SIGNAL(pt, &bot_semaphore) ;
      PT_SEM_SDK_WAIT(pt, &top_semaphore) ;

      // [OPT 2] Hollow pegs, drawn by core 1. Balls never overlap pegs
      // (TELEPORT_DIST), so drawing order between the cores doesn't matter.
      for (int i = 0; i < NUM_PEGS; i++) {
        drawCircle(fix2int15(peg_x[i]), fix2int15(peg_y[i]), PEG_RADIUS, WHITE) ;   // hollow
      }

      // [OPT 2][OPT 8] Core 1's share of the balls: [split, num_balls), run from SRAM
      updateAndDrawRange(split, num_balls) ;

      core1_us = time_us_32() - t1 ;
      // [OPT 2] Join: tell core 0 this share is done
      PT_SEM_SDK_SIGNAL(pt, &done_semaphore) ;
    } // END WHILE(1)
  PT_END(pt);
} // animation thread

// ========================================
// === core 1 main -- started in main below
// ========================================
void core1_main(){
  // Add animation thread
  pt_add_thread(protothread_anim1);
  // Start the scheduler
  pt_schedule_start ;

}

// ========================================
// === main
// ========================================
// USE ONLY C-sdk library
int main(){
  // ===================================================================
  // [OPT 6] OVERCLOCK 150 -> 300 -> 350 MHz
  //   Bottleneck : CPU time. At 150 MHz Spare hit 0 at 5,200 balls.
  //   Approach   : raise the core voltage first (the RP2350 does not do it
  //                automatically; 1.30 V is the max without unlocking the
  //                regulator), then the system clock. VGA needs a fixed
  //                25 MHz pixel clock, so with sys_clk = D x 25 MHz:
  //                hsync/vsync clkdiv = D, rgb.pio holds = D-1 / D-3
  //                (D = 14 at 350 MHz; see the VGA/*.pio files). The sound
  //                DMA timer reads clock_get_hz(), so it adapts by itself.
  //   350 MHz PLL : needs a 1050 MHz VCO (/3 /1), which isn't a multiple of
  //                the 12 MHz crystal, so set_sys_clock_khz() (reference
  //                divider 1 only) can't produce it and would halt at boot.
  //                Program the PLL directly with reference divider 2:
  //                6 MHz x 175 = 1050 MHz -- same steps as set_sys_clock_pll().
  //   Expected / measured : 300 MHz: ~2x CPU; measured 3,150 us spare at
  //                10,000 balls (RAM, not CPU, was the limit -> OPT 7).
  //                350 MHz: +17%; measured 13,000 balls at 0 us spare
  //                (with the 12-byte ball and hollow drawing).
  // ===================================================================
  vreg_set_voltage(VREG_VOLTAGE_1_30) ;
  busy_wait_us(10000) ;                 // let the voltage settle before raising the clock
  // Run clk_sys from the 48 MHz USB PLL while the sys PLL is reprogrammed
  clock_configure_undivided(clk_sys,
                            CLOCKS_CLK_SYS_CTRL_SRC_VALUE_CLKSRC_CLK_SYS_AUX,
                            CLOCKS_CLK_SYS_CTRL_AUXSRC_VALUE_CLKSRC_PLL_USB,
                            USB_CLK_HZ) ;
  pll_init(pll_sys, 2, 1050 * MHZ, 3, 1) ;
  clock_configure_undivided(clk_sys,
                            CLOCKS_CLK_SYS_CTRL_SRC_VALUE_CLKSRC_CLK_SYS_AUX,
                            CLOCKS_CLK_SYS_CTRL_AUXSRC_VALUE_CLKSRC_PLL_SYS,
                            350 * MHZ) ;
  // Peripherals (UART, SPI) on the fixed 48 MHz USB PLL, as set_sys_clock_khz() did
  clock_configure_undivided(clk_peri, 0,
                            CLOCKS_CLK_PERI_CTRL_AUXSRC_VALUE_CLKSRC_PLL_USB,
                            USB_CLK_HZ) ;
  // initialize stio
  stdio_init_all() ;

  // initialize VGA
  initVGA() ;

  // initialize the DAC + DMA for the peg sound
  initPegSound() ;

  // === ROTARY ENCODER === A/B interrupt on both edges, with pull-ups
  gpio_init(ROT_A);
  gpio_init(ROT_B);
  gpio_set_dir(ROT_A, GPIO_IN);
  gpio_set_dir(ROT_B, GPIO_IN);
  gpio_pull_up(ROT_A);
  gpio_pull_up(ROT_B);
  rot_prev_state = (gpio_get(ROT_A) << 1) | gpio_get(ROT_B) ;
  gpio_set_irq_enabled_with_callback(ROT_A, GPIO_IRQ_EDGE_RISE | GPIO_IRQ_EDGE_FALL, true, &rot_ISR);
  gpio_set_irq_enabled(ROT_B, GPIO_IRQ_EDGE_RISE | GPIO_IRQ_EDGE_FALL, true);
  // Push button: active high, so pull down. Polled by pollButton(), no IRQ.
  gpio_init(ROT_SW);
  gpio_set_dir(ROT_SW, GPIO_IN);
  gpio_pull_down(ROT_SW);
  gpio_set_input_enabled(ROT_SW, false);  // E9 workaround: see pollButton()

  // Missed-deadline LED (on-board), off until a frame misses
  gpio_init(LED_PIN);
  gpio_set_dir(LED_PIN, GPIO_OUT);
  gpio_put(LED_PIN, 0);

  // Semaphores (initial count 0, max 1): [OPT 2] fork/join, [OPT 5] clear barrier
  sem_init(&draw_semaphore, 0, 1) ;
  sem_init(&top_semaphore, 0, 1) ;
  sem_init(&bot_semaphore, 0, 1) ;
  sem_init(&done_semaphore, 0, 1) ;

  // start core 1
  multicore_reset_core1();
  multicore_launch_core1(&core1_main);

  // add threads
  pt_add_thread(protothread_serial);
  pt_add_thread(protothread_anim);

  // start scheduler
  pt_schedule_start ;
}
