
/**
 * Hunter Adams (vha3@cornell.edu)
 * 
 * This demonstration animates two balls bouncing about the screen.
 * Through a serial interface, the user can change the ball color.
 *
 * HARDWARE CONNECTIONS
  - GPIO 16 ---> VGA Hsync
  - GPIO 17 ---> VGA Vsync
  - GPIO 18 ---> VGA Green lo-bit --> 470 ohm resistor --> VGA_Green
  - GPIO 19 ---> VGA Green hi_bit --> 330 ohm resistor --> VGA_Green
  - GPIO 20 ---> 330 ohm resistor ---> VGA-Blue
  - GPIO 21 ---> 330 ohm resistor ---> VGA-Red
  - RP2040 GND ---> VGA-GND

  Rotary encoder
  GPIO 12 green left side.  A
  GPIO 11 yellow right side  B

  MCP4822 DAC (spi1)
  GPIO 13 ---> CS
  GPIO 14 ---> SCK
  GPIO 15 ---> MOSI (SDI)
 *
 * RESOURCES USED
 *  - PIO state machines 0, 1, and 2 on PIO instance 0
 *  - DMA channels (2, by claim mechanism)
 *  - 153.6 kBytes of RAM (for pixel color data)
 *
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
#define float2fix15(a) ((fix15)((a)*32768.0f)) // 2^15 (float, not double: the M33 FPU is single-precision only)
#define fix2float15(a) ((float)(a)/32768.0f)
#define absfix15(a) abs(a) 
#define int2fix15(a) ((fix15)(a << 15))
#define fix2int15(a) ((int)(a >> 15))
#define char2fix15(a) (fix15)(((fix15)(a)) << 15)
#define divfix(a,b) (fix15)(div_s64s64( (((signed long long)(a)) << 15), ((signed long long)(b))))

// uS per frame
#define FRAME_RATE 33000

// =====================================================================
// === ROTARY ENCODER INTERFACE ========================================
// =====================================================================
#define ROT_A  12
#define ROT_B  11
#define ROT_SW 10   // push button: reads HIGH while pressed

// The encoder has two modes, toggled by the push button:
//   ROT_MODE_BALLS  - one click = +/- BALL_STEP balls
//   ROT_MODE_BOUNCE - one click = +/- BOUNCE_STEP (in hundredths) bounciness
#define ROT_MODE_BALLS  0
#define ROT_MODE_BOUNCE 1
volatile int rot_mode = ROT_MODE_BALLS ;

#define MIN_BALLS  1
#define MAX_BALLS  16000   // 192 KB of balls at 12 bytes/ball (~17k is the RAM ceiling)
#define INIT_BALLS 100
#define BALL_STEP  100
volatile int rot_counter = INIT_BALLS ;   // = number of balls to animate

// Bounciness is kept in hundredths (0..100) for the knob and the display,
// and mirrored as fix15 for the physics
#define MIN_BOUNCE  0
#define MAX_BOUNCE  100
#define INIT_BOUNCE 30
#define BOUNCE_STEP 5
volatile int   bounce_pct = INIT_BOUNCE ;
volatile fix15 bounciness = (INIT_BOUNCE << 15) / 100 ;

static volatile uint8_t rot_prev_state = 3 ; // (A<<1)|B ; 3 = rest (both high)
static volatile int8_t  rot_accum = 0 ;      // steps taken since last rest

// Lookup table: index = (prev_state<<2)|curr_state.
// +1 = one valid step clockwise, -1 = one valid step counterclockwise,
//  0 = no change, or a state jump that skips a step (bounce/noise) -- ignore.
static const int8_t rot_table[16] = {
/* prev=0(00) */  0, -1, +1,  0,
/* prev=1(01) */ +1,  0,  0, -1,
/* prev=2(10) */ -1,  0,  0, +1,
/* prev=3(11) */  0, +1, -1,  0
} ;

