/**
 * V. Hunter Adams
 * DDS of sine wave on MCP4822 DAC w/ ISR
 * 
 * Modified example code from Raspberry Pi
 * Copyright (c) 2020 Raspberry Pi (Trading) Ltd.
 *
 * SPDX-License-Identifier: BSD-3-Clause
 *
   GPIO 5 (pin 7) Chip select
   GPIO 6 (pin 9) SCK/spi0_sclk
   GPIO 7 (pin 10) MOSI/spi0_tx
   GPIO 2 (pin 4) GPIO output for timing ISR
   GPIO 3 (pin 5) !LDAC
   3.3v (pin 36) -> VCC on DAC 
   GND (pin 3)  -> GND on DAC 
 */

// ============== include libraries ==========================
#include <stdio.h>                      // used for printf
#include <math.h>                       // used for the sine func
#include <string.h>                     // string stuff
#include "stdlib.h"                     // always good to have
#include "pico/stdlib.h"                // Pico SDK added for GPIO and timing
#include "hardware/timer.h"             //ISR for DDS
#include "hardware/irq.h"               // IRQ
#include "hardware/spi.h"               // SPI stuff to send to DAC
#include "hardware/adc.h"               // ADC stuff to read from potentiometer
#include "hardware/gpio.h"              // GPIO stuff to read from keypad
#include "pt_cornell_rp2040_v1_4.h"     // pt stands for "protothreads"
// ==============end libraries ==========================


// Low-level alarm infrastructure we'll be using
// ISR = Interrupt Service Routine
#define ALARM_NUM 0
#define ALARM_IRQ timer_hardware_alarm_get_irq_num(timer_hw, ALARM_NUM)

//DDS parameters
#define two32 4294967296.0  // 2^32 as a constant for phase increment calculations
#define Fs 50000            // Sampling frequency (Hz)
#define DELAY 20 // 1/Fs (in microseconds)
// the DDS units:
volatile float adc_val;     // ADC value taken in from slide potentiometer
volatile float freq_val;    // desired frequencye (Hz) from slide potentioemter
volatile float vol_val;     // volume scale facotr from slide after toggling to volume control mode
// 32 bit accumulator (Note: overflows --> wrap back to 0)
volatile unsigned int phase_accum_main;
// freq*two32/Fs = phase increment assigned later
volatile unsigned int phase_incr_main;

// SPI data
uint16_t DAC_data ; // output value

//DAC parameters
// A-channel, 1x, active
#define DAC_config_chan_A 0b0011000000000000
// B-channel, 1x, active
#define DAC_config_chan_B 0b1011000000000000

//SPI configurations (GPIO pins)
#define PIN_MISO 4
#define LDAC     5
#define PIN_CS   13
#define PIN_SCK  14
#define PIN_MOSI 15
#define SPI_PORT spi1 // set as SPI channel 1
#define ADC_PIN 26
#define ADC_MUX 0

// Volumn toggle switch GPIO
#define V_SWITCH_1 16           // in this state: Volume
#define V_SWITCH_2 17           // in this state: Frequency

// Keypad config
#define BASE_KEYPAD_PIN 6   // base pin to add offset through GPIO 6, 7, 8, 9, 10, 11, 12
#define KEYROWS         4   // number of rows in the keypad
#define NUMKEYS         12  // number of keys in the keypad

// Record config
#define record_length   1000      // num samples stored for each recording
#define record_freq     10000     // recording freq (slow)
#define playback_freq   1000      // playback freq (fast)

// Compose config
#define compose_length  100       // num sound bites in one composition

// Keypad legend:
// 0x6E = 1 ; // 0x5E = 2 ; // 0x3E = 3
// 0x6D = 4 ; // 0x5D = 5 ; // 0x3D = 6
// 0x6B = 7 ; // 0x5B = 8 ; // 0x3B = 9
// 0x67 = * ; // 0x57 = 0 ; // 0x37 = #
unsigned int keycodes[NUMKEYS] = {      0x57, 0x6E, 0x5E, 0x3E, 0x6D,
                                        0x5D, 0x3D, 0x6B, 0x5B, 0x3B,
                                        0x67, 0x37} ;
unsigned int scancodes[KEYROWS] = {   0xE, 0xD, 0xB, 0x7} ;
unsigned int button = 0x70 ;

// what's this for? idk used to debug keypad probs
char keytext[40];
int prev_key = 0;

// FSM states for keypad debounce
typedef enum {
    NOT_PRESSED,        // Idle... key is not pressed
    MAYBE_PRESSED,      // Key is pressed, but we need to check if it's stable
    PRESSED,            // Key is pressed and stable
    MAYBE_NOT_PRESSED   // Key looked like it was released, but we need to check if it's stable
} debounce_state_t;

