/**
 * V. Hunter Adams (vha3@cornell.edu)
 * 
 * This demonstration utilizes the MPU6050.
 * It gathers raw accelerometer/gyro measurements, scales
 * them, and plots them to the VGA display. The top plot
 * shows gyro measurements, bottom plot shows accelerometer
 * measurements.
 * 
 * HARDWARE CONNECTIONS
 *  - GPIO 16 ---> VGA Hsync
 *  - GPIO 17 ---> VGA Vsync
 *  - GPIO 18 ---> 470 ohm resistor ---> VGA Green
 *  - GPIO 19 ---> 330 ohm resistor ---> VGA Green
 *  - GPIO 20 ---> 330 ohm resistor ---> VGA Blue
 *  - GPIO 21 ---> 330 ohm resistor ---> VGA Red
 *  - RP2040 GND ---> VGA GND
 *  - GPIO 8 ---> MPU6050 SDA
 *  - GPIO 9 ---> MPU6050 SCL
 *  - 3.3v ---> MPU6050 VCC
 *  - RP2040 GND ---> MPU6050 GND
 *  - GPIO 4 ---> PWM_OUT
 */


// Include standard libraries
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
// Include PICO libraries
#include "pico/stdlib.h"
#include "pico/multicore.h"
// Include hardware libraries
#include "hardware/pwm.h"
#include "hardware/dma.h"
#include "hardware/irq.h"
#include "hardware/adc.h"
#include "hardware/pio.h"
#include "hardware/i2c.h"
#include "hardware/clocks.h"
#include "hardware/sync.h"
// Include custom libraries
#include "VGA/vga16_graphics_v3.h"
#include "mpu6050.h"
#include "pt_cornell_rp2040_v1_4.h"

// We will start drawing at column 81
#define LEFT_EDGE 81 

// Rescale the measurements for display
#define OLD_RANGE 500.  // (+/- 250)
#define NEW_RANGE 150.  // (looks nice on VGA)
#define OLD_MIN -250. 
#define OLD_MAX 250. 
#define ACCEL_SCALE 120.0

// Angle plot range (degrees)
#define ANGLE_MIN 0
#define ANGLE_RANGE 180
#define RAD2DEG 57.2957795f

// Place the plots
#define TOP_PLOT_BOTTOM 230
#define BOTTOM_PLOT_BOTTOM 430
#define PLOT_WIDTH 530

// Arrays in which raw measurements will be stored
fix15 acceleration[3], gyro[3];

// Arrays for circular display buffer
fix15 ax[PLOT_WIDTH] ;
fix15 ay[PLOT_WIDTH] ;
fix15 az[PLOT_WIDTH] ;
fix15 gx[PLOT_WIDTH] ;
fix15 gy[PLOT_WIDTH] ;
fix15 gz[PLOT_WIDTH] ;

// ===== ADDED: complementary filter =====

// Low-passed accelerometer measurements (15.16 fixed point, g's)
fix15 filtered_ax, filtered_az ;

// Angle estimates (15.16 fixed point, degrees)
fix15 accel_angle ;          // angle from accelerometer only (noisy, no drift)
fix15 gyro_angle_delta ;     // angle change from gyro this timestep
fix15 complementary_angle ;  // fused angle estimate

// Circular display buffers for the angle estimates
fix15 accel_angle_buf[PLOT_WIDTH] ;
fix15 comp_angle_buf[PLOT_WIDTH] ;
// ===== END ADDED =====

// Pointer to head of buffer
volatile int head = 0 ;

// character array
char screentext[80];   // CHANGED: was 40, controller readout line is longer

// draw speed
volatile int threshold = 10 ;

// Some macros for max/min/abs
#define min(a,b) ((a<b) ? a:b)
#define max(a,b) ((a<b) ? b:a)
#define abs(a) ((a>0) ? a:-a)

// semaphore
static struct pt_sem vga_semaphore ;

// Some paramters for PWM
#define WRAPVAL 6000
#define CLKDIV  25.0
// GPIO we're using for PWM
#define PWM_OUT 4
uint slice_num ;
// PWM duty cycle
volatile int control ;
volatile int old_control ;