// Apply one detent of the knob (dir = +1 CW, -1 CCW) to whichever value
// the current mode controls, clamped to its range
static void rot_click(int dir)
{
  if (rot_mode == ROT_MODE_BALLS) {
    rot_counter = MIN(MAX(rot_counter + dir * BALL_STEP, MIN_BALLS), MAX_BALLS) ;
  } else {
    bounce_pct = MIN(MAX(bounce_pct + dir * BOUNCE_STEP, MIN_BOUNCE), MAX_BOUNCE) ;
    bounciness = (bounce_pct << 15) / 100 ;
  }
}

// Push button, polled once per frame from the animation thread. 
// Toggles the mode on each press (low -> high), whatever the hold time.
static void pollButton(void)
{
  static int sw_prev = 0 ;
  gpio_set_input_enabled(ROT_SW, true) ;
  busy_wait_us(1) ;                    // let the input synchronizer settle
  int sw = gpio_get(ROT_SW) ;
  gpio_set_input_enabled(ROT_SW, false) ;
  if (sw && !sw_prev) {
    rot_mode = (rot_mode == ROT_MODE_BALLS) ? ROT_MODE_BOUNCE : ROT_MODE_BALLS ;
    rot_accum = 0 ;                    // don't carry a partial turn into the new mode
  }
  sw_prev = sw ;
}

// Fires on every edge of EITHER A or B.
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
#define GRAVITY      float2fix15(0.37)
// bounciness (set by the knob) is defined with the rotary encoder above
#define BALL_RADIUS  4
#define PEG_RADIUS   6
#define PEG_VERT_SEP 19
#define PEG_HORZ_SEP 38
#define SCREEN_W     640
#define SCREEN_H     480
// collision distances in fix15 (center-to-center)
#define COLLIDE_DIST  int2fix15(BALL_RADIUS + PEG_RADIUS)
#define TELEPORT_DIST int2fix15(BALL_RADIUS + PEG_RADIUS + 1)
// squared collision distance (px^2, in fix15), so the test needs no sqrt
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

// Index of the peg nearest (x, y), or -1 if the ball isn't within half a
// spacing of any peg. Rows are 19 px apart and the collision distance is 10,
// so the nearest peg is the only one the ball can be touching.
int nearestPeg(fix15 x, fix15 y)
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

// A ball is packed into 12 bytes (was 24): RAM is the limit on MAX_BALLS,
// since the two VGA frame buffers already take 307 KB. Use the BALL_* macros
// and ballStore() below; updateBall() works on unpacked locals.
//   xm, ym: position (fix15) in bits 31..5 -- 27 bits signed = +/-2048 px,
//           which keeps FULL fix15 precision (balls fly out to ~1300 px at
//           bounciness 1). The 5 low bits of each hold the 9-bit "meta":
//           meta bits 8..1 = last_peg + 1 (0 = none yet), bit 0 = binned.
//   vx, vy: velocity as fix10 (1/1024 px/frame, +/-32 px/frame; balls never
//           exceed ~17). Checked against full fix15 in a PC simulation of
//           this exact physics: same histogram, with spawnBall() adding a
//           sub-pixel drop jitter so the board still sees plenty of distinct
//           starting conditions.
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

// fix15 -> fix10, rounded to nearest (a plain >> would always round toward
// -inf and bias every ball left/up) and saturated to int16
static inline int16_t fix2vel(fix15 a)
{
  a = (a + 16) >> 5 ;
  return (int16_t)MIN(MAX(a, -32767), 32767) ;
}

// Pack a ball's state. Positions are clamped to +/-2047 px so the << 5 can't
// overflow (only balls far off screen ever get near it)
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
// [MULTICORE] total_fallen removed -- replaced by per-core fallen_core[] below

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

// [MULTICORE] was: int bins[NUM_BINS] ; (and a single total_fallen counter)
// Both cores bin balls now, and ++ isn't atomic across cores, so each core
// keeps its own counts. Index [get_core_num()] to write, sum both to read.
int bins_core[2][NUM_BINS] ;
int fallen_core[2] ;

