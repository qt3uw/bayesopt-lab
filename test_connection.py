from artiq.experiment import *
import numpy as np

class DACandADCTest(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.setattr_device("zotino0")
        self.setattr_device("sampler0")
        self.setattr_argument("dac_channel", NumberValue(default=0, step=1, ndecimals=0, min=0, max=31))
        self.setattr_argument("adc_channel", NumberValue(default=0, step=1, ndecimals=0, min=0, max=7))
        self.setattr_argument("test_voltage", NumberValue(default=5.0, unit="V", min=-10.0, max=10.0))
    
    def prepare(self):
        # self.smp = np.array([0.0] * 8)
        self.smp = [0] * 8
    
    @kernel
    def run(self):
        self.core.reset()

        self.sampler0.init()
        self.core.break_realtime()
        delay(10*ms)

        for i in range(8):
            self.sampler0.set_gain_mu(i, 0)

        self.core.break_realtime()

        data = [0, 0]   # minimal even length
        self.sampler0.sample_mu(data)

        print(data)

    # @kernel
    # def run(self):
    #     """
    #     Verify that cnv works and exists in the gateware
        
    #     """
    #     self.core.reset()
    #     self.sampler0.init()
    #     self.core.break_realtime()

    #     self.sampler0.cnv.pulse(1*us)

    # @kernel
    # def run(self):
    #     """
    #     Verify that we can read the ADC bus at all.
    #     """
        
    #     self.core.reset()
    #     self.sampler0.init()
    #     self.core.break_realtime()

    #     self.sampler0.bus_adc.write(0)
    #     x = self.sampler0.bus_adc.read()
    #     print(x)

