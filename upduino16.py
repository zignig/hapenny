# This is a very simple demo system for the UPduino v3 board. This will
#
# 1. Synthesize a hapenny CPU, minimal RAM, and a single-bit GPIO port
# 2. Initialize the RAM with a program that blinks the GPIO port
# 3. Wire that port to the green LED on the UPduino
# 4. Program the attached UPduino.
#
# You should then see the green LED blinking.

import itertools
import argparse

from amaranth import *
from amaranth.lib.wiring import *
from amaranth.build import ResourceError, Resource, Pins, Attrs
from amaranth_boards.upduino_v3 import UpduinoV3Platform

from hapenny import StreamSig
from hapenny.cpu16 import Cpu
from hapenny.bus import BusPort, SimpleFabric, partial_decode
from hapenny.gpio import OutputPort
from hapenny.mem import BasicMemory

RAM_WORDS = 256 * 1
RAM_ADDR_BITS = (RAM_WORDS - 1).bit_length()

BUS_ADDR_BITS = RAM_ADDR_BITS + 1

print(f"configuring for {RAM_ADDR_BITS}-bit RAM and {BUS_ADDR_BITS}-bit bus")

class Test(Elaboratable):
    def elaborate(self, platform):
        m = Module()

        m.submodules.cpu = cpu = Cpu(
            # +1 to adjust from bus halfword addressing to CPU byte addressing.
            addr_width = BUS_ADDR_BITS + 1,
        )
        m.submodules.mem = mem = BasicMemory(depth = RAM_WORDS, contents = [
            # 00000000 <reset>:
            #    0:   20000293                li      t0,512
            0x0293,
            0x2000,
            #    4:   00100313                li      t1,1
            0x0313,
            0x0010,
            #    8:   0004f3b7                lui     t2,0x4f
            0xf3b7,
            0x0004,
            # 
            # 0000000c <loop>:
            #    c:   00629023                sh      t1,0(t0)
            0x9023,
            0x0062,
            #   10:   00038e13                mv      t3,t2
            0x8e13,
            0x0003,
            # 
            # 00000014 <loop2>:
            #   14:   fffe0e13                addi    t3,t3,-1
            0x0e13,
            0xfffe,
            #   18:   fe0e1ee3                bnez    t3,14 <loop2>
            0x1ee3,
            0xfe0e,
            #   1c:   00029023                sh      zero,0(t0)
            0x9023,
            0x0002,
            #   20:   00038e13                mv      t3,t2
            0x8e13,
            0x0003,
            # 
            # 00000024 <loop3>:
            #   24:   fffe0e13                addi    t3,t3,-1
            0x0e13,
            0xfffe,
            #   28:   fe0e1ee3                bnez    t3,24 <loop3>
            0x1ee3,
            0xfe0e,
            #   2c:   fe1ff06f                j       c <loop>
            0xf06f,
            0xfe1f,
        ])
        m.submodules.port = port = OutputPort(1)
        m.submodules.fabric = fabric = SimpleFabric([
            mem.bus,
            # Extend the GPIO port's address bus to match the RAM.
            partial_decode(m, port.bus, RAM_ADDR_BITS),
        ])

        connect(m, cpu.bus, fabric.bus)
        platform.add_resources([
            Resource("pmod", 0, Pins("7 8 9 10", dir="o", conn=("j", 0))),
        ])
        def get_all_resources(name):
            resources = []
            for number in itertools.count():
                try:
                    resources.append(platform.request(name, number))
                except ResourceError:
                    break
            return resources

        pmod = platform.request("pmod", 0)

        rgb_led = platform.request("rgb_led", 0)
        m.d.comb += [
            rgb_led.r.o.eq(cpu.halted),
            rgb_led.g.o.eq(port.pins[0]),
        ]

        return m

p = UpduinoV3Platform()
p.hfosc_div = 1
p.build(Test(), do_program = True)
