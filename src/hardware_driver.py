"""General ARTIQ scaffolding for Bayesian optimization experiments."""

from __future__ import annotations

from typing import Any

from main import Parameter, run as run_bo

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


class DeviceSpec:
    """ARTIQ device to bind with setattr_device()."""

    def __init__(self, name: str):
        self.name = name


class ChannelSpec:
    """Integer-valued channel argument (e.g. dac_channel, adc_channel)."""

    def __init__(self, name: str, default: int = 0, minimum: int = 0, maximum: int = 31):
        self.name = name
        self.default = default
        self.minimum = minimum
        self.maximum = maximum


class NumericArgSpec:
    """Numeric host argument exposed with NumberValue."""

    def __init__(
        self,
        name: str,
        default: float,
        minimum: float | None = None,
        maximum: float | None = None,
        unit: str | None = None,
        integer: bool = False,
        step: float | None = None,
    ):
        self.name = name
        self.default = default
        self.minimum = minimum
        self.maximum = maximum
        self.unit = unit
        self.integer = integer
        self.step = step


class BOExperimentConfig:
    """Declarative config used to build a BO experiment."""

    def __init__(
        self,
        devices: list[DeviceSpec] | None = None,
        channels: list[ChannelSpec] | None = None,
        parameters: list[Parameter] | None = None,
        data_arguments: list[NumericArgSpec] | None = None,
    ):
        self.devices = [] if devices is None else devices
        self.channels = [] if channels is None else channels
        self.parameters = [] if parameters is None else parameters
        self.data_arguments = [] if data_arguments is None else data_arguments


class ConfigurableBOExperiment(EnvExperiment):
    """General BO runner.

    Users configure experiment shape declaratively through CONFIG and then
    override only hardware-specific hooks.
    """

    CONFIG = BOExperimentConfig()

    def _ensure_artiq(self) -> None:
        if not ARTIQ_AVAILABLE:
            raise RuntimeError(
                "ARTIQ is not available in this Python environment. "
                f"Import error: {ARTIQ_IMPORT_ERROR}"
            )

    def _number_value_for(self, spec: NumericArgSpec) -> NumberValue:
        kwargs: dict[str, Any] = {"default": spec.default}
        if spec.minimum is not None:
            kwargs["min"] = spec.minimum
        if spec.maximum is not None:
            kwargs["max"] = spec.maximum
        if spec.unit is not None:
            kwargs["unit"] = spec.unit
        if spec.step is not None:
            kwargs["step"] = spec.step
        if spec.integer:
            kwargs["ndecimals"] = 0
        return NumberValue(**kwargs)

    def build(self):
        if not ARTIQ_AVAILABLE:
            return

        for device in self.CONFIG.devices:
            self.setattr_device(device.name)

        for channel in self.CONFIG.channels:
            self.setattr_argument(
                channel.name,
                NumberValue(
                    default=channel.default,
                    min=channel.minimum,
                    max=channel.maximum,
                    step=1,
                    ndecimals=0,
                ),
            )

        for argument in self.CONFIG.data_arguments:
            self.setattr_argument(argument.name, self._number_value_for(argument))

        self.setattr_argument("init_trials", NumberValue(default=5, step=1, ndecimals=0, min=1))
        self.setattr_argument("max_trials", NumberValue(default=30, step=1, ndecimals=0, min=1))
        self.setattr_argument("seed", NumberValue(default=123, step=1, ndecimals=0, min=0))

    def prepare(self):
        if not ARTIQ_AVAILABLE:
            return

        for channel in self.CONFIG.channels:
            setattr(self, channel.name, int(getattr(self, channel.name)))

        for argument in self.CONFIG.data_arguments:
            current = getattr(self, argument.name)
            casted = int(current) if argument.integer else float(current)
            setattr(self, argument.name, casted)

        self.init_trials = int(self.init_trials)
        self.max_trials = int(self.max_trials)
        self.seed = int(self.seed)

    def parameter_space(self) -> list[Parameter]:
        if not self.CONFIG.parameters:
            raise RuntimeError("CONFIG.parameters must include at least one Parameter.")
        return self.CONFIG.parameters

    def setup_bo_run(self) -> None:
        """Optional setup hook called once before the BO loop."""

    def evaluate(self, params: dict[str, float]) -> float:
        raise NotImplementedError("Subclasses must implement evaluate(params).")

    def run(self):
        self._ensure_artiq()
        self.setup_bo_run()

        best = run_bo(
            experiment=self,
            init_trials=self.init_trials,
            max_trials=self.max_trials,
            seed=self.seed,
        )
        print(f"Hardware BO complete: {best}")
