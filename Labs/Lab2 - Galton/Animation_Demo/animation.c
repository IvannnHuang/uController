
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
// Include protothreads
#include "pt_cornell_rp2040_v1_4.h"

// === the fixed point macros ========================================
typedef signed int fix15 ;
#define multfix15(a,b) ((fix15)((((signed long long)(a))*((signed long long)(b)))>>15))
#define float2fix15(a) ((fix15)((a)*32768.0)) // 2^15
#define fix2float15(a) ((float)(a)/32768.0)
#define absfix15(a) abs(a) 
#define int2fix15(a) ((fix15)(a << 15))
#define fix2int15(a) ((int)(a >> 15))
#define char2fix15(a) (fix15)(((fix15)(a)) << 15)
#define divfix(a,b) (fix15)(div_s64s64( (((signed long long)(a)) << 15), ((signed long long)(b))))

// Wall detection
#define hitBottom(b) (b>int2fix15(380))
#define hitTop(b) (b<int2fix15(100))
#define hitLeft(a) (a<int2fix15(100))
#define hitRight(a) (a>int2fix15(540))

// uS per frame
#define FRAME_RATE 33000

// =====================================================================
// === ROTARY ENCODER INTERFACE ========================================
// =====================================================================
#define ROT_A 12
#define ROT_B 11

// The encoder sets the number of balls: one click = one ball
#define MIN_BALLS  1
#define MAX_BALLS  100
#define INIT_BALLS 10
volatile int rot_counter = INIT_BALLS ;   // = number of balls to animate
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

// Fires on every edge of EITHER A or B.
void rot_ISR(uint gpio, uint32_t events)
{
  uint8_t curr_state = (gpio_get(ROT_A) << 1) | gpio_get(ROT_B) ;
  rot_accum += rot_table[(rot_prev_state << 2) | curr_state] ;
  rot_prev_state = curr_state ;

  if (curr_state == 3) {               // landed back at rest (a full click, or none)
    // completed one click; clamp here so extra turns past the limits don't wind up
    if      ((rot_accum >=  4) && (rot_counter < MAX_BALLS)) rot_counter++ ;  // CW
    else if ((rot_accum <= -4) && (rot_counter > MIN_BALLS)) rot_counter-- ;  // CCW
    rot_accum = 0 ;                    // discard partial turns / bounce
  }
}

// =====================================================================
// === GALTON BOARD ====================================================
// =====================================================================
#define GRAVITY      float2fix15(0.37)
#define BOUNCINESS   float2fix15(0.5)
#define BALL_RADIUS  4
#define PEG_RADIUS   6
#define PEG_VERT_SEP 19
#define PEG_HORZ_SEP 38
#define SCREEN_W     640
#define SCREEN_H     480
// collision distances in fix15 (center-to-center)
#define COLLIDE_DIST  int2fix15(BALL_RADIUS + PEG_RADIUS)
#define TELEPORT_DIST int2fix15(BALL_RADIUS + PEG_RADIUS + 1)

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

// === BALLS ===
#define SPAWN_GAP    30   // vertical spacing (px) of newly added balls, so they don't fall as one clump

typedef struct {
  fix15 x, y ;        // position
  fix15 vx, vy ;      // velocity (px/frame)
  int   last_peg ;    // index of the last peg struck (-1 = none yet)
  int   binned ;      // 1 once this drop has been counted in the histogram
} ball_t ;

ball_t balls[MAX_BALLS] ;
int num_balls = 0 ;     // balls currently animated: balls[0 .. num_balls-1]
int total_fallen = 0 ;  // balls that have passed the bottom row since boot

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

int bins[NUM_BINS] ;

// Drop the ball from top-center with zero y-velocity and a small random
// x-velocity in [-0.25, 0.25) so it doesn't land on the peg dead-center
void spawnBall(ball_t* b)
{
  b->x  = int2fix15(SCREEN_W / 2) ;
  b->y  = int2fix15(0) ;
  b->vx = (fix15)((rand() & 0x3FFF) - 0x2000) ;  // 0x2000 = 0.25 in fix15
  b->vy = 0 ;
  b->last_peg = -1 ;
  b->binned = 0 ;
}

// Count a ball that just passed the bottom row: which gap did it go through?
void binBall(ball_t* b)
{
  int xi = fix2int15(b->x) - BOTTOM_LEFT_X ;          // relative to leftmost bottom peg
  int bin = (xi < 0) ? 0 : (xi / PEG_HORZ_SEP) + 1 ;  // left of it = bin 0
  if (bin > NUM_BINS - 1) bin = NUM_BINS - 1 ;        // right of rightmost peg
  bins[bin]++ ;
  total_fallen++ ;
  b->binned = 1 ;
}

