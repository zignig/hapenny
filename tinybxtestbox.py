import itertools
import argparse
import struct
from pathlib import Path

from amaranth import *
from amaranth.lib.wiring import *
from amaranth.build import ResourceError, Resource, Pins, Attrs
from amaranth_boards.test.blinky import Blinky
from amaranth_boards.resources.interface import UARTResource
from amaranth_boards.tinyfpga_bx import TinyFPGABXPlatform
import amaranth.lib.cdc

from hapenny import StreamSig
from hapenny.cpu import Cpu
from hapenny.bus import BusPort, SimpleFabric, partial_decode
from hapenny.serial import BidiUart
from hapenny.mem import BasicMemory

import logging
from rich.logging import RichHandler

FORMAT = "%(message)s"

logging.basicConfig(
    level="DEBUG", format=FORMAT, datefmt="[%X]", handlers=[RichHandler()]
)

log = logging.getLogger("rich")
log.info("TinyFPGA_BX")

develop = False

### Development harness 

class warmboot(Elaboratable):
    # Warmboot with internal / external mux.
    def __init__(self):
        log.info("Create Warmboot")
        self.image = Signal(2, reset=1)
        self.boot = Signal()

        self.ext_image = Signal(2)
        self.ext_boot = Signal()

        self.select = Signal()

    def elaborate(self, platform):
        m = Module()
        image_internal = Signal(2)
        boot_internal = Signal()
        m.submodules.wb = Instance(
            "SB_WARMBOOT",
            i_S1=image_internal[1],
            i_S0=image_internal[0],
            i_BOOT=boot_internal,
        )
        # TODO fix the internal selector
        m.d.comb += [
            image_internal.eq(Mux(self.select, self.ext_image, self.image)),
            boot_internal.eq(Mux(self.select, self.ext_boot, self.boot)),
        ]
        return m

# tiny-bootloader is written in a high-level language and needs to have a stack,
BOOT_ROM_WORDS = 256
BOOT_ROM_ADDR_BITS = (BOOT_ROM_WORDS - 1).bit_length()
RAM_ADDR_BITS =  31

bootloader = Path("icolarge-bootloader.bin").read_bytes()
boot_image = struct.unpack("<" + "H" * (len(bootloader) // 2), bootloader)

assert len(boot_image) <= BOOT_ROM_WORDS, \
        f"bootloader is {len(boot(image))} words long, too big for boot ROM"
log.info("Memory is %s bytes",BOOT_ROM_WORDS*2)


class Test(Elaboratable):
    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()
        F = 16e6 # Hz

        # Ok, back to the design.
        log.info("Create Cpu")
        m.submodules.cpu = cpu = Cpu(
            # execute from the bootloader dump.
            reset_vector = 0,
            # +1 to adjust from bus halfword addressing to CPU byte addressing.
            addr_width =  15
            # Program addresses only need to be able to address program memory,
            # so configure the PC and fetch port to be narrower. (+1 because,
            # again, our RAM is halfword addressed but this parameter is in
            # bytes.)
        )
        log.info("Create Memory")
        m.submodules.mainmem = mainmem = BasicMemory(depth=256 * 17)
        m.submodules.mem = bootmem = BasicMemory(depth = BOOT_ROM_WORDS,
                                             contents = boot_image)
        
    
        # Set the UART for 8x oversample instead of the default 16, to save some
        # logic.
        log.info("Create UART")
        m.submodules.uart = uart = BidiUart(baud_rate = 115_200,
                                            oversample = 2,
                                            clock_freq = F)
        log.info("Assemble Fabric")
        m.submodules.iofabric = iofabric = SimpleFabric([
            partial_decode(m, bootmem.bus, 11),     # 0x____0000
            partial_decode(m, uart.bus, 11),        # 0x____1000
        #    partial_decode(m, outport.bus, 11),     # 0x____2000
        #    partial_decode(m, inport.bus, 11) ,     # 0x____3000
        ])
        m.submodules.fabric = fabric = SimpleFabric([
            mainmem.bus,
            partial_decode(m, iofabric.bus, 13),
        ])

        connect(m, cpu.bus, fabric.bus)

        log.info("Binding the UART")
        uartpins = platform.request("uart", 0)

        rx_post_sync = Signal()
        m.submodules.rxsync = amaranth.lib.cdc.FFSynchronizer(
            i = uartpins.rx.i,
            o = rx_post_sync,
            o_domain = "sync",
            reset = 1,
            stages = 2,
        )
        m.d.comb += [
            uartpins.tx.o.eq(uart.tx),
            uart.rx.eq(rx_post_sync),
        ]

        if develop:
            #Dev harness
            log.info("Attach Warmboot")
            # warmboot , reset and possibly a debug interface.

            m.submodules.warmboot = wb = warmboot()
            wb_pin = platform.request("warmboot",0)
            m.d.comb += [
                wb.boot.eq(~(wb_pin.i))
            ]

        return m

p = TinyFPGABXPlatform()
# 3.3V FTDI connected to the tinybx.
# pico running micro python to run 
p.add_resources(
        [
            UARTResource(
                0, rx="A8", tx="B8", attrs=Attrs(IO_STANDARD="SB_LVCMOS", PULLUP=1)
            ),
            Resource(
                "reset_pin", 0, Pins("A9", dir="i"), Attrs(IO_STANDARD="SB_LVCMOS")
            ),
            Resource(
                "warmboot", 0, Pins("H2", dir="i"), Attrs(IO_STANDARD="SB_LVCMOS")
            ),  
        ]
    )

log.critical("Building the FPGA image")
p.build(Test())#, do_program = True)

# define the memory of the platform
link_x =  """
MEMORY {
    PROGMEM (rwx): ORIGIN = 0x0000, LENGTH = %s
}

# Specify the position of the Bootloader Stack
PROVIDE(__stack_start = %s);

"""
