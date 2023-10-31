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
from hapenny.boxcpu import Cpu
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
RAM_WORDS = 256 * 2
#RAM_WORDS = 256 * 16 # (8192) bytes WOO HOO.
RAM_ADDR_BITS = (RAM_WORDS - 1).bit_length()
BUS_ADDR_BITS = RAM_ADDR_BITS + 1

log.info(f"configuring for {RAM_ADDR_BITS}-bit RAM and {BUS_ADDR_BITS}-bit bus")

log.debug("Calc the bootload settings")
bootloader = Path("tiny-bootloader.bin").read_bytes()
#bootloader = Path("./tinyboot/tinyboot.bin").read_bytes()
boot_image = struct.unpack("<" + "h" * (len(bootloader) // 2), bootloader)

log.debug("All these calculation are in half words (16bits)")

boot_length = 2 ** len(boot_image).bit_length()
mem_size = RAM_WORDS

log.debug("Bootimage length : %s",len(boot_image))
log.debug("Bootimage length (bit ceiling): %s",boot_length)

log.info("Ram Size :%s words",mem_size)

leader = (0,) *(( mem_size - boot_length))
log.debug("Leader (zeros): %s",len(leader))

residual = (0,) * ((boot_length - len(boot_image)))
log.debug("Residual (zeros): %s",len(residual))
boot_image = leader + boot_image + residual

log.debug(boot_image)

log.info("Memory is %s bytes",RAM_WORDS*2)
## Fix the position of the boot loader
# place at bottom of the rams

# leader = (0,) * ((2**RAM_ADDR_BITS) - 512)
# residual = 512 - len(boot_image)
# boot_image = leader + boot_image
# print(residual,boot_image)
# #print(boot_image,len(boot_image))

class Test(Elaboratable):
    def __init__(self):
        super().__init__()

    def elaborate(self, platform):
        m = Module()
        F = 16e6 # Hz

        # Ok, back to the design.
        log.info("Create Cpu")
        log.critical("Reset vector is : %s 16bit.",len(leader))
        m.submodules.cpu = cpu = Cpu(
            # execute from the bootloader dump.
            reset_vector =  len(leader),
            # +1 to adjust from bus halfword addressing to CPU byte addressing.
            addr_width = BUS_ADDR_BITS + 1,
            # Program addresses only need to be able to address program memory,
            # so configure the PC and fetch port to be narrower. (+1 because,
            # again, our RAM is halfword addressed but this parameter is in
            # bytes.)
            prog_addr_width = RAM_ADDR_BITS + 1,
        )
        log.info("Create Memory")
        m.submodules.mem = mem = BasicMemory(depth = RAM_WORDS,
                                             contents = boot_image)
        # Set the UART for 8x oversample instead of the default 16, to save some
        # logic.
        log.info("Create UART")
        m.submodules.uart = uart = BidiUart(baud_rate = 115_200,
                                            oversample = 2,
                                            clock_freq = F)
        log.info("Assemble Fabric")
        m.submodules.fabric = fabric = SimpleFabric([
            mem.bus,
            partial_decode(m, uart.bus, RAM_ADDR_BITS),
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