// Draw the histogram under the board, scaled so the fullest bin is HIST_H tall
void drawHistogram()
{
  int max_count = 0 ;
  for (int k = 0; k < NUM_BINS; k++) {
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
  // Split this frame's motion into substeps of at most ~4 px, so a fast
  // ball can't jump past a peg, or land deep inside it, between checks.
  int speed = fix2int15(MAX(absfix15(b->vx), absfix15(b->vy))) ;
  int steps = (speed >> 2) + 1 ;

  for (int s = 0; s < steps; s++) {
    // Move one substep
    b->x = b->x + (b->vx / steps) ;
    b->y = b->y + (b->vy / steps) ;

    // Only the nearest peg can be in contact
    int peg = nearestPeg(b->x, b->y) ;
    if (peg < 0) continue ;
    fix15 dx = b->x - peg_x[peg] ;
    fix15 dy = b->y - peg_y[peg] ;

    // Cheap bounding-box check first, only do the sqrt if we're close
    if ((absfix15(dx) < COLLIDE_DIST) && (absfix15(dy) < COLLIDE_DIST)) {
      fix15 distance = float2fix15(sqrtf(fix2float15(multfix15(dx,dx) + multfix15(dy,dy)))) ;

      // distance > 0 guards the divide if the ball lands exactly on the peg center
      if ((distance < COLLIDE_DIST) && (distance > 0)) {
        // Normal vector pointing from peg to ball
        fix15 normal_x = divfix(dx, distance) ;
        fix15 normal_y = divfix(dy, distance) ;

        // Velocity component along the normal: < 0 means moving INTO the peg
        fix15 v_dot_n = multfix15(normal_x, b->vx) + multfix15(normal_y, b->vy) ;

        // Teleport outside the collision distance, along the normal
        b->x = peg_x[peg] + multfix15(normal_x, TELEPORT_DIST) ;
        b->y = peg_y[peg] + multfix15(normal_y, TELEPORT_DIST) ;

        // Only reflect if approaching
        if (v_dot_n < 0) {
          fix15 intermediate_term = multfix15(int2fix15(-2), v_dot_n) ;
          b->vx = b->vx + multfix15(normal_x, intermediate_term) ;
          b->vy = b->vy + multfix15(normal_y, intermediate_term) ;

          // Did we just strike a new peg
          if (peg != b->last_peg) {
            playPegSound() ;
            b->vx = multfix15(BOUNCINESS, b->vx) ;
            b->vy = multfix15(BOUNCINESS, b->vy) ;
            b->last_peg = peg ;
          }
        }
      }
    }
  }

  // Count it in the histogram as it leaves the board (not at the screen
  // bottom, since it keeps drifting sideways as it falls)
  if (!b->binned && (b->y > BIN_LINE_Y)) binBall(b) ;

  // Re-spawn any ball that falls thru the bottom of the SCREEN
  if (b->y > int2fix15(SCREEN_H)) {
    spawnBall(b) ;
    return ;
  }

  // Bounce off the screen's sides. (No top bounce: balls start above the
  // screen at negative y and fall in.)
  if ((b->x < 0)                 && (b->vx < 0)) b->vx = -b->vx ;
  if ((b->x > int2fix15(SCREEN_W)) && (b->vx > 0)) b->vx = -b->vx ;

  // Apply gravity
  b->vy = b->vy + GRAVITY ;
}

// the color of the boid
char color = WHITE ;

// Create a semaphore
semaphore_t draw_semaphore ;

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

    static char text_str[40] ;

    while(1) {
      // Wait for the signal that the buffer's changed
      PT_YIELD_UNTIL(pt, draw_start_signal()) ;
      // Clear the buffer
      clearLowFrame(0, BLACK);
      // Signal core 1 that it can start drawing
      PT_SEM_SDK_SIGNAL(pt, &draw_semaphore) ;

      // === ROTARY ENCODER: match the ball count to the knob ===
      int target = rot_counter ;     // read the ISR's value once
      // Adding balls: spawn each new one, stacked SPAWN_GAP px apart above
      // the screen so they fall in one after another
      for (int i = num_balls; i < target; i++) {
        spawnBall(&balls[i]) ;
        balls[i].y = int2fix15(-(i - num_balls) * SPAWN_GAP) ;
      }
      // Removing balls: the extras just stop being updated/drawn
      num_balls = target ;

      // === GALTON BOARD ===
      for (int i = 0; i < NUM_PEGS; i++) {
        fillCircle(fix2int15(peg_x[i]), fix2int15(peg_y[i]), PEG_RADIUS, WHITE) ;
      }
      for (int i = 0; i < num_balls; i++) {
        updateBall(&balls[i]) ;
      }
      // histogram first, so balls falling through it are drawn on top
      drawHistogram() ;
      for (int i = 0; i < num_balls; i++) {
        fillCircle(fix2int15(balls[i].x), fix2int15(balls[i].y), BALL_RADIUS, color) ;
      }

      // === TEXT ===
      sprintf(text_str, "Balls:  %d", num_balls) ;
      drawTextVGA437(10, 10, text_str, WHITE, BLACK) ;
      sprintf(text_str, "Fallen: %d", total_fallen) ;
      drawTextVGA437(10, 30, text_str, WHITE, BLACK) ;
      sprintf(text_str, "Time:   %d s", (int)(time_us_64() / 1000000)) ;
      drawTextVGA437(10, 50, text_str, WHITE, BLACK) ;

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
  set_sys_clock_khz(150000, true) ;
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

  // Initialize the semaphore
  // Arguments: pointer to sem, initial count, max count
  sem_init(&draw_semaphore, 0, 1) ;

  // start core 1 
  multicore_reset_core1();
  multicore_launch_core1(&core1_main);

  // add threads
  pt_add_thread(protothread_serial);
  pt_add_thread(protothread_anim);

  // start scheduler
  pt_schedule_start ;
} 