// ===== ADDED: proportional controller =====
volatile int closed_loop = 0 ;                  // 0 = manual duty ('p'), 1 = P control
volatile fix15 desired_angle = 0 ;              // target angle (degrees, 15.16)
volatile fix15 Kp = int2fix15(100) ;            // gain (duty counts per degree, 15.16)
fix15 angle_error ;                             // desired - measured (degrees, 15.16)
// ===== END ADDED =====


void drawAxes() {
    // Draw the static aspects of the display
    setTextSize(1) ;
    setTextColor(WHITE);

    // Draw bottom plot
    drawHLine(75, 430, 5, CYAN) ;
    drawHLine(75, 355, 5, CYAN) ;
    drawHLine(75, 280, 5, CYAN) ;
    drawVLine(80, 280, 150, CYAN) ;
    sprintf(screentext, "0") ;
    setCursor(50, 350) ;
    writeString(screentext) ;
    sprintf(screentext, "+2") ;
    setCursor(50, 280) ;
    writeString(screentext) ;
    sprintf(screentext, "-2") ;
    setCursor(50, 425) ;
    writeString(screentext) ;

    // Draw top plot
    drawHLine(75, 230, 5, CYAN) ;
    drawHLine(75, 155, 5, CYAN) ;
    drawHLine(75, 80, 5, CYAN) ;
    drawVLine(80, 80, 150, CYAN) ;
    sprintf(screentext, "0") ;
    setCursor(50, 150) ;
    writeString(screentext) ;
    sprintf(screentext, "+250") ;
    setCursor(45, 75) ;
    writeString(screentext) ;
    sprintf(screentext, "-250") ;
    setCursor(45, 225) ;
    writeString(screentext) ;
}

volatile int throttle = 10 ;

// Interrupt service routine
void on_pwm_wrap() {

    // Clear the interrupt flag that brought us here
    pwm_clear_irq(pwm_gpio_to_slice_num(5));
    gpio_put(14, !gpio_get(14)) ;

    // Read the IMU
    // NOTE! This is in 15.16 fixed point. Accel in g's, gyro in deg/s
    // If you want these values in floating point, call fix2float15() on
    // the raw measurements.
    mpu6050_read_raw(acceleration, gyro);

    // ===== ADDED: low pass filter on accelerometer (first-order IIR, alpha = 1/16) =====
    filtered_ax = filtered_ax + ((acceleration[0] - filtered_ax) >> 4);
    filtered_az = filtered_az + ((acceleration[2] - filtered_az) >> 4);
    // ===== END ADDED =====

    // Accelerometer angle (degrees - 15.16 fixed point)
    // NO SMALL ANGLE APPROXIMATION --> ADDED LOW PASS FILTER
    // IMU rotates about +y axis
    // FIXED: removed +PI so flat (arm horizontal) = 0 deg, range -180 to +180
    accel_angle = multfix15(float2fix15(atan2(-filtered_ax, filtered_az)), oneeightyoverpi);

    // Gyro angle delta (measurement times timestep) (15.16 fixed point)
    // gyro y for rotation about +y axis
    gyro_angle_delta = multfix15(gyro[1], zeropt001) ;

    // Complementary angle (degrees - 15.16 fixed point)
    // gyro and accel share the same sign convention so + instead between (comp ang + gyro ang)
    complementary_angle = multfix15(complementary_angle + gyro_angle_delta, zeropt999) + multfix15(accel_angle, zeropt001);

    // ===== ADDED: proportional control =====
    if (closed_loop) {
        // Positive error = arm is below the target, so more thrust is needed
        angle_error = desired_angle - complementary_angle ;
        // Kp * error in 64 bits (avoids overflow), >>32 converts 15.16 * 15.16 to an integer duty cycle
        int u = (int)((((long long)Kp) * ((long long)angle_error)) >> 32) ;
        // The fan can only push one way, so clamp to the valid duty range
        if (u < 0) u = 0 ;
        if (u > WRAPVAL) u = WRAPVAL ;
        control = u ;
    }
    // ===== END ADDED =====

    // Update fan duty cycle
    if (control!=old_control) {
        old_control = control ;
        pwm_set_chan_level(slice_num, PWM_CHAN_A, control);
    }

    // Increment drawspeed controller
    throttle += 1 ;
    // Maintain a circular buffer for display
    if ((throttle >= threshold)) { 
        // Zero drawspeed controller
        throttle = 0 ;

        // Replace oldest data in accel arrays with new sample
        ax[head] = acceleration[0] ;
        ay[head] = acceleration[1] ;
        az[head] = acceleration[2] ;

        // Replace oldest data in gyro arrays with new sample
        gx[head] = gyro[0] ;
        gy[head] = gyro[1] ;
        gz[head] = gyro[2] ;
        
        // ===== ADDED: store complementary filter angle estimates for display =====
        accel_angle_buf[head] = accel_angle ;
        comp_angle_buf[head] = complementary_angle ;
        // ===== END ADDED =====

        // Move the pointer to the oldest data
        head = ((head+1) == PLOT_WIDTH) ? 0 : (head + 1) ;

    }
}

