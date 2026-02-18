from artiq.experiment import *

class DACandADCTest(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.setattr_device("zotino0")
        self.setattr_device("sampler0")
        self.setattr_argument("dac_channel", NumberValue(default=0, step=1, ndecimals=0, min=0, max=31))
        self.setattr_argument("adc_channel", NumberValue(default=0, step=1, ndecimals=0, min=0, max=7))
        self.setattr_argument("test_voltage", NumberValue(default=5.0, unit="V", min=-10.0, max=10.0))
    
    def prepare(self):
        self.smp = [0.0]*8

    @kernel
    def run(self):
        self.core.reset()
        self.core.break_realtime()
        
        self.sampler0.init()
        delay(50*ms)
        
        for i in range(8):
            self.sampler0.set_gain_mu(i, 0)
            delay(10000*us)
        
        self.sampler0.sample(self.smp)
        delay(10000*us)  # Wait for sampling to complete
        
        # Print results
        # print("="*60)
        print(self.smp)
        # print("="*60))
        # print("="*60)
    # def prepare(self):
    #     self.dac_channel = int(self.dac_channel)
    #     self.adc_channel = int(self.adc_channel)
    #     self._sample_buffer = [0.0] * 8
    
    # @kernel
    # def measure(self):
    #     self.core.reset()
    #     self.core.break_realtime()
        
    #     # Initialize Zotino DAC
    #     self.zotino0.init()
    #     delay(1*ms)
        
    #     # Initialize Sampler ADC
    #     self.sampler0.init()
    #     delay(10*ms)
        
    #     # Set unity gain on ADC channel
    #     self.sampler0.set_gain_mu(self.adc_channel, 0)
    #     delay(500*us)
        
    #     # Set DAC output voltage
    #     self.zotino0.set_dac([self.test_voltage], [self.dac_channel])
    #     self.zotino0.load()  # Critical: Actually load the DAC values
    #     delay(5*ms)  # Increased: Allow DAC to settle
        
    #     # Read ADC - this is asynchronous!
    #     self.sampler0.sample(self._sample_buffer)
    #     delay(1*ms)  # Critical: Wait for sampling to complete
        
    #     return self._sample_buffer[self.adc_channel]
    
    # def run(self):
    #     measured_voltage = self.measure()
    #     print("="*50)
    #     print("DAC Channel %d: Set to %.3f V" % (self.dac_channel, self.test_voltage))
    #     print("ADC Channel %d: Measured %.3f V" % (self.adc_channel, measured_voltage))
    #     print("="*50)
    #     print("")
    #     print("Use multimeter to verify:")
    #     print("  - DAC output on channel %d" % self.dac_channel)
    #     print("  - Connect DAC to ADC for loopback test")