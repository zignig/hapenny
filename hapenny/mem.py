# Reusable memory with our bus interface.

from amaranth import *
from amaranth.lib.wiring import *
from amaranth.lib import wiring
from amaranth.lib.enum import *
from amaranth.lib.coding import Encoder, Decoder

from hapenny import StreamSig, AlwaysReady, mux
from hapenny.bus import BusPort

import struct
from pathlib import Path

import os
import logging

log = logging.getLogger(__name__)


class BasicMemory(Component):
    """A dead-simple 16-bit-wide memory with the Hapenny bus interface.

    This uses an Amaranth generic memory internally, which relies on inference
    in the synthesis tools to map to a specific type of resource such as block
    RAM. In practice it won't map to uninitialized RAM (like the iCE40UP5K's
    SPRAM) because Amaranth insists on generating it with an initializer; for
    that you'll need another module.

    Parameters
    ----------
    depth (integer): number of 16-bit halfwords in the memory. If omitted,
        contents must be provided, and depth is inferred from len(contents).
    contents (list of integer): initialization contents of the memory. If
        omitted, depth must be provided, and the RAM is implicitly zeroed.
    read_only (boolean): if overridden to True, the memory will not respond to
        write strobes. This is useful for using an initialized block RAM as a
        program ROM.
    file_name (path): path to a file to load into the memory.

    Attributes
    ----------
    bus: a BusPort with the minimum number of addr bits required to address
        'depth' words, and a 16-bit data path.
    """

    def __init__(
        self, *, depth=None, file_name=None, contents=[], read_only=False
    ):

        if depth is None:
            assert len(contents) > 0, "either depth or contents must be provided"
            depth = len(contents)

        self.depth = depth
        self.contents = contents

        self.addr_bits = (self.depth - 1).bit_length()
        super().__init__({"bus": In(BusPort(addr=self.addr_bits, data=16))})

        self.read_only = False
        self.file_name = file_name

    def _decode(self):
        bootloader = Path(self.file_name).read_bytes()
        boot_image = struct.unpack("<" + "H" * (len(bootloader) // 2), bootloader)
        return boot_image

    def fetch(self):
        "Load a filename"
        try:
            os.stat(self.file_name)
            # if we reach here the file exists
            self.contents = self._decode()
        except:
            log.warning(f"file does not exist {self.file_name}")
            # get the file data (Succesfull, [image contents])
            if self.build():
                self.contents = self._decode()
            else:
                raise Exception("File build failed")

    ## override for building firmwares , bootloader in subclasses
    def build(self):
        return False

    def elaborate(self, platform):
        m = Module()

        if self.file_name is not None:
            self.fetch()
        mem = Memory(
            width=16,
            depth=self.depth,
            name="basicram",
            init=self.contents,
        )

        m.submodules += mem

        rp = mem.read_port(transparent=False)

        m.d.comb += [
            rp.addr.eq(self.bus.cmd.payload.addr),
            rp.en.eq(self.bus.cmd.valid & (self.bus.cmd.payload.lanes == 0)),
            self.bus.resp.eq(rp.data),
        ]

        if not self.read_only:
            wp = mem.write_port(granularity=8)
            m.d.comb += [
                wp.addr.eq(self.bus.cmd.payload.addr),
                wp.data.eq(self.bus.cmd.payload.data),
                wp.en[0].eq(self.bus.cmd.valid & self.bus.cmd.payload.lanes[0]),
                wp.en[1].eq(self.bus.cmd.valid & self.bus.cmd.payload.lanes[1]),
            ]

        return m


class SpramMemory(Component):
    """A single 256 kiB / 32 kiB SPRAM on the UP5K.

    This module exists because getting Amaranth to generate a memory that Yosys
    is willing to map to SPRAM is currently hard.

    SPRAMs are uninitialized at reset and can retain content across both design
    and device resets. As a result, this module doesn't support a read_only
    mode, because its contents would be indeterminate (yet not random enough to
    be interesting).

    Attributes
    ----------
    bus: bus interface with 14 address bits.
    """

    bus: In(BusPort(addr=14, data=16))

    def elaborate(self, platform):
        m = Module()

        m.submodules.spram = Instance(
            "SB_SPRAM256KA",
            i_CLOCK=ClockSignal("sync"),
            i_ADDRESS=self.bus.cmd.payload.addr,
            i_DATAIN=self.bus.cmd.payload.data,
            # Weirdly, write enables are at the nibble level.
            i_MASKWREN=Cat(
                self.bus.cmd.payload.lanes[0],
                self.bus.cmd.payload.lanes[0],
                self.bus.cmd.payload.lanes[1],
                self.bus.cmd.payload.lanes[1],
            ),
            i_WREN=self.bus.cmd.payload.lanes != 0,
            i_CHIPSELECT=self.bus.cmd.valid,
            i_POWEROFF=1,  # active fucking low
            i_STANDBY=0,
            i_SLEEP=0,
            o_DATAOUT=self.bus.resp,
        )

        return m
