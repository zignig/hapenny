from amaranth import * 
from amaranth_boards.tinyfpga_bx import TinyFPGABXPlatform

from hapenny.wbmem import WBMem
from hapenny.cpu import Cpu

class Test(Elaboratable):
    def __init__(self):
        super().__init__()
        self.cpu = Cpu()
        self.mem = WBMem()
        self.mem2 = WBMem(name="bootloader")
        self.cpu.dec.add(self.mem.bus)
        self.cpu.dec.add(self.mem2.bus)

    def elaborate(self, platform):
        m = Module()
        F = 16e6  # Hz

        m.submodules.cpu = self.cpu
        m.submodules.mem = self.mem
        m.submodules.mem2 = self.mem2


        return m 


async def bench(ctx):
    max = 2048
    for i in range(max):
        if i % 128 == 0:
            print(f"Remaining {max} - {max - i}")
        await ctx.tick()


from amaranth.sim import Simulator

if __name__ == "__main__":
    pooter = Test()
    for i in pooter.cpu.dec.bus.memory_map.all_resources():
        print(i.path,i.start,i.end)
    sim = Simulator(pooter)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    with sim.write_vcd("pooter.vcd"):
        sim.run()