static PT_THREAD (protothread_draw(struct pt *pt))
{
    PT_BEGIN(pt) ;

    static int start ;
    static int i ;

    // Draw axes
    drawAxes() ;
    // Copy to other buffer
    copy_buffer_to_other() ;

    while(1) {
        // Wait for a buffer swap
        PT_YIELD_UNTIL(pt, draw_start_signal()) ;
        gpio_put(15, !gpio_get(15)) ;
        
        // Clear the buffer, draw the axes
        clearLowFrame(0, BLACK) ;
        drawAxes() ;

        // Plot data oldest-->newest
        start = head ;
        for (i = 0; i < PLOT_WIDTH; i++) {
            drawPixel(LEFT_EDGE + i, (BOTTOM_PLOT_BOTTOM -
                (int)(NEW_RANGE*((float)((fix2float15(ax[start])*ACCEL_SCALE)-OLD_MIN)/OLD_RANGE))), WHITE) ;
            drawPixel(LEFT_EDGE + i, (BOTTOM_PLOT_BOTTOM -
                (int)(NEW_RANGE*((float)((fix2float15(ay[start])*ACCEL_SCALE)-OLD_MIN)/OLD_RANGE))), RED) ;
            drawPixel(LEFT_EDGE + i, (BOTTOM_PLOT_BOTTOM -
                (int)(NEW_RANGE*((float)((fix2float15(az[start])*ACCEL_SCALE)-OLD_MIN)/OLD_RANGE))), GREEN) ;
            drawPixel(LEFT_EDGE + i, (TOP_PLOT_BOTTOM -
                (int)(NEW_RANGE*((float)((fix2float15(gx[start]))-OLD_MIN)/OLD_RANGE))), WHITE) ;
            drawPixel(LEFT_EDGE + i, (TOP_PLOT_BOTTOM -
                (int)(NEW_RANGE*((float)((fix2float15(gy[start]))-OLD_MIN)/OLD_RANGE))), RED) ;
            drawPixel(LEFT_EDGE + i, (TOP_PLOT_BOTTOM -
                (int)(NEW_RANGE*((float)((fix2float15(gz[start]))-OLD_MIN)/OLD_RANGE))), GREEN) ;


            // ===== ADDED: complementary filter angle traces on top plot =====
            // Angles rotate about +y axis within the range ~[-90, 90] so 0 degree is when the IMU is parallel to the floor
            drawPixel(LEFT_EDGE + i, (TOP_PLOT_BOTTOM -
                (int)(NEW_RANGE*((float)((fix2float15(accel_angle_buf[start]))-OLD_MIN)/OLD_RANGE))), MAGENTA) ;
            drawPixel(LEFT_EDGE + i, (TOP_PLOT_BOTTOM -
                (int)(NEW_RANGE*((float)((fix2float15(comp_angle_buf[start]))-OLD_MIN)/OLD_RANGE))), YELLOW) ;
            // ===== END ADDED =====

            start = ((start+1)==PLOT_WIDTH) ? 0 : (start+1) ;
        }

        // ===== ADDED: target angle line on top plot =====
        drawHLine(LEFT_EDGE, (TOP_PLOT_BOTTOM -
            (int)(NEW_RANGE*((float)((fix2float15(desired_angle))-OLD_MIN)/OLD_RANGE))), PLOT_WIDTH, LIGHT_BLUE) ;
        // ===== END ADDED =====

        // ===== ADDED: numeric readout of angle estimates =====
        setTextSize(2) ;
        setTextColor(MAGENTA) ;
        setCursor(85, 20) ;
        sprintf(screentext, "Accel Ang: %6.1f", fix2float15(accel_angle)) ;
        writeString(screentext) ;
        setTextColor(YELLOW) ;
        setCursor(330, 20) ;
        sprintf(screentext, "Comp Ang: %6.1f", fix2float15(complementary_angle)) ;
        writeString(screentext) ;
        setTextSize(1) ;
        // ===== END ADDED =====

        // ===== ADDED: controller readout =====
        setTextColor(LIGHT_BLUE) ;
        setCursor(85, 45) ;
        sprintf(screentext, "Target: %6.1f  Kp: %6.1f  Duty: %4d  %s",
            fix2float15(desired_angle), fix2float15(Kp), control, closed_loop ? "CLOSED LOOP" : "MANUAL") ;
        writeString(screentext) ;
        // ===== END ADDED =====
    }

    PT_END(pt) ;
}