// Playback and recrding flags
static debounce_state_t key_state = NOT_PRESSED;   // current state of FSM
static int possible = -1;                          // current keycode index
static int keypad_flag = 1;                        // flag to indicate if a key is pressed

static unsigned int record_flag = 0;                // flag to indicate if we are recording
// static int record_key[10] = {-1, -1, -1, -1, -1, -1, -1, -1, -1, -1};
static int record_idx = 0;                             // recording key/sound index
static int recording_key = -1;                         // flag to indicate which key is being recorded
static float record_sound[10][record_length] = {0.0};  // 100 freq for 10 sec recording
static int record_sound_idx[10] = {0};                 // record end idx for each recording

static int playback_flag = 0;   // flag to indicate if we are playing bakc a recorded sound
static int playback_key = -1;   // flag to indicate which key is being played back

static unsigned int compose_flag = 0;
static int compose_key_seq[compose_length] = {0};   
static int compose_key_seq_idx = 0; 
static int compose_playback_flag = 0;

static float volume_scale = 1.0;

//GPIO for timing the ISR
#define ISR_GPIO 2

// DDS sine table
#define sine_table_size 256
volatile int sin_table[sine_table_size] ;

// Alarm ISR
static void alarm_irq(void) {

    // Assert a GPIO when we enter the interrupt
    gpio_put(ISR_GPIO, 1) ;

    // Clear the alarm irq
    hw_clear_bits(&timer_hw->intr, 1u << ALARM_NUM);

    // Reset the alarm register
    timer_hw->alarm[ALARM_NUM] = timer_hw->timerawl + DELAY ;

    // DDS phase and sine table lookup
    phase_accum_main += phase_incr_main  ;
    DAC_data = (DAC_config_chan_B | (((uint16_t)(sin_table[phase_accum_main>>24]*vol_val) + 2048) & 0xffff))  ;

    // Perform an SPI transaction
    spi_write16_blocking(SPI_PORT, &DAC_data, 1) ;

    // De-assert the GPIO when we leave the interrupt
    gpio_put(ISR_GPIO, 0) ;

}

// ADC Potentiometer thread
static PT_THREAD (protothread_FoutInput(struct pt *pt))
{
    PT_BEGIN(pt);

    static unsigned int i;
    static unsigned int k;

    while(1) {

        adc_val = adc_read();
        if(gpio_get(V_SWITCH_1) && !gpio_get(V_SWITCH_2)) {
            vol_val = adc_val / 4096; // normalize to range 0.0 - 1.0
            // printf("adc_out: %d, vol scale: %f\n", adc_val, vol_val);
        }
        else if (gpio_get(V_SWITCH_2) && !gpio_get(V_SWITCH_1)){
            freq_val = adc_val * 2.5;     // normalize to range 0 - 10k
            // printf("adc_out: %d, freq scale: %f\n", adc_val, freq_val);
        }

        // Print the value
        if (keypad_flag || record_flag) {      // key 0 pressed to play current sound controlled by potentiometer
            phase_incr_main = ((int)freq_val*two32)/Fs  ; // update the phase increment
        }
        else if (!compose_playback_flag && playback_flag && playback_key != -1) {    // play recorded sound with corresponding key 
            for (i = 0; i < record_sound_idx[playback_key]; i++) {
                phase_incr_main = ((int)record_sound[playback_key][i]*two32)/Fs;
                // printf("Playing back on key: %d, i: %d, freq: %f, len:%d\n", playback_key, i, record_sound[playback_key][i], record_sound_idx[playback_key]);
                PT_YIELD_usec(playback_freq);
            }
            if (i >= record_sound_idx[playback_key]) {
                // printf("Playback finished key %d, i=%d, len=%d\n", playback_key, i, record_sound_idx[playback_key]);
                playback_flag = 0;
                playback_key = -1;
            }
        } 
        else if (compose_playback_flag) {   // playback for song compose using record keys
            // printf("Compose playback start\n");
            for(k = 0; k < compose_key_seq_idx; k++) {
                // printf("Compose playing back on key: %d, len: %d\n", compose_key_seq[k], record_sound_idx[compose_key_seq[k]]);
                for (i = 0; i < record_sound_idx[compose_key_seq[k]]; i++) {
                    phase_incr_main = ((int)record_sound[compose_key_seq[k]][i]*two32)/Fs;
                    PT_YIELD_usec(playback_freq);
                }
            }
            compose_playback_flag = 0;
            // printf("Compose playing finished\n");
        }
        else {
          phase_incr_main = 0;
        }

        // Yield
        PT_YIELD_usec(playback_freq) ;
      } // END WHILE(1)
      PT_END(pt);
}

