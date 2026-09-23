
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
  need to make sequence detector to detect clockwise and counterclockwise rotation
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
// === ROTARY ENCODER INTERFACE (added w/ Claude Code assistance)
// Prompt: "Read the rotary encoder page and write a software interface
// to the rotary encoder. You should display a number on the VGA display
// that increments when you rotate the encoder clockwise, and decrements
// when you rotate it counterclockwise."
//
// v2 (Claude Code assisted): the single-edge version above double-counted
// every click, because one physical click makes A itself edge twice (once
// as its contact pad engages, once as it releases -- see the encoder page's
// state diagram). Fix: interrupt on BOTH A and B edges, track which of the
// 4 possible (A,B) states we're in, and only bump rot_counter once we've
// walked all the way through one full click's worth of states and landed
// back at rest. This also makes contact bounce self-cancel, since a bounce
// steps forward then immediately back (+1 then -1), never reaching the
// "hey, that's a full click" threshold below.
// =====================================================================
#define ROT_A 12
#define ROT_B 11
volatile int rot_counter = 0;
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
    if (rot_accum >= 4)       rot_counter++ ;  // completed one CW click
    else if (rot_accum <= -4) rot_counter-- ;  // completed one CCW click
    rot_accum = 0 ;                    // discard partial turns / bounce
  }
}
// === END ROTARY ENCODER ISR ===========================================

// the color of the boid
char color = WHITE ;

// Boid on core 0
fix15 boid0_x ;
fix15 boid0_y ;
fix15 boid0_vx ;
fix15 boid0_vy ;

// Boid on core 1
fix15 boid1_x ;
fix15 boid1_y ;
fix15 boid1_vx ;
fix15 boid1_vy ;

// Create a semaphore
semaphore_t draw_semaphore ;

// Create a boid
void spawnBoid(fix15* x, fix15* y, fix15* vx, fix15* vy, int direction)
{
  // Start in center of screen
  *x = int2fix15(320) ;
  *y = int2fix15(240) ;
  // Choose left or right
  if (direction) *vx = int2fix15(3) ;
  else *vx = int2fix15(-3) ;
  // Moving down
  *vy = int2fix15(1) ;
}

// Draw the boundaries
void drawArena() {
  drawVLine(100, 100, 280, WHITE) ;
  drawVLine(540, 100, 280, WHITE) ;
  drawHLine(100, 100, 440, WHITE) ;
  drawHLine(100, 380, 440, WHITE) ;
}

// Detect wallstrikes, update velocity and position
void wallsAndEdges(fix15* x, fix15* y, fix15* vx, fix15* vy)
{
  // Reverse direction if we've hit a wall
  if (hitTop(*y)) {
    *vy = (-*vy) ;
    *y  = (*y + int2fix15(5)) ;
  }
  if (hitBottom(*y)) {
    *vy = (-*vy) ;
    *y  = (*y - int2fix15(5)) ;
  } 
  if (hitRight(*x)) {
    *vx = (-*vx) ;
    *x  = (*x - int2fix15(5)) ;
  }
  if (hitLeft(*x)) {
    *vx = (-*vx) ;
    *x  = (*x + int2fix15(5)) ;
  } 

  // Update position using velocity
  *x = *x + *vx ;
  *y = *y + *vy ;
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

    // Spawn a boid
    spawnBoid(&boid0_x, &boid0_y, &boid0_vx, &boid0_vy, 0);

    static char rot_str[32] ;

    while(1) {
      // Wait for the signal that the buffer's changed
      PT_YIELD_UNTIL(pt, draw_start_signal()) ;
      // Clear the buffer
      clearLowFrame(0, BLACK);
      // Signal core 1 that it can start drawing
      PT_SEM_SDK_SIGNAL(pt, &draw_semaphore) ;
      // update boid's position and velocity
      wallsAndEdges(&boid0_x, &boid0_y, &boid0_vx, &boid0_vy) ;
      // draw the boid at its new position
      fillCircle(fix2int15(boid0_x), fix2int15(boid0_y), 15, color); 
      // draw the boundaries
      drawArena() ;

      // === ROTARY ENCODER: display rot_counter (Claude Code assisted) ===
      sprintf(rot_str, "Count: %d", rot_counter) ;
      drawTextVGA437(50, 50, rot_str, WHITE, BLACK);
      // === END ROTARY ENCODER DISPLAY ===================================

     // NEVER exit while
    } // END WHILE(1)
  PT_END(pt);
} // animation thread


// Animation on core 1
static PT_THREAD (protothread_anim1(struct pt *pt))
{
    // Mark beginning of thread
    PT_BEGIN(pt);

    // Spawn a boid
    spawnBoid(&boid1_x, &boid1_y, &boid1_vx, &boid1_vy, 1);

    while(1) {
      // Wait for the signal from core 0
      PT_SEM_SDK_WAIT(pt, &draw_semaphore) ;
      // update boid's position and velocity
      wallsAndEdges(&boid1_x, &boid1_y, &boid1_vx, &boid1_vy) ;
      // draw the boid at its new position
      fillCircle(fix2int15(boid1_x), fix2int15(boid1_y), 15, color); 
     // NEVER exit while
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

  // === ROTARY ENCODER: GPIO + interrupt setup (Claude Code assisted) ===
  // Pull-ups needed because A/B float when not touching a contact pad.
  // v2: interrupt on BOTH pins now, since rot_ISR needs to see every step
  // of the 4-state sequence, not just A's edges.
  gpio_init(ROT_A);
  gpio_init(ROT_B);
  gpio_set_dir(ROT_A, GPIO_IN);
  gpio_set_dir(ROT_B, GPIO_IN);
  gpio_pull_up(ROT_A);
  gpio_pull_up(ROT_B);
  // seed rot_prev_state with the real, current pin reading (assumes we boot
  // at rest -- fine since the encoder detents there and holds until turned)
  rot_prev_state = (gpio_get(ROT_A) << 1) | gpio_get(ROT_B) ;
  gpio_set_irq_enabled_with_callback(ROT_A, GPIO_IRQ_EDGE_RISE | GPIO_IRQ_EDGE_FALL, true, &rot_ISR);
  gpio_set_irq_enabled(ROT_B, GPIO_IRQ_EDGE_RISE | GPIO_IRQ_EDGE_FALL, true);
  // === END ROTARY ENCODER SETUP =========================================

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
