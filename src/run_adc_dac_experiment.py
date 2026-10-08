"""Example BO experiment: drive a Zotino DAC to hit a target voltage on a Sampler ADC.

Copy this file as the starting point for a new experiment.

    artiq_run src/run_adc_dac_experiment.py --device-db src/device_db.py
"""

from artiq.experiment import NumberValue, delay, kernel, ms, us

from artiq_bo import BOExperiment
from bo import Parameter


class ADCDACExperiment(BOExperiment):
    def build(self):
        super().build()
        self.setattr_device("core")
        self.setattr_device("zotino0")
        self.setattr_device("sampler0")
        self.setattr_argument("dac_channel", NumberValue(0, min=0, max=31, step=1, precision=0))
        self.setattr_argument("adc_channel", NumberValue(0, min=0, max=7, step=1, precision=0))
        self.setattr_argument("target_voltage", NumberValue(1.0, min=-10.0, max=10.0, unit="V"))

    def prepare(self):
        self.dac_channel = int(self.dac_channel)
        self.adc_channel = int(self.adc_channel)
        self._sample_buffer = [0.0] * 8

    def parameter_space(self):
        return [Parameter("dac_voltage", (1.5, 1.6))]

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

    def setup(self):
        self.init_hardware()

    def evaluate(self, params):
        measured = self.measure_once(params["dac_voltage"])
        print(f"  measured_v={measured:.6f}")
        return -(measured - self.target_voltage) ** 2