void debounce_fsm_tick(int keycode) {
    switch (key_state) {
        case NOT_PRESSED:
            if (keycode != -1) {  // button detected first time
                possible = keycode;
                key_state = MAYBE_PRESSED;
            }
            break;

        case MAYBE_PRESSED:
            if (keycode == possible) {  // key press stable by current scan matched with first scan
                key_state = PRESSED;
                // printf("\nKey pressed: %d", possible);
            } else {
                key_state = NOT_PRESSED;
            }
            break;

        case PRESSED:  
            if (keycode != possible) {  // key detected changed
                key_state = MAYBE_NOT_PRESSED;
            }
            if (possible != 10 && possible != 11 && possible != 0) {
                record_idx = possible;
            }
            break;

        case MAYBE_NOT_PRESSED:
            if (keycode == possible) {  
                key_state = PRESSED;       
            } else {  // key release detected
                // printf("\nKey released: %d\n", possible);
                if (possible == 0) {
                    compose_flag = 0;   // reset compose mode
                    record_flag = 0;    // reset record mode
                    keypad_flag = !keypad_flag; // toggle play mode
                    // printf("play mode toggled, keypad_flag: %d, record_flag: %d, compose_flag: %d, record_clear: %d\n", keypad_flag, record_flag, compose_flag, recording_key);
                }
                else if (possible == 10) {
                    compose_flag = 0;       // reset compose mode
                    keypad_flag = 0;        // reset play mode
                    record_flag = !record_flag; // toggle record mode
                    recording_key = -1;     // reset recording key
                    // printf("record mode toggled, keypad_flag: %d, record_flag: %d, compose_flag: %d, record_clear: %d\n", keypad_flag, record_flag, compose_flag, recording_key);
                }
                else if (record_flag && possible != 0 && possible != 11) {
                    record_flag = 0;        // end recording
                    recording_key = -1;     // reset recording key
                    // printf("Record end, keypad_flag: %d, record_flag: %d, compose_flag: %d, record_clear: %d\n", keypad_flag, record_flag, compose_flag, recording_key);
                } 
                else if (!compose_flag && !record_flag && possible != 10 && possible != 0 && possible != 11 && possible != -1) {
                    playback_flag = 1;      // start playback of recordd sound
                    playback_key = possible;    // set playback key to the key presesd
                    // printf("Playback pressed, key: %d\n", possible);
                }
                else if (possible == 11) {
                    record_flag = 0;
                    keypad_flag = 0;
                    compose_flag = !compose_flag;
                    // printf("Compose mode toggled, compose_flag: %d\n", compose_flag);
                    if (!compose_playback_flag && compose_key_seq_idx != 0) {
                        compose_playback_flag = 1;
                        // printf("Compose finished, sequence (%d keys): ", compose_key_seq_idx);
                        // for (int j = 0; j < compose_key_seq_idx; j++) {
                            // printf("%d ", compose_key_seq[j]);
                        // }
                        // printf("\nPlayback start, keypad_flag: %d, record_flag: %d, compose_flag: %d, record_clear: %d\n", keypad_flag, record_flag, compose_flag, recording_key);
                    }
                    else {
                        compose_key_seq_idx = 0;
                        // printf("Compose start");
                    }
                } else if(compose_flag && possible != 11 && possible != 0 && possible != 10) {
                    if (compose_key_seq_idx >= compose_length) {
                        compose_flag = !compose_flag;
                        // printf("Compose sequence max length reached: %d\n", compose_length);
                    }
                    else {
                        compose_key_seq[compose_key_seq_idx] = possible;
                        compose_key_seq_idx++;
                        // printf("Compose key sequence added: %d\n", possible);
                    }
                }

                key_state = NOT_PRESSED;
            }
            break;
    }
}

static PT_THREAD (protothread_key_debounce(struct pt *pt))
{
    PT_BEGIN(pt) ;

    static int i ;
    static uint32_t keypad ;

    while(1) {

        // Scan the keypad! 
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

        //FSM update here
        debounce_fsm_tick(i);

        PT_YIELD_usec(30000) ;
    }
    PT_END(pt) ;
}

