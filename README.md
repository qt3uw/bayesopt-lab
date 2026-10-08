# bayesopt-lab

Minimal Bayesian optimization for ARTIQ lab hardware.

- `src/bo.py` — the optimizer (Gaussian Process + Upper Confidence Bound). No hardware deps. `python src/bo.py` runs a synthetic self-check.
- `src/artiq_bo.py` — `BOExperiment`, the ARTIQ base class that runs the BO loop.
- `src/run_adc_dac_experiment.py` — smallest hardware example; copy it to start a new experiment.
- `src/laser_power_cal.py` — laser power calibration (SUServo DDS + Thorlabs power meter).

## Adding an experiment

```python
from artiq.experiment import NumberValue, kernel
from artiq_bo import BOExperiment
from bo import Parameter

class MyExperiment(BOExperiment):
    def build(self):
        super().build()                      # adds init_trials / max_trials / seed
        self.setattr_device("core")
        self.setattr_argument("target", NumberValue(1.0))

    def parameter_space(self):               # what the optimizer may vary, in physical units
        return [Parameter("voltage", (0.0, 1.0))]

    def setup(self):                         # optional: one-time hardware init
        ...

    def evaluate(self, params):              # set hardware, measure, return objective
        measured = self.measure(params["voltage"])
        return -(measured - self.target) ** 2   # higher is better
```

Run it: `artiq_run src/my_experiment.py --device-db src/device_db.py`

Override `teardown()` to close instruments; it runs even if the loop crashes.
`device_db.py` is machine-specific and git-ignored.
