"""Calibrate laser power by optimizing Urukul RF amplitude from power meter readout.

Edit the constants in the "EDIT THESE FIRST" section before a lab run. This
experiment keeps DDS frequency fixed, varies only RF amplitude, and reads
optical power directly from a Thorlabs power meter.

MAKE SURE TO CHECK WAVELENGTH_NM, DEFAULT DDS FREQ, DEFAULT TARGET POWER
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

try:
    from ctypes import c_double, c_uint32, c_bool, c_int, c_int16, byref, create_string_buffer
    from TLPMX import TLPMX, TLPM_DEFAULT_CHANNEL

    TLPMX_AVAILABLE = True
    TLPMX_IMPORT_ERROR = None
except Exception as exc:
    TLPMX_AVAILABLE = False
    TLPMX_IMPORT_ERROR = exc


# EDIT THESE FIRST
# Must match the wavelength label on the power meter calibration.
WAVELENGTH_NM = 633

WATTS_TO_NANOWATTS = 1e9

# Hardware defaults.
DDS_PROFILE = 3
DEFAULT_AOM_ENABLED = "on"
DEFAULT_DDS_FREQUENCY_HZ = 200 * MHz
DEFAULT_TARGET_POWER_NW = 1000.0
DEFAULT_SETTLE_TIME_MS = 1.0
DEFAULT_ADC_AVERAGES = 8
DEFAULT_INIT_TRIALS = 5
DEFAULT_MAX_TRIALS = 30
DEFAULT_SEED = 123
AMPLITUDE_MIN = 0.00
AMPLITUDE_MAX = 0.95


class PowerMeasurement:
    def __init__(self, amplitude: float, optical_power_nw: float, objective: float):
        self.amplitude = amplitude
        self.optical_power_nw = optical_power_nw
        self.objective = objective


class LaserPowerCalibration(EnvExperiment):
    """Single-use ARTIQ experiment for Urukul-driven laser power calibration."""

    def _ensure_artiq(self) -> None:
        if not ARTIQ_AVAILABLE:
            raise RuntimeError(
                "ARTIQ is not available in this Python environment. "
                f"Import error: {ARTIQ_IMPORT_ERROR}"
            )

    def _ensure_tlpmx(self) -> None:
        if not TLPMX_AVAILABLE:
            raise RuntimeError(
                "TLPMX is not available in this Python environment. "
                f"Import error: {TLPMX_IMPORT_ERROR}"
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
        self.settle_time_ms = float(self.settle_time_ms)

        self.adc_averages = int(self.adc_averages)
        self.init_trials = int(self.init_trials)
        self.max_trials = int(self.max_trials)
        self.seed = int(self.seed)

        self._aom_enabled = 1 if self.aom_enabled == "on" else 0

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

    def _print_run_summary(self) -> None:
        print("Laser power calibration settings:")
        print(f"  target_power_nw={self.target_power_nw:.3f}")
        print(f"  dds_frequency_hz={self.dds_frequency_hz:.3f}")
        print(f"  amplitude_bounds=({AMPLITUDE_MIN:.2f}, {AMPLITUDE_MAX:.2f})")
        print(f"  adc_averages={self.adc_averages}")
        print(f"  settle_time_ms={self.settle_time_ms:.3f}")
        print(f"  init_trials={self.init_trials}")
        print(f"  max_trials={self.max_trials}")
        print(f"  wavelength_nm={WAVELENGTH_NM}")

    @kernel
    def configure_dds_output(self, amplitude: float):
        self.core.break_realtime()
        self.suservo0.init()
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
    def set_amplitude_and_settle(self, amplitude: float):
        self.core.break_realtime()
        self.set_dds_amplitude(amplitude)
        delay(self.settle_time_ms * ms)

    @kernel
    def init_hardware(self):
        self.core.reset()
        self.core.break_realtime()
        self.configure_dds_output(0.0)
        if self._aom_enabled == 1:
            self.aom_on()
        else:
            self.aom_off()

    def measure_power_nw(self, amplitude: float) -> float:
        self.set_amplitude_and_settle(amplitude)
        power = c_double()
        total = 0.0
        for _ in range(self.adc_averages):
            self._tlpm.measPower(byref(power), TLPM_DEFAULT_CHANNEL)
            total += power.value
        return (total / self.adc_averages) * WATTS_TO_NANOWATTS

    def evaluate(self, params: dict[str, float]) -> float:
        self._ensure_artiq()
        amplitude = float(params["dds_amplitude"])
        power_nw = self.measure_power_nw(amplitude)
        self._last_metric_name = "power_nw"
        self._last_metric_value = power_nw
        return self._objective_from_power_nw(power_nw)

    def evaluate_and_record(self, amplitude: float) -> PowerMeasurement:
        self._ensure_artiq()
        power_nw = self.measure_power_nw(float(amplitude))
        return PowerMeasurement(
            amplitude=float(amplitude),
            optical_power_nw=float(power_nw),
            objective=self._objective_from_power_nw(power_nw),
        )

    def run(self):
        self._ensure_artiq()
        self._ensure_tlpmx()
        self._ensure_devices_present()
        self.init_hardware()
        self._print_run_summary()

        resourceName = create_string_buffer(1024)
        deviceCount = c_uint32()
        self._tlpm = TLPMX()
        self._tlpm.findRsrc(byref(deviceCount))
        self._tlpm.getRsrcName(c_int(0), resourceName)
        self._tlpm.open(resourceName, c_bool(True), c_bool(True))
        self._tlpm.setWavelength(c_double(WAVELENGTH_NM), TLPM_DEFAULT_CHANNEL)
        self._tlpm.setPowerUnit(c_int16(0), TLPM_DEFAULT_CHANNEL)  # 0 = Watts

        try:
            best = run_bo(
                experiment=self,
                init_trials=self.init_trials,
                max_trials=self.max_trials,
                seed=self.seed,
            )
        finally:
            self._tlpm.close()

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
            print(f"  objective={best_measurement.objective:.3f}")
        else:
            print(f"Laser power calibration complete: {best}")
