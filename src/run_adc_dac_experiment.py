"""Example ARTIQ entrypoint: ADC/DAC Bayesian optimization experiment."""

from __future__ import annotations

from dataclasses import dataclass

from hardware_driver import (
    ARTIQ_AVAILABLE,
    ConfigurableBOExperiment,
    delay,
    kernel,
    ms,
    us,
)


@dataclass
class MeasurementResult:
    setpoint_v: float
    measured_v: float
    objective: float


class ADCDACExperiment(ConfigurableBOExperiment):
    """Example ADC/DAC BO experiment using Zotino and Sampler.

    This example auto-builds CONFIG from device_db + description JSON.
    """

    DESCRIPTION_PATH = "src/adc_dac_description.json"
    DEVICE_DB_PATH = "device_db.py"

    def prepare(self):
        super().prepare()
        if not ARTIQ_AVAILABLE:
            return
        self._sample_buffer = [0.0] * 8

    @kernel
    def init_hardware(self):
        core = getattr(self, self.device_roles["core"])
        dac = getattr(self, self.device_roles["dac"])
        adc = getattr(self, self.device_roles["adc"])

        core.reset()
        core.break_realtime()

        dac.init()
        delay(1 * ms)

        adc.init()
        delay(5 * ms)
        adc.set_gain_mu(self.adc_channel, 0)
        delay(100 * us)

    @kernel
    def measure_once(self, dac_voltage: float) -> float:
        core = getattr(self, self.device_roles["core"])
        dac = getattr(self, self.device_roles["dac"])
        adc = getattr(self, self.device_roles["adc"])

        core.break_realtime()

        if dac_voltage > 10.0:
            dac_voltage = 10.0
        if dac_voltage < -10.0:
            dac_voltage = -10.0

        dac.set_dac([dac_voltage], [self.dac_channel])
        delay(200 * us)
        adc.sample(self._sample_buffer)
        return self._sample_buffer[self.adc_channel]

    def setup_bo_run(self) -> None:
        self.init_hardware()

    def evaluate(self, params: dict[str, float]) -> float:
        self._ensure_artiq()
        setpoint = float(params["dac_voltage"])
        measured = float(self.measure_once(setpoint))
        error = measured - float(self.target_voltage)
        return -(error * error)

    def evaluate_and_record(self, setpoint_v: float) -> MeasurementResult:
        self._ensure_artiq()
        measured = float(self.measure_once(float(setpoint_v)))
        error = measured - float(self.target_voltage)
        return MeasurementResult(
            setpoint_v=float(setpoint_v),
            measured_v=measured,
            objective=-(error * error),
        )
