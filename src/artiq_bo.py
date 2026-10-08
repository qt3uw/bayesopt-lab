"""Base class that wires an ARTIQ experiment into the BO loop in bo.py."""

from artiq.experiment import EnvExperiment, NumberValue

from bo import run as run_bo


class BOExperiment(EnvExperiment):
    """Subclass this; see run_adc_dac_experiment.py for a complete example.

    Implement:
      build()            call super().build(), then setattr_device/setattr_argument as usual
      parameter_space()  return list[Parameter] the optimizer may vary
      evaluate(params)   set hardware to params, measure, return objective (higher is better)
    Optional:
      setup()            one-time hardware init before the loop
      teardown()         always runs after the loop (close instruments here)
    """

    def build(self):
        self.setattr_argument("init_trials", NumberValue(5, min=1, step=1, precision=0), group="BO")
        self.setattr_argument("max_trials", NumberValue(30, min=1, step=1, precision=0), group="BO")
        self.setattr_argument("seed", NumberValue(123, min=0, step=1, precision=0), group="BO")

    def setup(self):
        pass

    def teardown(self):
        pass

    def run(self):
        self.setup()
        try:
            self.best = run_bo(
                experiment=self,
                init_trials=int(self.init_trials),
                max_trials=int(self.max_trials),
                seed=int(self.seed),
            )
        finally:
            self.teardown()
