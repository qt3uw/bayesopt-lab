"""Calibrate laser power by optimizing SUServo DDS amplitude from power meter readout.

DDS frequency is fixed; only RF amplitude varies. Optical power is read directly
from a Thorlabs power meter.

MAKE SURE TO CHECK WAVELENGTH_NM, DEFAULT DDS FREQ, DEFAULT TARGET POWER

    artiq_run src/laser_power_cal.py --device-db src/device_db.py
"""

import time
from ctypes import byref, c_bool, c_double, c_int, c_int16, c_uint32, create_string_buffer

from artiq.experiment import EnumerationValue, MHz, NumberValue, delay, kernel, us

from artiq_bo import BOExperiment
from bo import Parameter
from TLPMX import TLPM_DEFAULT_CHANNEL, TLPMX

WAVELENGTH_NM = 633  # must match the power meter calibration wavelength
DDS_PROFILE = 3
AMPLITUDE_BOUNDS = (0.05, 0.30)


def open_power_meter() -> TLPMX:
    """Open the first Thorlabs power meter found, set to watts at WAVELENGTH_NM."""
    resource_name = create_string_buffer(1024)
    device_count = c_uint32()
    meter = TLPMX()
    meter.findRsrc(byref(device_count))
    meter.getRsrcName(c_int(0), resource_name)
    meter.open(resource_name, c_bool(True), c_bool(True))
    meter.setWavelength(c_double(WAVELENGTH_NM), TLPM_DEFAULT_CHANNEL)
    meter.setPowerUnit(c_int16(0), TLPM_DEFAULT_CHANNEL)  # 0 = Watts
    return meter


class LaserPowerCalibration(BOExperiment):
    def build(self):
        super().build()
        self.setattr_device("core")
        self.setattr_device("suservo0")
        self.setattr_device("suservo0_ch3")
        self.setattr_argument("aom_enabled", EnumerationValue(["on", "off"], default="on"))
        self.setattr_argument(
            "dds_frequency_hz",
            NumberValue(200 * MHz, min=1 * MHz, max=400 * MHz, step=1 * MHz, unit="Hz"),
        )
        self.setattr_argument("target_power_nw", NumberValue(10.0, min=0.0, max=1e9))
        self.setattr_argument("settle_time_s", NumberValue(1.0, min=0.1, max=1.0, unit="s"))
        self.setattr_argument("meter_averages", NumberValue(8, min=1, max=1024, step=1, precision=0))

    def prepare(self):
        self.meter_averages = int(self.meter_averages)
        self._aom_enabled = 1 if self.aom_enabled == "on" else 0

    def parameter_space(self):
        return [Parameter("dds_amplitude", AMPLITUDE_BOUNDS)]

    @kernel
    def configure_dds_output(self, amplitude: float):
        self.core.break_realtime()
        self.suservo0.init()
        if amplitude < 0.0:
            amplitude = 0.0
        if amplitude > 1.0:
            amplitude = 1.0
        self.suservo0_ch3.set_dds(
            profile=DDS_PROFILE,
            frequency=self.dds_frequency_hz,
            offset=0.0,
            phase=0.0,
        )
        self.suservo0.set_config(enable=1)
        self.suservo0_ch3.set_y(DDS_PROFILE, amplitude)
        delay(100 * us)

    @kernel
    def aom_on(self):
        self.suservo0_ch3.set(en_out=1, en_iir=0, profile=DDS_PROFILE)

    @kernel
    def aom_off(self):
        self.suservo0_ch3.set(en_out=0, en_iir=0, profile=DDS_PROFILE)

    @kernel
    def init_hardware(self):
        self.core.reset()
        self.core.break_realtime()
        self.configure_dds_output(0.0)
        if self._aom_enabled == 1:
            self.aom_on()
        else:
            self.aom_off()

    @kernel
    def set_dds_amplitude(self, amplitude: float):
        self.core.break_realtime()
        if amplitude < 0.0:
            amplitude = 0.0
        if amplitude > 1.0:
            amplitude = 1.0
        self.suservo0_ch3.set_y(DDS_PROFILE, amplitude)

    def measure_power_nw(self, amplitude: float) -> float:
        self.set_dds_amplitude(amplitude)
        time.sleep(self.settle_time_s)
        power = c_double()
        total = 0.0
        for _ in range(self.meter_averages):
            self.meter.measPower(byref(power), TLPM_DEFAULT_CHANNEL)
            total += power.value
        return total / self.meter_averages * 1e9  # W -> nW

    def setup(self):
        print(
            f"Laser power cal: target={self.target_power_nw:.3f} nW, "
            f"dds_freq={self.dds_frequency_hz:.0f} Hz, amplitude_bounds={AMPLITUDE_BOUNDS}, "
            f"wavelength={WAVELENGTH_NM} nm, settle={self.settle_time_s} s, averages={self.meter_averages}"
        )
        self.init_hardware()
        self.meter = open_power_meter()

    def teardown(self):
        self.meter.close()

    def evaluate(self, params):
        power_nw = self.measure_power_nw(params["dds_amplitude"])
        print(f"  power_nw={power_nw:.3f}")
        return -(power_nw - self.target_power_nw) ** 2
