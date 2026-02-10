"""ARTIQ entrypoint: run minimal BO loop against Zotino->Sampler hardware."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from main import Parameter, run as run_bo


_ARTIQ_DRIVER_PATH = Path(__file__).with_name("artiq.py")
_SPEC = spec_from_file_location("local_artiq_driver", _ARTIQ_DRIVER_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Failed to load local ARTIQ driver module at {_ARTIQ_DRIVER_PATH}")
_DRIVER = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_DRIVER)

ARTIQ_AVAILABLE = _DRIVER.ARTIQ_AVAILABLE
NumberValue = _DRIVER.NumberValue
ZotinoSamplerExperiment = _DRIVER.ZotinoSamplerExperiment


class HardwareBORunner(ZotinoSamplerExperiment):
    """Wraps ZotinoSamplerExperiment with BO loop controls."""

    def build(self):
        super().build()
        if not ARTIQ_AVAILABLE:
            return

        self.setattr_argument("init_trials", NumberValue(default=5, step=1, ndecimals=0, min=1))
        self.setattr_argument("max_trials", NumberValue(default=30, step=1, ndecimals=0, min=1))
        self.setattr_argument("seed", NumberValue(default=123, step=1, ndecimals=0, min=0))

    def prepare(self):
        super().prepare()
        if not ARTIQ_AVAILABLE:
            return

        self.init_trials = int(self.init_trials)
        self.max_trials = int(self.max_trials)
        self.seed = int(self.seed)

    def run(self):
        self._ensure_artiq()

        self.init_hardware()
        best = run_bo(
            parameters=[Parameter("dac_voltage", (-10.0, 10.0))],
            init_trials=self.init_trials,
            max_trials=self.max_trials,
            seed=self.seed,
            objective_fn=self.evaluate_for_params,
        )
        print(f"Hardware BO complete: {best}")
