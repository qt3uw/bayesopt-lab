"""ARTIQ entrypoint: optimize Urukul amplitude from Sampler photodiode readout."""

from __future__ import annotations

from dataclasses import dataclass

from main import Parameter
from hardware_driver import (
    ARTIQ_AVAILABLE,
    BOExperimentConfig,
    ChannelSpec,
    ConfigurableBOExperiment,
    DeviceSpec,
    NumericArgSpec,
    delay,
    kernel,
    ms,
    us,
)


@dataclass
class PowerMeasurement:
    amplitude: float
    photodiode_v: float
    optical_power_nw: float
    objective: float


class UrukulSamplerPowerBOExperiment(ConfigurableBOExperiment):
    """Bayesian optimization for Urukul amplitude using Sampler photodiode voltage."""

    CONFIG = BOExperimentConfig(
        devices=[
            DeviceSpec("core"),
            DeviceSpec("urukul0_cpld"),
            DeviceSpec("urukul0_dds"),
            DeviceSpec("sampler0"),
        ],
        channels=[
            ChannelSpec("adc_channel", default=0, minimum=0, maximum=7),
        ],
        parameters=[
            Parameter("urukul_amplitude", (0.05, 0.95)),
        ],
        data_arguments=[
            NumericArgSpec("rf_frequency_hz", default=80e6, minimum=1e6, maximum=400e6, unit="Hz"),
            NumericArgSpec("rf_phase_turns", default=0.0, minimum=0.0, maximum=1.0),
            NumericArgSpec("target_power_nw", default=1000.0, minimum=0.0, maximum=1e9),
            NumericArgSpec("pd_voltage_offset_v", default=0.0, minimum=-10.0, maximum=10.0, unit="V"),
            NumericArgSpec("pd_voltage_to_nw_gain", default=1e6, minimum=0.0, maximum=1e12),
            NumericArgSpec("settle_time_ms", default=1.0, minimum=0.01, maximum=1000.0, unit="ms"),
            NumericArgSpec("adc_averages", default=8, minimum=1, maximum=1024, integer=True),
        ],
    )

    def prepare(self):
        super().prepare()
        if not ARTIQ_AVAILABLE:
            return
        self._sample_buffer = [0.0] * 8

    def _ensure_devices_present(self) -> None:
        missing = [name for name in ("core", "urukul0_cpld", "urukul0_dds", "sampler0") if not hasattr(self, name)]
        if missing:
            raise RuntimeError(
                "Missing required devices in device_db for this experiment: "
                f"{missing}. Add the missing entries to src/device_db.py."
            )

    @kernel
    def init_hardware(self):
        self.core.reset()
        self.core.break_realtime()

        self.urukul0_cpld.init()
        self.urukul0_dds.init()
        self.urukul0_dds.sw.off()
        delay(1 * ms)

        self.sampler0.init()
        delay(5 * ms)
        self.sampler0.set_gain_mu(self.adc_channel, 0)
        delay(100 * us)

    @kernel
    def measure_photodiode_voltage(self, amplitude: float) -> float:
        self.core.break_realtime()

        if amplitude < 0.0:
            amplitude = 0.0
        if amplitude > 1.0:
            amplitude = 1.0

        self.urukul0_dds.set(self.rf_frequency_hz, phase=self.rf_phase_turns, amplitude=amplitude)
        self.urukul0_dds.sw.on()
        delay(self.settle_time_ms * ms)

        total = 0.0
        n = int(self.adc_averages)
        i = 0
        while i < n:
            self.sampler0.sample(self._sample_buffer)
            total += self._sample_buffer[self.adc_channel]
            delay(20 * us)
            i += 1
        return total / n

    def setup_bo_run(self) -> None:
        self._ensure_devices_present()
        self.init_hardware()

    def _voltage_to_power_nw(self, voltage_v: float) -> float:
        # Linear photodiode calibration model.
        return (voltage_v - float(self.pd_voltage_offset_v)) * float(self.pd_voltage_to_nw_gain)

    def evaluate(self, params: dict[str, float]) -> float:
        self._ensure_artiq()
        amplitude = float(params["urukul_amplitude"])
        photodiode_v = float(self.measure_photodiode_voltage(amplitude))
        power_nw = self._voltage_to_power_nw(photodiode_v)
        error = power_nw - float(self.target_power_nw)
        return -(error * error)

    def evaluate_and_record(self, amplitude: float) -> PowerMeasurement:
        self._ensure_artiq()
        photodiode_v = float(self.measure_photodiode_voltage(float(amplitude)))
        power_nw = self._voltage_to_power_nw(photodiode_v)
        error = power_nw - float(self.target_power_nw)
        return PowerMeasurement(
            amplitude=float(amplitude),
            photodiode_v=photodiode_v,
            optical_power_nw=power_nw,
            objective=-(error * error),
        )
