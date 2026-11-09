"""Typeset every report formula to a PNG (matplotlib mathtext, Computer Modern).

Run:  python3 make_formulas.py      (writes figures/eq_*.png)
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

matplotlib.rcParams["mathtext.fontset"] = "cm"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figures")

EQ = {
    # --- complementary filter -------------------------------------------------
    "accel": r"$\theta_{acc} = \frac{180}{\pi}\,\mathrm{atan2}\left(-\bar{a}_x,\ \bar{a}_z\right)$",
    "gyro": r"$\theta_{gyro}(t) = \theta_0 + \int_0^t (\omega_y + b)\,dt' = \theta_{true}(t) + b\,t$",
    "comp": r"$\hat{\theta}_n = 0.999\,\left(\hat{\theta}_{n-1} + \omega_{y,n}\,\Delta t\right) + 0.001\,\theta_{acc,n}$",
    "comp_tf": r"$\hat{\Theta}(s) = \frac{1}{\tau s+1}\,\Theta_{acc}(s) + \frac{\tau s}{\tau s+1}\,\Theta_{gyro}(s),"
               r"\qquad \tau = \frac{\alpha\,\Delta t}{1-\alpha} = \frac{0.999 \times 1\ \mathrm{ms}}{0.001} \approx 1\ \mathrm{s}$",
    "bias": r"$e_{ss} = \lim_{s\to 0}\ s\cdot\frac{\tau s}{\tau s+1}\cdot\frac{b}{s^2} = \tau\, b"
            r"\qquad (b = 1\,^\circ/\mathrm{s}\ \Rightarrow\ e_{ss} \approx 1^\circ)$",
    "lpf": r"$y_n = y_{n-1} + \frac{1}{16}\left(x_n - y_{n-1}\right)"
           r"\quad\Longleftrightarrow\quad RC\,\frac{dV_{out}}{dt} = V_{in} - V_{out},\ \ \frac{\Delta t}{RC} = \frac{1}{16}$",
    "lpf_fc": r"$\tau_{LP} \approx 16\,\Delta t = 16\ \mathrm{ms},\qquad f_c = \frac{1}{2\pi\,\tau_{LP}} \approx 10\ \mathrm{Hz}$",
    # --- PID -------------------------------------------------------------------
    "pid": r"$u(t) = K_p\, e(t) + K_i \int_0^t e\,dt' + K_d\,\frac{de}{dt},\qquad e = \theta_{des} - \hat{\theta}$",
    "dedt": r"$\frac{de}{dt} = \frac{d\theta_{des}}{dt} - \frac{d\hat{\theta}}{dt} = -\,\omega_y"
            r"\qquad (\theta_{des}\ \mathrm{constant\ between\ commands})$",
    "pid_disc": r"$I_n = \mathrm{clamp}\left(I_{n-1} + K_i\, e_n,\ 0,\ I_{max}\right),\qquad"
                r"u_n = \mathrm{clamp}\left(K_p\, e_n - K_d\,\omega_{y,n} + I_n,\ \ 0,\ \ u_{lim,n}\right)$",
    "ulim": r"$u_{lim,n} = \mathrm{min}\left(u_{n-1} + 20,\ 6000\right)"
            r"\qquad \Rightarrow\qquad 0 \rightarrow 6000\ \mathrm{counts\ in}\ 300\ \mathrm{ms}$",
    "gains": r"$K_p = 80\ \frac{\mathrm{counts}}{\deg},\qquad K_d = 12\ \frac{\mathrm{counts}}{\deg/\mathrm{s}},"
             r"\qquad K_i = 0.2\ \frac{\mathrm{counts}}{\deg\cdot\mathrm{ms}} = 200\ \frac{\mathrm{counts}}{\deg\cdot\mathrm{s}}$",
    "pid_zeros": r"$C(s) = K_p + \frac{K_i}{s} + K_d\, s = \frac{K_d s^2 + K_p s + K_i}{s},"
                 r"\qquad T_i = \frac{K_p}{K_i} = 0.4\ \mathrm{s},\qquad T_d = \frac{K_d}{K_p} = 0.15\ \mathrm{s}$",
    "zeros_val": r"$12 s^2 + 80 s + 200 = 0\ \ \Rightarrow\ \ s = -3.3 \pm 2.4j\ \mathrm{rad/s}"
                 r"\qquad (|s| \approx 4.1\ \mathrm{rad/s},\ \zeta \approx 0.82)$",
    # --- plant -----------------------------------------------------------------
    "motor_tf": r"$\frac{\Omega(s)}{V(s)} = \frac{K}{(Js + b)(Ls + R) + K^2}$",
    "torque": r"$K_T\,\omega^2 L - m g L\,\sin\theta - K_f\,\dot{\theta} = m L^2\,\ddot{\theta}$",
    "lin": r"$\Delta\ddot{\theta} = \frac{2 K_T \omega_0}{m L}\,\Delta\omega - \frac{g}{L}\cos\theta_0\,\Delta\theta"
           r" - \frac{K_f}{m L^2}\,\Delta\dot{\theta}$",
    "plant_tf": r"$\frac{\Delta\Theta(s)}{\Delta\Omega(s)} = \frac{2K_T\omega_0/(mL)}{s^2 + \frac{K_f}{mL^2}\,s + \frac{g}{L}\cos\theta_0}$",
    "hover": r"$K_T\,\omega_0^2 = m g\,\sin\theta_0 = m g\,\cos\varphi_0"
             r"\qquad (\varphi = \theta - 90^\circ\ \mathrm{is\ the\ angle\ in\ our\ code})$",
    "com_offset": r"$\tau_g(\varphi) = m g\,\left(r\,\cos\varphi + d\,\sin\varphi\right)$",
    # --- PWM / circuit ---------------------------------------------------------
    "pwm_f": r"$f_{PWM} = \frac{f_{sys}}{\mathrm{CLKDIV}\,\left(\mathrm{WRAP} + 1\right)}"
             r" = \frac{150\ \mathrm{MHz}}{25 \times 6001} \approx 999.8\ \mathrm{Hz}$",
    "pwm_avg": r"$\bar{V}_{motor} = D\,V_s = \frac{\mathrm{level}}{6001}\,V_s,"
               r"\qquad \frac{3280}{6001}\times 5\ \mathrm{V} \approx 2.7\ \mathrm{V\ (hover\ at\ } 0^\circ)$",
    "ldi": r"$V = L\,\frac{dI}{dt} = 10^{-3}\ \mathrm{H}\cdot\frac{1\ \mathrm{A}}{10^{-8}\ \mathrm{s}} = 10^{5}\ \mathrm{V}$",
    # --- fixed point / I2C -------------------------------------------------------
    "fix": r"$x_{fix} = \mathrm{round}\left(x \cdot 2^{16}\right),\qquad (a\,b)_{fix} = \left(a_{fix}\, b_{fix}\right) \gg 16$",
    "i2c": r"$t_{read} \approx \frac{(2 + 7)\ \mathrm{bytes} \times 9\ \mathrm{clocks}}{400\ \mathrm{kHz}} \approx 0.2\ \mathrm{ms},"
           r"\qquad 2\ \mathrm{reads} \approx 0.4\ \mathrm{ms\ of\ each}\ 1\ \mathrm{ms}$",
    # --- plain-language report: final formulas only --------------------------------
    "gyro_s": r"$\theta_{gyro,n} = \theta_{gyro,n-1} + \omega_{y,n}\,\Delta t\qquad (\Delta t = 1\ \mathrm{ms})$",
    "lpf_s": r"$y_n = y_{n-1} + \frac{x_n - y_{n-1}}{16}\qquad (\mathrm{cutoff} \approx 10\ \mathrm{Hz})$",
    "hover_s": r"$K_T\,\omega_0^2 = m g\,\cos\varphi_0$",
}


def render(name, tex, size=15):
    fig = plt.figure(figsize=(0.01, 0.01))
    fig.text(0, 0, tex, fontsize=size)
    path = os.path.join(OUT, f"eq_{name}.png")
    fig.savefig(path, dpi=220, bbox_inches="tight", pad_inches=0.04, transparent=True)
    plt.close(fig)
    return path


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for k, v in EQ.items():
        render(k, v)
    print(f"wrote {len(EQ)} formulas to {OUT}")
