"""Calibrate laser power by optimizing Urukul RF amplitude from photodiode readout.

Edit the constants in the "EDIT THESE FIRST" section before a lab run. This
experiment keeps DDS frequency fixed, varies only RF amplitude, and converts
photodiode voltage into laser power using the detector calibration at 633 nm.

MAKE SURE TO CHECK GAIN, DEFAULT DDS FREQ, DEFAULT TARGET POWER
"""

from __future__ import annotations

from main import Parameter, run as run_bo

try:
    from artiq.experiment import EnvExperiment, EnumerationValue, NumberValue, delay, kernel, MHz, ms, us

    ARTIQ_AVAILABLE = True
    ARTIQ_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - allows import on non-ARTIQ hosts
    ARTIQ_AVAILABLE = False
    ARTIQ_IMPORT_ERROR = exc

    class EnvExperiment:  # type: ignore[override]
        pass

    class NumberValue:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

    class EnumerationValue:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

    def kernel(func):  # type: ignore[override]
        return func

    def delay(_):  # type: ignore[override]
        return None

    MHz = 1e6
    ms = 1e-3
    us = 1e-6


# EDIT THESE FIRST
# Detector calibration is fixed for tomorrow's setup at 633 nm.
RESPONSIVITY_A_PER_W = 0.33

# WARNING: This must match the physical gain dial on the detector.
# Verify the detector is set to 70 dB Hi-Z before running.
# EDIT THESE FIRST
# Match this to the physical knob position on the PDA36A2 before running.
GAIN_SETTING_DB = 70  # options: 0, 10, 20, 30, 40, 50, 60, 70

TIA_GAIN_HI_Z = {
    0:  1.51e3,
    10: 4.75e3,
    20: 1.5e4,
    30: 4.75e4,
    40: 1.51e5,
    50: 4.75e5,
    60: 1.5e6,
    70: 4.75e6,
}

TIA_GAIN_V_PER_A = TIA_GAIN_HI_Z[GAIN_SETTING_DB]
WATTS_TO_NANOWATTS = 1e9

# Hardware defaults.
ADC_CHANNEL = 0
DDS_PROFILE = 3
DEFAULT_AOM_ENABLED = "on"
DEFAULT_DDS_FREQUENCY_HZ = 200 * MHz
DEFAULT_TARGET_POWER_NW = 1000.0
DEFAULT_SETTLE_TIME_MS = 1.0
DEFAULT_ADC_AVERAGES = 8
DEFAULT_INIT_TRIALS = 5
DEFAULT_MAX_TRIALS = 30
DEFAULT_SEED = 123
AMPLITUDE_MIN = 0.05
AMPLITUDE_MAX = 0.95


class PowerMeasurement:
    def __init__(self, amplitude: float, photodiode_v: float, optical_power_nw: float, objective: float):
        self.amplitude = amplitude
        self.photodiode_v = photodiode_v
        self.optical_power_nw = optical_power_nw
        self.objective = objective


def voltage_to_power_w(voltage_v: float, dark_voltage_v: float) -> float:
    return (voltage_v - dark_voltage_v) / (RESPONSIVITY_A_PER_W * TIA_GAIN_V_PER_A)


def voltage_to_power_nw(voltage_v: float, dark_voltage_v: float) -> float:
    return voltage_to_power_w(voltage_v, dark_voltage_v) * WATTS_TO_NANOWATTS