// Record thread
static PT_THREAD (protothread_record(struct pt *pt)){
   PT_BEGIN(pt);

   static int k;
   
   while(1) { // record sound for the key pressed
    if (record_flag && key_state == PRESSED && possible != 10 && possible != 0 && possible != 11 && possible != -1) {
        k = possible;

        if (recording_key != k) {      
            recording_key = k;          // new key to record on 
            record_sound_idx[k] = 0;    // go back to first index of this keys recording
        }
        if (record_sound_idx[record_idx] >= record_length) {  // record max length reached 
            // printf("Record key: %d Max length recorded, end record\n", record_idx);
            record_flag = 0;  //end reocridng
        }
        else {
            record_sound[record_idx][record_sound_idx[record_idx]] = freq_val;   // record freq continuously
            record_sound_idx[record_idx]++;                                      // move on to next recording index
            // printf("Record key: %d; current sound freq: %f\n", record_idx, freq_val);
        }
    }
    PT_YIELD_usec(record_freq);
   }
   PT_END(pt);
}

int main() {
    // Initialize stdio
    stdio_init_all();
    printf("Hello, DAC!\n");

    // Initialize SPI channel (channel, baud rate set to 20MHz)
    spi_init(SPI_PORT, 20000000) ;
    // Format (channel, data bits per transfer, polarity, phase, order)
    spi_set_format(SPI_PORT, 16, 0, 0, 0);

    // Setup the ADC
    adc_init() ;
    adc_gpio_init(ADC_PIN) ;
    adc_select_input(ADC_MUX) ;

    // Setup volumn switch GPIO
    gpio_init(V_SWITCH_1);
    gpio_init(V_SWITCH_2);
    gpio_set_dir(V_SWITCH_1, GPIO_IN);
    gpio_set_dir(V_SWITCH_2, GPIO_IN);
    gpio_pull_up(V_SWITCH_1);
    gpio_pull_up(V_SWITCH_2); 

    // Setup the ISR-timing GPIO
    gpio_init(ISR_GPIO) ;
    gpio_set_dir(ISR_GPIO, GPIO_OUT);
    gpio_put(ISR_GPIO, 0) ;

    // MAP LDAC to GPIO
    gpio_init(LDAC);
    gpio_set_dir(LDAC, GPIO_OUT);
    gpio_put(LDAC, 0);

    // Map SPI signals to GPIO ports
    gpio_set_function(PIN_MISO, GPIO_FUNC_SPI);
    gpio_set_function(PIN_SCK, GPIO_FUNC_SPI);
    gpio_set_function(PIN_MOSI, GPIO_FUNC_SPI);
    gpio_set_function(PIN_CS, GPIO_FUNC_SPI) ;

    // Keypad setup
    gpio_init_mask((0x7F << BASE_KEYPAD_PIN)) ;
    gpio_set_dir((BASE_KEYPAD_PIN+4), GPIO_IN);
    gpio_set_dir((BASE_KEYPAD_PIN+5), GPIO_IN);
    gpio_set_dir((BASE_KEYPAD_PIN+6), GPIO_IN);
    gpio_set_dir_out_masked((0xF << BASE_KEYPAD_PIN)) ;
    gpio_put_masked((0xF << BASE_KEYPAD_PIN), (0xF << BASE_KEYPAD_PIN)) ;
    gpio_pull_up((BASE_KEYPAD_PIN+4)) ;
    gpio_pull_up((BASE_KEYPAD_PIN+5)) ;
    gpio_pull_up((BASE_KEYPAD_PIN+6)) ;

    // === build the sine lookup table =======
   	// scaled to produce values between 0 and 4096
    int ii;
    for (ii = 0; ii < sine_table_size; ii++){
        
         sin_table[ii] = (int)(2047*sin((float)ii*6.283/(float)sine_table_size));
    }

    // Enable the interrupt for the alarm (we're using Alarm 0)
    hw_set_bits(&timer_hw->inte, 1u << ALARM_NUM) ;
    // Associate an interrupt handler with the ALARM_IRQ
    irq_set_exclusive_handler(ALARM_IRQ, alarm_irq) ;
    // Enable the alarm interrupt
    irq_set_enabled(ALARM_IRQ, true) ;
    // Write the lower 32 bits of the target time to the alarm register, arming it.
    timer_hw->alarm[ALARM_NUM] = timer_hw->timerawl + DELAY ;

    // === config threads ========================
    pt_add_thread(protothread_FoutInput);       // ADC/freq/sound out thread
    pt_add_thread(protothread_key_debounce);    // keypad debounce FSM thread
    pt_add_thread(protothread_record);          // recording thread
    
    // === initalize the scheduler ===============
    pt_schedule_start ;

    // Nothing happening here
    // unreachable 
    while(1){
    }
    return 0;
}