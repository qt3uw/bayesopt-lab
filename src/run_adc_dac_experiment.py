"""Example ARTIQ entrypoint: ADC/DAC Bayesian optimization experiment."""

from __future__ import annotations

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


class MeasurementResult:
    def __init__(self, setpoint_v: float, measured_v: float, objective: float):
        self.setpoint_v = setpoint_v
        self.measured_v = measured_v
        self.objective = objective


class ADCDACExperiment(ConfigurableBOExperiment):
    """Example ADC/DAC BO experiment using Zotino and Sampler.

    Override CONFIG and evaluate() for custom experiments.
    """

    CONFIG = BOExperimentConfig(
        devices=[DeviceSpec("core"), DeviceSpec("zotino0"), DeviceSpec("sampler0")],
        channels=[
            ChannelSpec("dac_channel", default=0, minimum=0, maximum=31),
            ChannelSpec("adc_channel", default=0, minimum=0, maximum=7),
        ],
        parameters=[Parameter("dac_voltage", (1.5, 1.6))],
        data_arguments=[
            NumericArgSpec("target_voltage", default=1.0, minimum=-10.0, maximum=10.0, unit="V"),
            NumericArgSpec(
                "initial_dac_voltage", default=0.0, minimum=-10.0, maximum=10.0, unit="V"
            ),
        ],
    )

    def prepare(self):
        super().prepare()
        if not ARTIQ_AVAILABLE:
            return
        self._sample_buffer = [0.0] * 8

    @kernel
    def init_hardware(self):
        self.core.reset()
        self.core.break_realtime()

        self.zotino0.init()
        delay(1 * ms)

        self.sampler0.init()
        delay(5 * ms)
        self.sampler0.set_gain_mu(self.adc_channel, 0)
        delay(100 * us)

    @kernel
    def measure_once(self, dac_voltage: float) -> float:
        self.core.break_realtime()

        if dac_voltage > 10.0:
            dac_voltage = 10.0
        if dac_voltage < -10.0:
            dac_voltage = -10.0

        self.zotino0.set_dac([dac_voltage], [self.dac_channel])
        delay(200 * us)
        self.sampler0.sample(self._sample_buffer)
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