// Drop the ball from just above the top peg with zero y-velocity and a small random
// x-velocity in (-0.25, 0.25) so it doesn't land on the peg dead-center.
//  - vx is forced odd at fix10, so it is never exactly 0: a ball dropped
//    with vx = 0 hits the top peg dead-center and bounces in place forever
//  - x gets a random sub-pixel offset (+/-0.5 px), so the board still sees
//    plenty of distinct starting conditions with vx stored at fix10
void spawnBall(ball_t* b)
{
  fix15 x  = int2fix15(SCREEN_W / 2) + (fix15)((rand() & 0x7FFF) - 0x4000) ;  // 0x4000 = 0.5 px
  fix15 vx = vel2fix15(((rand() & 0x1FF) - 0x100) | 1) ;                       // 0x100 = 0.25 at fix10
  ballStore(b, x, int2fix15(BOARD_TOP_Y - 50), vx, 0, MAKE_META(-1, 0)) ;      // no peg yet, not binned
}

// Count a ball that just passed the bottom row: which gap did it go through?
// (the caller marks the ball as binned)
void binBall(fix15 x)
{
  int xi = fix2int15(x) - BOTTOM_LEFT_X ;          // relative to leftmost bottom peg
  int bin = (xi < 0) ? 0 : (xi / PEG_HORZ_SEP) + 1 ;  // left of it = bin 0
  if (bin > NUM_BINS - 1) bin = NUM_BINS - 1 ;        // right of rightmost peg
  // [MULTICORE] was: bins[bin]++ ; total_fallen++ ;
  // count into this core's own arrays so the two cores never race
  int core = get_core_num() ;
  bins_core[core][bin]++ ;
  fallen_core[core]++ ;
}

