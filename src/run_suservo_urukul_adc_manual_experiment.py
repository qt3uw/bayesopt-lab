"""Manual ARTIQ entrypoint for SUServo Ch3 DDS + ADC Bayesian optimization."""

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


class PowerMeasurement:
    def __init__(self, amplitude: float, photodiode_v: float, optical_power_nw: float, objective: float):
        self.amplitude = amplitude
        self.photodiode_v = photodiode_v
        self.optical_power_nw = optical_power_nw
        self.objective = objective


class SUServoUrukulADCManualBOExperiment(EnvExperiment):
    """Manual single-use experiment for SUServo Ch3 DDS amplitude optimization."""
    ADC_CHANNEL = 0

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
            "U3_aom_status",
            EnumerationValue(["u3 aom on", "u3 aom off"], default="u3 aom on"),
        )
        self.setattr_argument(
            "U3_dds_frequency",
            NumberValue(default=200 * MHz, min=1 * MHz, max=400 * MHz, step=1 * MHz, unit="Hz"),
        )
        self.setattr_argument("target_power_nw", NumberValue(default=1000.0, min=0.0, max=1e9))
        self.setattr_argument("pd_voltage_offset_v", NumberValue(default=0.0, min=-10.0, max=10.0, unit="V"))
        self.setattr_argument("pd_voltage_to_nw_gain", NumberValue(default=1e6, min=0.0, max=1e12))
        self.setattr_argument(
            "settle_time_ms",
            NumberValue(default=1.0, min=0.01, max=1000.0, unit="ms"),
        )
        self.setattr_argument("adc_averages", NumberValue(default=8, min=1, max=1024, step=1, ndecimals=0))
        self.setattr_argument("init_trials", NumberValue(default=5, min=1, step=1, ndecimals=0))
        self.setattr_argument("max_trials", NumberValue(default=30, min=1, step=1, ndecimals=0))
        self.setattr_argument("seed", NumberValue(default=123, min=0, step=1, ndecimals=0))

    def prepare(self):
        if not ARTIQ_AVAILABLE:
            return
        self.adc_averages = int(self.adc_averages)
        self.init_trials = int(self.init_trials)
        self.max_trials = int(self.max_trials)
        self.seed = int(self.seed)

        self.U3_dds_frequency = float(self.U3_dds_frequency)
        self.target_power_nw = float(self.target_power_nw)
        self.pd_voltage_offset_v = float(self.pd_voltage_offset_v)
        self.pd_voltage_to_nw_gain = float(self.pd_voltage_to_nw_gain)
        self.settle_time_ms = float(self.settle_time_ms)
        self._aom_enabled = 1 if self.U3_aom_status == "u3 aom on" else 0

    def parameter_space(self) -> list[Parameter]:
        return [Parameter("u3_dds_amp", (0.05, 0.95))]

    def _ensure_devices_present(self) -> None:
        missing = [name for name in ("core", "suservo0", "suservo0_ch3") if not hasattr(self, name)]
        if missing:
            raise RuntimeError(
                "Missing required devices in device_db for this experiment: "
                f"{missing}. Add the missing entries to src/device_db.py."
            )

    @kernel
    def set_power(self, amplitude: float):
        self.core.break_realtime()
        self.suservo0.init()
        self.suservo0.set_pgia_mu(self.ADC_CHANNEL, 0)

        self.suservo0_ch3.set_dds(
            profile=3,
            frequency=self.U3_dds_frequency,
            offset=0.0,
            phase=0.0,
        )
        self.suservo0.set_config(enable=1)
        self.suservo0_ch3.set_y(3, amplitude)
        delay(100 * us)

    @kernel
    def aom_on(self):
        self.suservo0_ch3.set(en_out=1, en_iir=0, profile=3)

    @kernel
    def aom_off(self):
        self.suservo0_ch3.set(en_out=0, en_iir=0, profile=3)

    @kernel
    def change_frequency(self, frequency: float):
        self.suservo0_ch3.set_dds(profile=3, frequency=frequency, offset=0.0, phase=0.0)

    @kernel
    def change_amplitude(self, amplitude: float):
        if amplitude < 0.0:
            amplitude = 0.0
        if amplitude > 1.0:
            amplitude = 1.0
        self.suservo0_ch3.set_y(3, amplitude)

    @kernel
    def init_hardware(self):
        self.core.reset()
        self.core.break_realtime()
        self.set_power(0.5)
        if self._aom_enabled == 1:
            self.aom_on()
        else:
            self.aom_off()

    @kernel
    def measure_photodiode_voltage(self, amplitude: float) -> float:
        self.core.break_realtime()
        self.change_amplitude(amplitude)
        delay(self.settle_time_ms * ms)

        total_v = 0.0
        i = 0
        while i < self.adc_averages:
            total_v += self.suservo0.get_adc(self.ADC_CHANNEL)
            delay(20 * us)
            i += 1
        return total_v / self.adc_averages

    def _voltage_to_power_nw(self, voltage_v: float) -> float:
        return (voltage_v - self.pd_voltage_offset_v) * self.pd_voltage_to_nw_gain

    def evaluate(self, params: dict[str, float]) -> float:
        self._ensure_artiq()
        amplitude = float(params["u3_dds_amp"])
        photodiode_v = float(self.measure_photodiode_voltage(amplitude))
        power_nw = self._voltage_to_power_nw(photodiode_v)
        error = power_nw - self.target_power_nw
        return -(error * error)

    def evaluate_and_record(self, amplitude: float) -> PowerMeasurement:
        self._ensure_artiq()
        photodiode_v = float(self.measure_photodiode_voltage(float(amplitude)))
        power_nw = self._voltage_to_power_nw(photodiode_v)
        error = power_nw - self.target_power_nw
        return PowerMeasurement(
            amplitude=float(amplitude),
            photodiode_v=photodiode_v,
            optical_power_nw=power_nw,
            objective=-(error * error),
        )

    def run(self):
        self._ensure_artiq()
        self._ensure_devices_present()
        self.init_hardware()

        best = run_bo(
            experiment=self,
            init_trials=self.init_trials,
            max_trials=self.max_trials,
            seed=self.seed,
        )
        print(f"Manual SUServo Urukul ADC BO complete: {best}")
