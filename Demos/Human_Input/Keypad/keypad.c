/**
 * Hunter Adams (vha3@cornell.edu)
 * 
 * Keypad Demo w/ Debouncing FSM
 * 
 * KEYPAD CONNECTIONS
 *  - GPIO 9   -->  330 ohms  --> Pin 1 (button row 1)
 *  - GPIO 10  -->  330 ohms  --> Pin 2 (button row 2)
 *  - GPIO 11  -->  330 ohms  --> Pin 3 (button row 3)
 *  - GPIO 12  -->  330 ohms  --> Pin 4 (button row 4)
 *  - GPIO 13  -->     Pin 5 (button col 1)
 *  - GPIO 14  -->     Pin 6 (button col 2)
 *  - GPIO 15  -->     Pin 7 (button col 3)
 * 
 * SERIAL CONNECTIONS
 *  - GPIO 0        -->     UART RX (white)
 *  - GPIO 1        -->     UART TX (green)
 *  - RP2040 GND    -->     UART GND
 */

// ---- Original includes (Hunter Adams / user) ----
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>

#include "pico/stdlib.h"
#include "pico/multicore.h"

#include "hardware/pio.h"
#include "hardware/dma.h"
#include "hardware/sync.h"
#include "hardware/spi.h"
#include "hardware/clocks.h"

#include "pt_cornell_rp2040_v1_4.h"


// ---- Original keypad pin configurations (Hunter Adams / user) ----
#define BASE_KEYPAD_PIN 6
#define KEYROWS         4
#define NUMKEYS         12

#define LED             25

unsigned int keycodes[NUMKEYS] = {      0x57, 0x6E, 0x5E, 0x3E, 0x6D,
                                        0x5D, 0x3D, 0x6B, 0x5B, 0x3B,
                                        0x67, 0x37} ;
unsigned int scancodes[KEYROWS] = {   0xE, 0xD, 0xB, 0x7} ;
unsigned int button = 0x70 ;

char keytext[40];
int prev_key = 0;

/* ============================================================
 * BEGIN CLAUDE-GENERATED CODE
 *
 * Originating user prompt (paraphrased from chat history):
 *   "I'd like to implement [a debouncing state machine] into
 *   this code" -- referencing a 4-state FSM (Not pressed / Maybe
 *   pressed / Pressed / Maybe not pressed) described in the lab
 *   handout (Fig. 3), where a "possible" keycode is stored and
 *   confirmed across successive scans before a press event fires.
 *
 * The states, transitions, and tick function below are new code
 * written by Claude (Anthropic) implementing that FSM in C.
 * ============================================================ */
typedef enum {
    NOT_PRESSED,
    MAYBE_PRESSED,
    PRESSED,
    MAYBE_NOT_PRESSED
} debounce_state_t;

static debounce_state_t key_state = NOT_PRESSED;
static int possible = -1;   // candidate keycode being confirmed

// Called once per scan with the raw keycode from this pass (-1 = nothing valid)
void debounce_fsm_tick(int keycode) {
    switch (key_state) {

        case NOT_PRESSED:
            if (keycode != -1) {
                possible = keycode;
                key_state = MAYBE_PRESSED;
            }
            break;

        case MAYBE_PRESSED:
            if (keycode == possible) {
                key_state = PRESSED;
                // ---- single "key pressed" event fires here ----
                printf("\nKey pressed: %d", possible);
                // e.g. trigger a note: set phase_incr_main from possible, etc.
            } else {
                key_state = NOT_PRESSED;
            }
            break;

        case PRESSED:
            if (keycode != possible) {
                key_state = MAYBE_NOT_PRESSED;
            }
            break;

        case MAYBE_NOT_PRESSED:
            if (keycode == possible) {
                key_state = PRESSED;       // was just a blip, still held
            } else {
                key_state = NOT_PRESSED;
                // ---- optional "key released" event ----
                printf("\nKey released: %d", possible);
            }
            break;
    }
}
/* ============================================================
 * END CLAUDE-GENERATED CODE
 * ============================================================ */

// This thread runs on core 0
// ---- Original thread structure and keypad scan loop (Hunter Adams / user) ----
static PT_THREAD (protothread_core_0(struct pt *pt))
{
    PT_BEGIN(pt) ;

    static int i ;
    static uint32_t keypad ;

    while(1) {

        gpio_put(LED, !gpio_get(LED)) ;

        // Scan the keypad!  (original scan logic, unmodified)
        for (i=0; i<KEYROWS; i++) {
            gpio_put_masked((0xF << BASE_KEYPAD_PIN),
                            (scancodes[i] << BASE_KEYPAD_PIN)) ;
            sleep_us(1) ;
            keypad = ((gpio_get_all() >> BASE_KEYPAD_PIN) & 0x7F) ;
            if ((~keypad) & button) break ;
        }
        if ((~keypad) & button) {
            for (i=0; i<NUMKEYS; i++) {
                if (keypad == keycodes[i]) break ;
            }
            if (i==NUMKEYS) (i = -1) ;
        }
        else (i=-1) ;

        // ---- CLAUDE-GENERATED LINE ----
        // Prompt: "please make comments in the code accordingly for
        // where you generated code" (follow-up asking to wire the FSM
        // into this loop). Replaces the original `printf("\n%d", i);`
        // with a call into the debounce FSM, so a press registers as
        // one clean event instead of printing every raw scan result.
        debounce_fsm_tick(i);

        PT_YIELD_usec(30000) ;
    }
    PT_END(pt) ;
}


// ---- Original main(), unmodified (Hunter Adams / user) ----
int main() {

    set_sys_clock_khz(150000, true) ;
    stdio_init_all();

    gpio_init(LED) ;
    gpio_set_dir(LED, GPIO_OUT) ;
    gpio_put(LED, 0) ;

    gpio_init_mask((0x7F << BASE_KEYPAD_PIN)) ;
    gpio_set_dir((BASE_KEYPAD_PIN+4), GPIO_IN);
    gpio_set_dir((BASE_KEYPAD_PIN+5), GPIO_IN);
    gpio_set_dir((BASE_KEYPAD_PIN+6), GPIO_IN);
    gpio_set_dir_out_masked((0xF << BASE_KEYPAD_PIN)) ;
    gpio_put_masked((0xF << BASE_KEYPAD_PIN), (0xF << BASE_KEYPAD_PIN)) ;
    gpio_pull_up((BASE_KEYPAD_PIN+4)) ;
    gpio_pull_up((BASE_KEYPAD_PIN+5)) ;
    gpio_pull_up((BASE_KEYPAD_PIN+6)) ;

    pt_add_thread(protothread_core_0) ;
    pt_schedule_start ;

}