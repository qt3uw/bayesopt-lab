"""Minimal ARTIQ DAC->ADC driver for Bayesian optimization experiments.

This module is intentionally small:
- Write one zotino0 DAC channel.
- Read one sampler0 ADC channel.
- Return a scalar objective based on a target voltage.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from artiq.experiment import EnvExperiment, NumberValue, delay, kernel, ms, us

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

    def kernel(func):  # type: ignore[override]
        return func

    def delay(_):  # type: ignore[override]
        return None

    ms = 1e-3
    us = 1e-6

class MeasurementResult:
    def __init__(self, setpoint_v: float, measured_v: float, objective: float):
        self.setpoint_v = setpoint_v
        self.measured_v = measured_v
        self.objective = objective


class ZotinoSamplerExperiment(EnvExperiment):
    """Single-channel DAC->ADC experiment for quick hardware BO tests."""

    def build(self):
        if not ARTIQ_AVAILABLE:
            return

        self.setattr_device("core")
        self.setattr_device("zotino0")
        self.setattr_device("sampler0")

        self.setattr_argument("dac_channel", NumberValue(default=0, step=1, ndecimals=0))
        self.setattr_argument("adc_channel", NumberValue(default=0, step=1, ndecimals=0))
        self.setattr_argument(
            "target_voltage", NumberValue(default=1.0, unit="V", min=-10.0, max=10.0)
        )
        self.setattr_argument(
            "initial_dac_voltage", NumberValue(default=0.0, unit="V", min=-10.0, max=10.0)
        )

    def prepare(self):
        if not ARTIQ_AVAILABLE:
            return

        self.dac_channel = int(self.dac_channel)
        self.adc_channel = int(self.adc_channel)
        self._sample_buffer = [0.0] * 8

    def _ensure_artiq(self) -> None:
        if not ARTIQ_AVAILABLE:
            raise RuntimeError(
                "ARTIQ is not available in this Python environment. "
                f"Import error: {ARTIQ_IMPORT_ERROR}"
            )

    @kernel
    def init_hardware(self):
        self.core.reset()
        self.core.break_realtime()

        self.zotino0.init()
        delay(1 * ms)

        self.sampler0.init()
        delay(5 * ms)

        # Unity gain (mu=0) on selected ADC channel.
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

    def evaluate_for_params(self, params: dict[str, float]) -> float:
        """Host-side objective callable shape compatible with your BO loop."""
        self._ensure_artiq()

        setpoint = float(params["dac_voltage"])
        measured = float(self.measure_once(setpoint))
        error = measured - float(self.target_voltage)
        return -(error * error)

    def evaluate_and_record(self, setpoint_v: float) -> MeasurementResult:
        """Convenience method if you want measured voltage alongside objective."""
        self._ensure_artiq()

        measured = float(self.measure_once(float(setpoint_v)))
        error = measured - float(self.target_voltage)
        return MeasurementResult(
            setpoint_v=float(setpoint_v),
            measured_v=measured,
            objective=-(error * error),
        )

    def run(self):
        self._ensure_artiq()

        self.init_hardware()
        result = self.evaluate_and_record(float(self.initial_dac_voltage))
        print(
            "DAC={:.4f} V, ADC={:.4f} V, objective={:.6f}".format(
                result.setpoint_v, result.measured_v, result.objective
            )
        )


def make_hardware_objective(experiment: ZotinoSamplerExperiment):
    """Returns a function: f({'dac_voltage': ...}) -> objective."""

    def objective(params: dict[str, float]) -> float:
        return experiment.evaluate_for_params(params)

    return objective
