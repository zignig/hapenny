from functools import reduce

from amaranth import *
from amaranth.lib.wiring import *
from amaranth.lib.enum import *
from amaranth.lib.coding import Encoder, Decoder

from amaranth_soc.memory import MemoryMap

from hapenny import StreamSig, AlwaysReady, treeduce


class Widget(Component):
    # a wrapper for the peripherals
    _data_width = 16
    _count = 0
    _section = None
    w: In(0)  # faker to do component

    def __init__(self):
        super().__init__()
        self._registers = []

    def add_reg(self, name, reg):
        self._registers.append((name,))

    def _build(self):
        if hasattr(self, "_registers"):
            self._bit_width = len(self._registers).bit_length()
        else:
            self._bit_width = self._bits
        #print(type(self).__qualname__, self._bit_width, self._data_width)
        self._name = type(self).__qualname__ + "_" + str(type(self)._count)
        type(self)._count += 1
        if not hasattr(self, "_memory_map"):
            self._memory_map = MemoryMap(
                name=self._name, addr_width=self._bit_width, data_width=self._data_width
            )

        #print("build ", self)
        if hasattr(self, "_registers"):
            for i in self._registers:
                self._memory_map.add_resource(object(), name=i[0], size=1)

    def show(self):
        for i in self._memory_map.all_resources():
            print(i.name, i.start)


class TurboEncabulator(Widget):
    _section = "peripheral"

    def __init__(self, turbos):
        super().__init__()
        self.add_reg("TURBOS", object())
        self.add_reg("ACTIVATE", object())
        self.add_reg("STUFF", object())
        for i in range(turbos):
            self.add_reg("T" + str(i), object())


class Uart(Widget):
    _section = "peripheral"

    def __init__(self):
        super().__init__()
        self.add_reg("TX", object())
        self.add_reg("RX", object())
        print(type(self).__qualname__)


class FakeMem(Widget):
    _section = "memory"

    def __init__(self, size):
        bit_width = (size - 1).bit_length()
        self._bits = bit_width
        self._memory_map = MemoryMap(addr_width=bit_width, data_width=16)
        self._memory_map.add_resource(
            object(), name="mem_" + str(self._count), size=size
        )
        type(self)._count += 1


class ProgMem(FakeMem):
    _section = "progmem"


class WidgetFabric(Elaboratable):
    _section = "fabric"

    def __init__(self, name, devices):
        self._memory_map = MemoryMap(addr_width=32, data_width=16)
        self.name = name
        self._devices = devices
        self._sections = {}
        # build all the devices
        for d in devices:
            #print(self._sections, d)
            if d._section is not None:
                if d._section in self._sections:
                    self._sections[d._section].append(d)
                else:
                    self._sections[d._section] = [d]
            d._build()
        # for d in devices:
        #     print(d, d._bit_width)
        print(self._sections)
        for i, d in enumerate(devices):
            #print(i, d,d._name)
            self._memory_map.add_window(d._memory_map)

    def show(self):
        print()
        print("window patterns" + "-" * 30)
        for i in self._memory_map.window_patterns():
            print(i)
        print("windows" + "-" * 30)
        for i in self._memory_map.windows():
            print(i)
        print("resources" + "-" * 30)
        for i in self._memory_map.all_resources():
            print(i.name, i.start, i.end)


if __name__ == "__main__":
    uart = Uart()
    uart2 = Uart()
    uart3 = Uart()
    fm = FakeMem(1023)
    fm2 = ProgMem(512)
    te = TurboEncabulator(3)

    owf = WidgetFabric("test", [])
    wf = WidgetFabric("base", [fm, fm2, uart, uart2, uart3, te])
    wf.show()
