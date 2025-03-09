from amaranth import *
from amaranth.lib.wiring import *
from amaranth.lib import wiring
from amaranth.lib import memory as Mem
from amaranth_soc import wishbone,memory

import struct
from pathlib import Path

class WBMem(Component):
    def __init__(self,name="mem",writeable=True):
        self.writeable = writeable
        super().__init__(
            {
                "bus": In(wishbone.Signature(
                    addr_width=10, data_width=16, granularity=8
                ))
            }
        )
        bootloader = Path('/opt/patina/experiments/bin/spinner').read_bytes()
        boot_image = struct.unpack("<" + "H" * (len(bootloader) // 2), bootloader)

        self.bus.memory_map = mm = memory.MemoryMap(addr_width=11,data_width=8)

        mm.add_resource(name=name,size=1024,resource=self)

        self._mem = Mem.Memory(depth=64,shape=16,init=boot_image)

    def elaborate(self, platform):
        m = Module()
        m.submodules.mem = self._mem

        # get the ports
        mem_rp = self._mem.read_port()

        m.d.comb += self.bus.dat_r.eq(mem_rp.data)
        # ack the transaction

        with m.If(self.bus.cyc & self.bus.stb):
            m.d.sync += self.bus.ack.eq(1)

        # get the read 
        with m.If(self.bus.cyc & self.bus.stb):
            m.d.sync += self.bus.ack.eq(1)
            m.d.comb += mem_rp.addr.eq(self.bus.adr)

        # do the write 
        if self.writeable:
            mem_wp = self._mem.write_port(granularity=8)
            m.d.comb += mem_wp.addr.eq(mem_rp.addr)
            m.d.comb += mem_wp.data.eq(self.bus.dat_w)
            with m.If(self.bus.cyc & self.bus.stb & self.bus.we):
                m.d.comb += mem_wp.en.eq(self.bus.sel)

        # reset the ack
        with m.If(self.bus.ack):
            m.d.sync += self.bus.ack.eq(0)

        return m