// User input thread. User can change draw speed
static PT_THREAD (protothread_serial(struct pt *pt))
{
    PT_BEGIN(pt) ;
    static char classifier ;
    static int test_in ;
    static float float_in ;
    while(1) {
        sprintf(pt_serial_out_buffer, "input a command: ");
        serial_write ;
        // spawn a thread to do the non-blocking serial read
        serial_read ;
        // convert input string to number
        sscanf(pt_serial_in_buffer,"%c", &classifier) ;

        // num_independents = test_in ;
        if (classifier=='t') {
            sprintf(pt_serial_out_buffer, "timestep: ");
            serial_write ;
            serial_read ;
            // convert input string to number
            sscanf(pt_serial_in_buffer,"%d", &test_in) ;
            if (test_in > 0) {
                threshold = test_in ;
            }
        }
        // ===== ADDED: 'p' command sets fan duty cycle (from PWM_Demo) =====
        else if (classifier=='p') {
            sprintf(pt_serial_out_buffer, "duty cycle (0-%d): ", WRAPVAL);
            serial_write ;
            serial_read ;
            // convert input string to number
            sscanf(pt_serial_in_buffer,"%d", &test_in) ;
            if (test_in >= 0 && test_in <= WRAPVAL) {
                closed_loop = 0 ;   // ADDED: manual duty turns off the controller
                control = test_in ;
            }
        }
        // ===== END ADDED =====
        // ===== ADDED: controller commands =====
        // 'a' = target angle, 'k' = Kp, 'c' = closed loop on (1) / off (0)
        else if (classifier=='a') {
            sprintf(pt_serial_out_buffer, "target angle (-180 to 180 deg): ");
            serial_write ;
            serial_read ;
            sscanf(pt_serial_in_buffer,"%f", &float_in) ;
            if (float_in >= -180.0f && float_in <= 180.0f) {
                desired_angle = float2fix15(float_in) ;
            }
        }
        else if (classifier=='k') {
            sprintf(pt_serial_out_buffer, "Kp (duty counts per degree): ");
            serial_write ;
            serial_read ;
            sscanf(pt_serial_in_buffer,"%f", &float_in) ;
            if (float_in >= 0.0f && float_in <= 6000.0f) {
                Kp = float2fix15(float_in) ;
            }
        }
        else if (classifier=='c') {
            sprintf(pt_serial_out_buffer, "closed loop (1 = on, 0 = off): ");
            serial_write ;
            serial_read ;
            sscanf(pt_serial_in_buffer,"%d", &test_in) ;
            if (test_in == 0) {
                closed_loop = 0 ;
                control = 0 ;   // fan off when leaving closed loop
            }
            else if (test_in == 1) {
                closed_loop = 1 ;
            }
        }
        // ===== END ADDED =====
    }
    PT_END(pt) ;
}

// Entry point for core 1
void core1_entry() {
    gpio_init(15) ;
    gpio_set_dir(15, GPIO_OUT) ;
    gpio_put(15, 0) ;
    pt_add_thread(protothread_draw) ;
    pt_schedule_start ;
}

