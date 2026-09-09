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
   3.3v (pin 36) -> VCC on DAC 
   GND (pin 3)  -> GND on DAC 
 */

#include <stdio.h>
#include <math.h>
#include <string.h>
#include "stdlib.h"
#include "pico/stdlib.h"
#include "hardware/timer.h"
#include "hardware/irq.h"
#include "hardware/spi.h"
#include "hardware/adc.h"
#include "hardware/gpio.h"
#include "pt_cornell_rp2040_v1_4.h"


// Low-level alarm infrastructure we'll be using
#define ALARM_NUM 0
#define ALARM_IRQ timer_hardware_alarm_get_irq_num(timer_hw, ALARM_NUM)

//DDS parameters
#define two32 4294967296.0 // 2^32 
#define Fs 50000
#define DELAY 20 // 1/Fs (in microseconds)
// the DDS units:
volatile float adc_val;
volatile unsigned int phase_accum_main;
// volatile unsigned int phase_incr_main = (800*two32)/Fs ;
volatile unsigned int phase_incr_main;

// SPI data
uint16_t DAC_data ; // output value

//DAC parameters
// A-channel, 1x, active
#define DAC_config_chan_A 0b0011000000000000
// B-channel, 1x, active
#define DAC_config_chan_B 0b1011000000000000

//SPI configurations
#define PIN_MISO 4
#define PIN_CS   13
#define PIN_SCK  14
#define PIN_MOSI 15
#define SPI_PORT spi1
#define ADC_PIN 26
#define ADC_MUX 0

// Keypad config
#define BASE_KEYPAD_PIN 6
#define KEYROWS         4
#define NUMKEYS         12

unsigned int keycodes[NUMKEYS] = {      0x57, 0x6E, 0x5E, 0x3E, 0x6D,
                                        0x5D, 0x3D, 0x6B, 0x5B, 0x3B,
                                        0x67, 0x37} ;
unsigned int scancodes[KEYROWS] = {   0xE, 0xD, 0xB, 0x7} ;
unsigned int button = 0x70 ;

char keytext[40];
int prev_key = 0;

typedef enum {
    NOT_PRESSED,
    MAYBE_PRESSED,
    PRESSED,
    MAYBE_NOT_PRESSED
} debounce_state_t;

static debounce_state_t key_state = NOT_PRESSED;
static int possible = -1;
static int keypad_flag = 0;

// Recording
static int record_flag = 0;
static int record_key[10] = {-1, -1, -1, -1, -1, -1, -1, -1, -1, -1};
static int record_idx = 0;
static float record_sound[9][1000] = {0.0};  // 100 freq for 10 sec recording
// static int record_sound_idx[10] = 0;    // sound end idx for each recording

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
    DAC_data = (DAC_config_chan_B | ((sin_table[phase_accum_main>>24] + 2048) & 0xffff))  ;

    // Perform an SPI transaction
    spi_write16_blocking(SPI_PORT, &DAC_data, 1) ;

    // De-assert the GPIO when we leave the interrupt
    gpio_put(ISR_GPIO, 0) ;

}

// ADC potentiometer thread
static PT_THREAD (protothread_FoutInput(struct pt *pt))
{
    PT_BEGIN(pt);

      while(1) {
        // Read the ADC
        adc_val = adc_read() * 2.5;     // normalize to range 0 - 10k

        // Print the value
        if (keypad_flag) {
        //   printf("ADC value: %f\n", adc_val) ;
          phase_incr_main = ((int)adc_val*two32)/Fs  ; // update the phase increment
        }
        else {
          phase_incr_main = 0;
        }

        // Yield
        PT_YIELD_usec(10000) ; // adjusts ADC sample rate
      } // END WHILE(1)
      PT_END(pt);
}

// Debounce FSM helper function
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
                printf("\nKey pressed: %d", possible);
            } else {
                key_state = NOT_PRESSED;
            }
            break;

        case PRESSED:
            if (keycode != possible) {  // key detected changed
                key_state = MAYBE_NOT_PRESSED;
            }
            break;

        case MAYBE_NOT_PRESSED:
            if (keycode == possible) { 
                key_state = PRESSED;  
            } else { // key release detected
                printf("\nKey released: %d\n", possible);

                if (possible == 0) {
                    keypad_flag = ~keypad_flag;
                    printf("play mode toggled\n");
                }
                if (possible == 10) {
                    record_flag = ~record_flag;
                    printf("record mode toggled\n");
                }

                key_state = NOT_PRESSED;
            }
            break;
    }
}

// Keypad thread
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

        
        if (record_flag == 1 && key_state == PRESSED) {  // start recording
            record_idx = i;  // record record key
            printf("Record key: %d\n", i);
        }

        PT_YIELD_usec(30000) ;
    }
    PT_END(pt) ;
}

// Record thread
// static PT_THREAD (protothread_record(struct pt *pt))
// {
//     PT_BEGIN(pt);

//       while(1) {
//        // TODO: code for freq recording
        

//         // Yield
//         PT_YIELD_usec(100000) ;
//       } // END WHILE(1)
//       PT_END(pt);
// }

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

    // Setup the ISR-timing GPIO
    gpio_init(ISR_GPIO) ;
    gpio_set_dir(ISR_GPIO, GPIO_OUT);
    gpio_put(ISR_GPIO, 0) ;

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
    pt_add_thread(protothread_FoutInput);
    pt_add_thread(protothread_key_debounce);
    
    // === initalize the scheduler ===============
    pt_schedule_start ;

    // Nothing happening here
    while(1){
    }
    return 0;
}