class LaserPowerCalibration(EnvExperiment):
    """Single-use ARTIQ experiment for Urukul-driven laser power calibration."""

    def _ensure_artiq(self) -> None:
        if not ARTIQ_AVAILABLE:
            raise RuntimeError(
                "ARTIQ is not available in this Python environment. "
                f"Import error: {ARTIQ_IMPORT_ERROR}"
            )

    def build(self):
        if not ARTIQ_AVAILABLE:
            return

        self.setattr_device("core")
        self.setattr_device("suservo0")
        self.setattr_device("suservo0_ch3")

        self.setattr_argument(
            "aom_enabled",
            EnumerationValue(["on", "off"], default=DEFAULT_AOM_ENABLED),
        )
        self.setattr_argument(
            "dds_frequency_hz",
            NumberValue(default=DEFAULT_DDS_FREQUENCY_HZ, min=1 * MHz, max=400 * MHz, step=1 * MHz, unit="Hz"),
        )
        self.setattr_argument(
            "target_power_nw",
            NumberValue(default=DEFAULT_TARGET_POWER_NW, min=0.0, max=1e9),
        )
        self.setattr_argument(
            "dark_voltage_v",
            NumberValue(default=0.0, min=-10.0, max=10.0, unit="V"),
        )
        self.setattr_argument(
            "settle_time_ms",
            NumberValue(default=DEFAULT_SETTLE_TIME_MS, min=0.01, max=1000.0, unit="ms"),
        )
        self.setattr_argument(
            "adc_averages",
            NumberValue(default=DEFAULT_ADC_AVERAGES, min=1, max=1024, step=1, ndecimals=0),
        )
        self.setattr_argument(
            "init_trials",
            NumberValue(default=DEFAULT_INIT_TRIALS, min=1, step=1, ndecimals=0),
        )
        self.setattr_argument(
            "max_trials",
            NumberValue(default=DEFAULT_MAX_TRIALS, min=1, step=1, ndecimals=0),
        )
        self.setattr_argument(
            "seed",
            NumberValue(default=DEFAULT_SEED, min=0, step=1, ndecimals=0),
        )

    def prepare(self):
        if not ARTIQ_AVAILABLE:
            return

        self.dds_frequency_hz = float(self.dds_frequency_hz)
        self.target_power_nw = float(self.target_power_nw)
        self.dark_voltage_v = float(self.dark_voltage_v)
        self.settle_time_ms = float(self.settle_time_ms)

        self.adc_averages = int(self.adc_averages)
        self.init_trials = int(self.init_trials)
        self.max_trials = int(self.max_trials)
        self.seed = int(self.seed)

        self._aom_enabled = 1 if self.aom_enabled == "on" else 0
        self._dark_offset_measured = False

    def parameter_space(self) -> list[Parameter]:
        return [Parameter("dds_amplitude", (AMPLITUDE_MIN, AMPLITUDE_MAX))]

    def _ensure_devices_present(self) -> None:
        missing = [name for name in ("core", "suservo0", "suservo0_ch3") if not hasattr(self, name)]
        if missing:
            raise RuntimeError(
                "Missing required devices in device_db for this experiment: "
                f"{missing}. Add the missing entries to src/device_db.py."
            )

    def _objective_from_power_nw(self, power_nw: float) -> float:
        error_nw = power_nw - self.target_power_nw
        return -(error_nw * error_nw)

    def _measurement_from_voltage(self, amplitude: float, photodiode_v: float) -> PowerMeasurement:
        power_nw = voltage_to_power_nw(photodiode_v, self.dark_voltage_v)
        return PowerMeasurement(
            amplitude=float(amplitude),
            photodiode_v=float(photodiode_v),
            optical_power_nw=float(power_nw),
            objective=self._objective_from_power_nw(power_nw),
        )

    def _print_run_summary(self) -> None:
        print("Laser power calibration settings:")
        print(f"  target_power_nw={self.target_power_nw:.3f}")
        print(f"  dds_frequency_hz={self.dds_frequency_hz:.3f}")
        print(f"  amplitude_bounds=({AMPLITUDE_MIN:.2f}, {AMPLITUDE_MAX:.2f})")
        print(f"  adc_averages={self.adc_averages}")
        print(f"  settle_time_ms={self.settle_time_ms:.3f}")
        print(f"  init_trials={self.init_trials}")
        print(f"  max_trials={self.max_trials}")
        print(f"  dark_voltage_v={self.dark_voltage_v:.6f}")
        print(f"  detector_wavelength_nm=633")
        print(f"  responsivity_a_per_w={RESPONSIVITY_A_PER_W}")
        print(f"  tia_gain_v_per_a={TIA_GAIN_V_PER_A}")

    @kernel
    def configure_dds_output(self, amplitude: float):
        self.core.break_realtime()
        self.suservo0.init()
        self.suservo0.set_pgia_mu(ADC_CHANNEL, 0)
        if amplitude < 0.0:
            amplitude = 0.0
        if amplitude > 1.0:
            amplitude = 1.0
        self.suservo0_ch3.set_dds(
            profile=DDS_PROFILE,
            frequency=self.dds_frequency_hz,
            offset=0.0,
            phase=0.0,
        )
        self.suservo0.set_config(enable=1)
        self.suservo0_ch3.set_y(DDS_PROFILE, amplitude)
        delay(100 * us)

    @kernel
    def aom_on(self):
        self.suservo0_ch3.set(en_out=1, en_iir=0, profile=DDS_PROFILE)

    @kernel
    def aom_off(self):
        self.suservo0_ch3.set(en_out=0, en_iir=0, profile=DDS_PROFILE)

    @kernel
    def set_dds_amplitude(self, amplitude: float):
        if amplitude < 0.0:
            amplitude = 0.0
        if amplitude > 1.0:
            amplitude = 1.0
        self.suservo0_ch3.set_y(DDS_PROFILE, amplitude)

    @kernel
    def init_hardware(self):
        self.core.reset()
        self.core.break_realtime()
        self.configure_dds_output(0.0)
        if self._aom_enabled == 1:
            self.aom_on()
        else:
            self.aom_off()

    @kernel
    def measure_photodiode_voltage(self, amplitude: float) -> float:
        self.core.break_realtime()
        self.set_dds_amplitude(amplitude)
        delay(self.settle_time_ms * ms)

        total_v = 0.0
        i = 0
        while i < self.adc_averages:
            self.suservo0.set_config(enable=0)
            delay(5 * us)
            total_v += self.suservo0.get_adc(ADC_CHANNEL)
            delay(5 * us)
            self.suservo0.set_config(enable=1)
            delay(5 * us)
            i += 1
        return total_v / self.adc_averages

    def measure_dark_offset(self) -> float:
        self._ensure_artiq()
        if self._dark_offset_measured:
            return self.dark_voltage_v
        # Dark offset is defined here as the photodiode reading at RF amplitude = 0.
        self.dark_voltage_v = float(self.measure_photodiode_voltage(0.0))
        self._dark_offset_measured = True
        return self.dark_voltage_v

    def evaluate(self, params: dict[str, float]) -> float:
        self._ensure_artiq()
        amplitude = float(params["dds_amplitude"])
        photodiode_v = float(self.measure_photodiode_voltage(amplitude))
        measurement = self._measurement_from_voltage(amplitude, photodiode_v)
        self._last_metric_name = "power_nw"
        self._last_metric_value = measurement.optical_power_nw
        return measurement.objective

    def evaluate_and_record(self, amplitude: float) -> PowerMeasurement:
        self._ensure_artiq()
        photodiode_v = float(self.measure_photodiode_voltage(float(amplitude)))
        return self._measurement_from_voltage(amplitude, photodiode_v)

    def run(self):
        self._ensure_artiq()
        self._ensure_devices_present()
        self.init_hardware()
        self.measure_dark_offset()
        self._print_run_summary()

        best = run_bo(
            experiment=self,
            init_trials=self.init_trials,
            max_trials=self.max_trials,
            seed=self.seed,
        )

        best_amplitude = None
        if isinstance(best, dict):
            params = best.get("params")
            if isinstance(params, dict):
                best_amplitude = params.get("dds_amplitude")

        if best_amplitude is not None:
            best_measurement = self.evaluate_and_record(float(best_amplitude))
            print("\nBest laser power result:")
            print(f"  dds_amplitude={best_measurement.amplitude:.6f}")
            print(f"  optical_power_nw={best_measurement.optical_power_nw:.3f}")
            print(f"  photodiode_voltage_v={best_measurement.photodiode_v:.6f}")
            print(f"  objective={best_measurement.objective:.3f}")
        else:
            print(f"Laser power calibration complete: {best}")