int main() {

    // Overclock
    set_sys_clock_khz(150000, true) ;

    // Initialize stdio
    stdio_init_all();

    // Initialize VGA
    initVGA() ;

    // ===== ADDED: I2C bus recovery =====
    // If the Pico resets mid-transfer, the MPU6050 (which stays powered) can be
    // left holding SDA low, and mpu6050_reset() then blocks forever. Clocking SCL
    // up to 9 times lets the IMU finish its byte and release SDA.
    gpio_init(SDA_PIN) ;
    gpio_init(SCL_PIN) ;
    gpio_set_dir(SDA_PIN, GPIO_IN) ;
    gpio_pull_up(SDA_PIN) ;
    gpio_set_dir(SCL_PIN, GPIO_OUT) ;
    gpio_put(SCL_PIN, 1) ;
    sleep_us(10) ;
    for (int k = 0; k < 9 && !gpio_get(SDA_PIN); k++) {
        gpio_put(SCL_PIN, 0) ;
        sleep_us(5) ;
        gpio_put(SCL_PIN, 1) ;
        sleep_us(5) ;
    }
    printf("\n\rI2C bus %s\n\r", gpio_get(SDA_PIN) ? "free" : "STUCK (SDA held low)") ;
    // ===== END ADDED =====

    ////////////////////////////////////////////////////////////////////////
    ///////////////////////// I2C CONFIGURATION ////////////////////////////
    i2c_init(I2C_CHAN, I2C_BAUD_RATE) ;
    gpio_set_function(SDA_PIN, GPIO_FUNC_I2C) ;
    gpio_set_function(SCL_PIN, GPIO_FUNC_I2C) ;

    // MPU6050 initialization
    mpu6050_reset();
    mpu6050_read_raw(acceleration, gyro);

    // // ===== ADDED: seed filters with first reading so the angle doesn't start at 0 =====
    filtered_ax = acceleration[0] ;
    filtered_az = acceleration[2] ;
    complementary_angle = multfix15(float2fix15(atan2(-filtered_ax, filtered_az)), oneeightyoverpi);
    // // ===== END ADDED =====

    ////////////////////////////////////////////////////////////////////////
    ///////////////////////// PWM CONFIGURATION ////////////////////////////
    ////////////////////////////////////////////////////////////////////////
    // Tell GPIO's 4,5 that they allocated to the PWM
    gpio_set_function(5, GPIO_FUNC_PWM);
    gpio_set_function(PWM_OUT, GPIO_FUNC_PWM);  // CHANGED: was hardcoded 4, now uses PWM_OUT

    // Find out which PWM slice is connected to GPIO 5 (it's slice 2, same for 4)
    slice_num = pwm_gpio_to_slice_num(5);

    // Mask our slice's IRQ output into the PWM block's single interrupt line,
    // and register our interrupt handler
    pwm_clear_irq(slice_num);
    pwm_set_irq_enabled(slice_num, true);
    irq_set_exclusive_handler(PWM_IRQ_WRAP, on_pwm_wrap);
    irq_set_enabled(PWM_IRQ_WRAP, true);

    // This section configures the period of the PWM signals
    pwm_set_wrap(slice_num, WRAPVAL) ;
    pwm_set_clkdiv(slice_num, CLKDIV) ;

    // This sets duty cycle
    pwm_set_chan_level(slice_num, PWM_CHAN_B, 0);
    pwm_set_chan_level(slice_num, PWM_CHAN_A, 0);

    // Start the channel
    pwm_set_mask_enabled((1u << slice_num));

   
    ////////////////////////////////////////////////////////////////////////
    ///////////////////////////// ROCK AND ROLL ////////////////////////////
    ////////////////////////////////////////////////////////////////////////
    // start core 1 
    multicore_reset_core1();
    multicore_launch_core1(core1_entry);

    // start core 0
    gpio_init(14) ;
    gpio_set_dir(14, GPIO_OUT) ;
    gpio_put(14, 0) ;
    pt_add_thread(protothread_serial) ;
    pt_schedule_start ;

}