// Draw the histogram under the board, scaled so the fullest bin is HIST_H tall
void drawHistogram()
{
  // [MULTICORE] was: read bins[k] directly. Now sum the two cores' counts once.
  int bins[NUM_BINS] ;
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
// DAC wiring (same as Lab 1)
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

  // Sine at PEG_SOUND_FREQ with a short linear attack and a linear decay to
  // zero, centered on mid-scale (2048) so the DAC rests at mid-scale after
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
    
  // Setup the control channel
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

  // DMA pacing timer: rate = (X/Y) * sys_clk = sys_clk / 3000 = 50 kHz at 150 MHz
  int snd_timer = dma_claim_unused_timer(true) ;
  dma_timer_set_fraction(snd_timer, 1, (uint16_t)(clock_get_hz(clk_sys) / SOUND_FS)) ;

  // Setup the data channel
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

// Peg-strike sound. drop sound if bounces overlapped
void playPegSound()
{
  if (dma_channel_is_busy(snd_data_chan) || dma_channel_is_busy(snd_ctrl_chan)) return ;
  dma_start_channel_mask(1u << snd_ctrl_chan) ;
}

// One frame of ball physics 
void updateBall(ball_t* b)
{
  // Unpack the ball into locals; packed back at the end
  fix15 x       = BALL_POS(b->xm) ;
  fix15 y       = BALL_POS(b->ym) ;
  fix15 vx      = vel2fix15(b->vx) ;
  fix15 vy      = vel2fix15(b->vy) ;
  int meta      = BALL_META(b) ;
  int last_peg  = META_LAST_PEG(meta) ;
  int binned    = META_BINNED(meta) ;

  // Past the bottom row there are no pegs left to hit (and gravity keeps
  // it moving down), so skip the substeps and peg search: just move it.
  if (y > BIN_LINE_Y) {
    x = x + vx ;
    y = y + vy ;
  } else {
    // Split this frame's motion into substeps of at most ~4 px, so a fast
    // ball can't jump past a peg, or land deep inside it, between checks.
    int speed = fix2int15(MAX(absfix15(vx), absfix15(vy))) ;
    int steps = (speed >> 2) + 1 ;
    fix15 step_vx = vx / steps ;   // divide once, not every substep
    fix15 step_vy = vy / steps ;

    for (int s = 0; s < steps; s++) {
      // Move one substep
      x = x + step_vx ;
      y = y + step_vy ;

      // Only the nearest peg can be in contact
      int peg = nearestPeg(x, y) ;
      if (peg < 0) continue ;
      fix15 dx = x - peg_x[peg] ;
      fix15 dy = y - peg_y[peg] ;

      // Cheap bounding-box check first, then compare SQUARED distances, so
      // near-misses in the box corners never pay for a sqrt
      if ((absfix15(dx) < COLLIDE_DIST) && (absfix15(dy) < COLLIDE_DIST)) {
        fix15 dist2 = multfix15(dx,dx) + multfix15(dy,dy) ;

        // dist2 > 0 guards the divide if the ball lands exactly on the peg center
        if ((dist2 < COLLIDE_DIST2) && (dist2 > 0)) {
          // Normal vector pointing from peg to ball. 1/distance in single-
          // precision float: the M33 FPU does sqrt and divide in hardware,
          // while divfix is a 64-bit software divide. dx*inv is already fix15.
          float inv_dist = 1.0f / sqrtf(fix2float15(dist2)) ;
          fix15 normal_x = (fix15)(dx * inv_dist) ;
          fix15 normal_y = (fix15)(dy * inv_dist) ;

          // Velocity component along the normal: < 0 means moving INTO the peg
          fix15 v_dot_n = multfix15(normal_x, vx) + multfix15(normal_y, vy) ;

          // Teleport outside the collision distance, along the normal
          x = peg_x[peg] + multfix15(normal_x, TELEPORT_DIST) ;
          y = peg_y[peg] + multfix15(normal_y, TELEPORT_DIST) ;

          // Only reflect if approaching
          if (v_dot_n < 0) {
            fix15 intermediate_term = multfix15(int2fix15(-2), v_dot_n) ;
            vx = vx + multfix15(normal_x, intermediate_term) ;
            vy = vy + multfix15(normal_y, intermediate_term) ;

            // Did we just strike a new peg
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

  // Count it in the histogram as it leaves the board (not at the screen
  // bottom, since it keeps drifting sideways as it falls)
  if (!binned && (y > BIN_LINE_Y)) {
    binBall(x) ;
    binned = 1 ;
  }

  // Re-spawn any ball that falls thru the bottom of the SCREEN
  if (y > int2fix15(SCREEN_H)) {
    spawnBall(b) ;
    return ;
  }

  // Apply gravity, then pack the ball back
  ballStore(b, x, y, vx, vy + GRAVITY, MAKE_META(last_peg, binned)) ;
}

// the color of the boid
char color = CYAN ;

// Create a semaphore
semaphore_t draw_semaphore ;   // core 0 -> core 1: "new frame, start clearing your half"

// [MULTICORE] new: the two halves of a two-way barrier between clearing and
// drawing. Neither core may draw until BOTH halves of the buffer are clear
// (any ball can be anywhere on screen).
//   top_semaphore: core 0 -> core 1: "top cleared, num_balls/split are final"
//   bot_semaphore: core 1 -> core 0: "bottom cleared, histogram drawn"
semaphore_t top_semaphore ;
semaphore_t bot_semaphore ;

// [MULTICORE] new: core 1 -> core 0: "my share of this frame is drawn".
// Keeps core 0 from clearing the next frame while core 1 is still drawing.
semaphore_t done_semaphore ;

// [MULTICORE] new: core 0 clears rows [0, CLEAR_SPLIT_Y), core 1 clears
// [CLEAR_SPLIT_Y, 480) and then draws the histogram (which lives down there)
#define CLEAR_SPLIT_Y 240

// [MULTICORE] new: balls [0, split) run on core 0, [split, num_balls) on core 1.
// Core 0's share is kept in per-mille (split_pm) and auto-balanced every
// frame from the measured core times, so it tracks the cost of the pegs,
// text, histogram, and where the balls are on the board.
#define SPLIT_PM_INIT  600     // starting guess: core 0 takes 60% of the balls
#define SPLIT_DEADBAND 50      // us: don't chase differences smaller than this
int split_pm = SPLIT_PM_INIT ; // only touched by core 0
volatile int split = 0 ;

// [MULTICORE] new: how long each core spent on its share last frame (us)
volatile uint32_t core0_us = 0 ;
volatile uint32_t core1_us = 0 ;
#define FRAME_BUDGET_US 16667   // DOUBLE_BUFFER_60 -> 60 fps

// === FAST BALL DRAW ===
// Balls are hollow rings. drawCircle() would recompute the same shape for
// every ball and plot it one pixel at a time through drawPixel(). The radius
// never changes, so compute each row's outer and inner (hole) half-widths
// once and write the pixels straight into the frame buffer.
extern char * current_draw_buffer ;     // defined in vga16_graphics_v3.c
int32_t sqrt_i32(int32_t v) ;           // defined in vga16_graphics_v3.c
static int ball_dx[BALL_RADIUS + 1] ;   // outer half-width of row i above/below center
static int ball_hx[BALL_RADIUS + 1] ;   // hole half-width of row i (0 = solid row)

// Ring = disk of radius r minus disk of radius r-1 (same half-width formula
// as fillCircle()). For r = 4 that's 1-2 px thick sides and solid top/bottom.
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

// Fill pixels [x, x+w) of one 640-px row (320 bytes, 2 px/byte:
// even x in the low nibble, odd x in the high nibble -- same as drawPixel)
static inline void drawSpan(unsigned char* row, int x, int w, unsigned char c)
{
  if (x & 1) {                                   // lone pixel at the left
    row[x >> 1] = (row[x >> 1] & 0x0F) | (c << 4) ;
    x++ ; w-- ;
  }
  unsigned char* p = row + (x >> 1) ;
  unsigned char both = c | (c << 4) ;
  for (; w >= 2; w -= 2) *p++ = both ;           // whole bytes
  if (w) *p = (*p & 0xF0) | c ;                  // lone pixel at the right
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

static inline void drawBall(int x0, int y0, char c)
{
  // Fast path only when the whole ball is on screen; otherwise fall back
  // to drawCircle(), which handles the clipping
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

// [MULTICORE] new: physics + draw for one ball, shared by both cores
static inline void updateAndDrawBall(ball_t* b)
{
  updateBall(b) ;
  drawBall(fix2int15(BALL_POS(b->xm)), fix2int15(BALL_POS(b->ym)), color) ;
}

// ==================================================
// === users serial input thread
// ==================================================
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
        // update boid color
        if ((user_input > 0) && (user_input < 16)) {
          color = (char)user_input ;
        }
      } // END WHILE(1)
  PT_END(pt);
} // timer thread

// Animation on core 0
static PT_THREAD (protothread_anim(struct pt *pt))
{
    // Mark beginning of thread
    PT_BEGIN(pt);

    // === GALTON BOARD: build the peg table (balls are added in the loop) ===
    initPegs() ;
    initBallSprite() ;

    static char text_str[40] ;

    while(1) {
      // Wait for the signal that the buffer's changed
      PT_YIELD_UNTIL(pt, draw_start_signal()) ;
      // [MULTICORE] new: time core 0's share of the frame
      static uint32_t t0 ;
      t0 = time_us_32() ;

      // [MULTICORE] changed: wake core 1 right away so the two cores clear
      // the buffer in parallel (was: core 0 cleared it all, core 1 idle)
      PT_SEM_SDK_SIGNAL(pt, &draw_semaphore) ;
      clearRegion(0, CLEAR_SPLIT_Y, BLACK) ;

      // [MULTICORE] the encoder / spawn bookkeeping runs before core 1 is
      // released to draw (top_semaphore), so core 1 never updates a ball
      // that core 0 is re-spawning, and it sees final num_balls / split.
      // === ROTARY ENCODER: match the ball count to the knob ===
      pollButton() ;                 // push button: toggle knob mode on press
      int target = rot_counter ;     // read the ISR's value once
      // Adding balls: all new ones spawn at the same spot above the top peg
      for (int i = num_balls; i < target; i++) {
        spawnBall(&balls[i]) ;
      }
      // Removing balls: the extras just stop being updated/drawn
      num_balls = target ;
      // [MULTICORE] new: auto-balance. Last frame's times are both measured
      // from the start of the frame, so they compare finish times; shift
      // balls toward whichever core finished first. 1 per-mille per frame
      // (~60 per-mille/s) is slow enough not to oscillate on noisy timings.
      int diff = (int)core1_us - (int)core0_us ;
      if      (diff >  SPLIT_DEADBAND) split_pm = MIN(split_pm + 1, 1000) ;
      else if (diff < -SPLIT_DEADBAND) split_pm = MAX(split_pm - 1, 0) ;
      // decide which balls each core owns this frame
      split = (num_balls * split_pm) / 1000 ;

      // [MULTICORE] new: barrier. Release core 1 (top is clear, split is
      // final), then wait until the bottom is clear and the histogram drawn,
      // so balls from both cores land on a clean buffer, on top of the bars.
      PT_SEM_SDK_SIGNAL(pt, &top_semaphore) ;
      PT_SEM_SDK_WAIT(pt, &bot_semaphore) ;

      // [MULTICORE] removed from core 0: the 136-peg draw loop (now on core 1)
      // [MULTICORE] moved to core 1: bottom-half clear and drawHistogram()

      // [MULTICORE] changed: was update ALL balls, then draw ALL balls.
      // Core 0 now updates + draws only balls [0, split); core 1 does the rest.
      for (int i = 0; i < split; i++) {
        updateAndDrawBall(&balls[i]) ;
      }

      // === TEXT ===
      // (shows last frame's core times; core0_us is taken after the text so
      // it includes the text cost too -- it's part of core 0's frame)
      sprintf(text_str, "Balls:  %d", num_balls) ;
      drawTextVGA437(10, 10, text_str, WHITE, BLACK) ;
      // [MULTICORE] changed: was total_fallen, now the sum of both cores' counts
      sprintf(text_str, "Fallen: %d", fallen_core[0] + fallen_core[1]) ;
      drawTextVGA437(10, 30, text_str, WHITE, BLACK) ;
      sprintf(text_str, "Time:   %d s", (int)(time_us_64() / 1000000)) ;
      drawTextVGA437(10, 50, text_str, WHITE, BLACK) ;
      // [MULTICORE] new: per-core work time and the spare time left in the
      // frame. Spare time is set by the slower core; if it's near 0, you're
      // at the ball limit. The split auto-balances the two (shown as Split).
      static uint32_t slowest ;
      slowest = MAX(core0_us, core1_us) ;
      sprintf(text_str, "Core0: %5d us", (int)core0_us) ;
      drawTextVGA437(10, 70, text_str, WHITE, BLACK) ;
      sprintf(text_str, "Core1: %5d us", (int)core1_us) ;
      drawTextVGA437(10, 90, text_str, WHITE, BLACK) ;
      sprintf(text_str, "Spare: %5d us", (int)FRAME_BUDGET_US - (int)slowest) ;
      drawTextVGA437(10, 110, text_str, WHITE, BLACK) ;
      // Knob mode (toggled by the push button) and the bounciness value
      sprintf(text_str, "Knob:   %s", (rot_mode == ROT_MODE_BALLS) ? "BALLS " : "BOUNCE") ;
      drawTextVGA437(10, 130, text_str, WHITE, BLACK) ;
      sprintf(text_str, "Bounce: %d.%02d", bounce_pct / 100, bounce_pct % 100) ;
      drawTextVGA437(10, 150, text_str, WHITE, BLACK) ;
      // [MULTICORE] new: core 0's current share of the balls
      sprintf(text_str, "Split: %3d.%d%%", split_pm / 10, split_pm % 10) ;
      drawTextVGA437(10, 170, text_str, WHITE, BLACK) ;
      core0_us = time_us_32() - t0 ;

      // [MULTICORE] new: wait for core 1 to finish its share before looping
      // back, so the next clearLowFrame can't wipe a buffer it's still drawing
      PT_SEM_SDK_WAIT(pt, &done_semaphore) ;

     // NEVER exit while
    } // END WHILE(1)
  PT_END(pt);
} // animation thread


// Animation on core 1
static PT_THREAD (protothread_anim1(struct pt *pt))
{
    // Mark beginning of thread
    PT_BEGIN(pt);

    while(1) {
      // Wait for the signal from core 0
      PT_SEM_SDK_WAIT(pt, &draw_semaphore) ;
      // [MULTICORE] new: everything below is core 1's share of the frame
      static uint32_t t1 ;
      t1 = time_us_32() ;

      // [MULTICORE] new: clear the bottom half while core 0 clears the top,
      // then draw the histogram (it sits entirely in the bottom half, and
      // core 0 isn't binning balls yet, so bins_core is stable here)
      clearLowFrame(CLEAR_SPLIT_Y, BLACK) ;
      drawHistogram() ;

      // [MULTICORE] new: barrier -- wait for the top half to be clear and for
      // num_balls / split to be final, then let core 0 start drawing too
      PT_SEM_SDK_SIGNAL(pt, &bot_semaphore) ;
      PT_SEM_SDK_WAIT(pt, &top_semaphore) ;

      // [MULTICORE] moved from core 0: draw the pegs. Balls are always pushed
      // out to TELEPORT_DIST, so they never overlap a peg and draw order
      // between the two cores doesn't matter.
      for (int i = 0; i < NUM_PEGS; i++) {
        drawCircle(fix2int15(peg_x[i]), fix2int15(peg_y[i]), PEG_RADIUS, WHITE) ;   // hollow
      }

      // [MULTICORE] new: update + draw balls [split, num_balls)
      for (int i = split; i < num_balls; i++) {
        updateAndDrawBall(&balls[i]) ;
      }

      core1_us = time_us_32() - t1 ;
      // [MULTICORE] new: tell core 0 this frame's share is done
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
  // Overclock 150 -> 350 MHz. The VGA PIO timing depends on this: see the
  // clkdivs in hsync.pio / vsync.pio and the pixel holds in rgb.pio.
  // The RP2350 doesn't raise the core voltage on its own, so do it first
  // and let it settle (1.30 V is the max without unlocking the regulator).
  vreg_set_voltage(VREG_VOLTAGE_1_30) ;
  busy_wait_us(10000) ;
  // 350 MHz needs a 1050 MHz VCO (/3 /1), which isn't a multiple of the
  // 12 MHz crystal, so set_sys_clock_khz() (reference divider 1 only) can't
  // make it. Same steps as the SDK's set_sys_clock_pll(), but with reference
  // divider 2: 6 MHz reference x 175 = 1050 MHz.
  // Run clk_sys from the 48 MHz USB PLL while sys PLL is reprogrammed
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

  // === ROTARY ENCODER ===
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

  // Initialize the semaphore
  // Arguments: pointer to sem, initial count, max count
  sem_init(&draw_semaphore, 0, 1) ;
  // [MULTICORE] new: clear-then-draw barrier
  sem_init(&top_semaphore, 0, 1) ;
  sem_init(&bot_semaphore, 0, 1) ;
  // [MULTICORE] new: core 1 -> core 0 "done" semaphore
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
