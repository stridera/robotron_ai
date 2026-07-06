from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wintypes
import struct
from dataclasses import dataclass

import psutil


PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008

MEM_COMMIT = 0x1000
MEM_MAPPED = 0x40000
MEM_PRIVATE = 0x20000

PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01

GUEST_MAP_BASE = 0x100000000
GUEST_MAP_LIMIT = 0x200000000
ROBOTRON_GUEST_IMAGE_BASE = 0x82000000
ROBOTRON_GUEST_ENTRY = 0x82062080

READABLE_PROTECTIONS = {
    0x02,  # PAGE_READONLY
    0x04,  # PAGE_READWRITE
    0x08,  # PAGE_WRITECOPY
    0x20,  # PAGE_EXECUTE_READ
    0x40,  # PAGE_EXECUTE_READWRITE
    0x80,  # PAGE_EXECUTE_WRITECOPY
}


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

ReadProcessMemory = kernel32.ReadProcessMemory
ReadProcessMemory.argtypes = [
    wintypes.HANDLE,
    wintypes.LPCVOID,
    wintypes.LPVOID,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
ReadProcessMemory.restype = wintypes.BOOL

WriteProcessMemory = kernel32.WriteProcessMemory
WriteProcessMemory.argtypes = [
    wintypes.HANDLE,
    wintypes.LPVOID,
    wintypes.LPCVOID,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
WriteProcessMemory.restype = wintypes.BOOL

VirtualQueryEx = kernel32.VirtualQueryEx
VirtualQueryEx.argtypes = [
    wintypes.HANDLE,
    wintypes.LPCVOID,
    ctypes.POINTER(MEMORY_BASIC_INFORMATION),
    ctypes.c_size_t,
]
VirtualQueryEx.restype = ctypes.c_size_t


@dataclass
class MemoryRegion:
    base: int
    size: int
    state: int
    protect: int
    type: int

    @property
    def end(self) -> int:
        return self.base + self.size

    @property
    def readable(self) -> bool:
        base_protect = self.protect & 0xFF
        return (
            self.state == MEM_COMMIT
            and not (self.protect & PAGE_GUARD)
            and base_protect in READABLE_PROTECTIONS
        )


class XeniaMemory:
    def __init__(self, process_name: str = "xenia_canary.exe", writable: bool = False):
        self.process = self._find_process(process_name)
        flags = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
        if writable:
            flags |= PROCESS_VM_WRITE | PROCESS_VM_OPERATION
        self.writable = writable
        self.handle = OpenProcess(
            flags,
            False,
            self.process.pid,
        )
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "OpenProcess failed")

        # Discover Xenia's virtual_membase from the pointer file written
        # by the GPU hook. Falls back to the legacy constant if unavailable.
        self._guest_map_base = GUEST_MAP_BASE
        try:
            import os
            ptr_file = os.path.join(os.environ.get("TEMP", "/tmp"),
                                    "robotron_entity_ptr.bin")
            with open(ptr_file, "rb") as f:
                data = f.read()
            if len(data) >= 16:
                vmbase = struct.unpack_from("<Q", data, 8)[0]
                if vmbase > 0:
                    self._guest_map_base = vmbase
        except (OSError, struct.error):
            pass

    def close(self) -> None:
        if self.handle:
            CloseHandle(self.handle)
            self.handle = None

    def __enter__(self) -> "XeniaMemory":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @staticmethod
    def _find_process(name: str) -> psutil.Process:
        matches = [p for p in psutil.process_iter(["pid", "name"]) if p.info["name"] == name]
        if not matches:
            raise RuntimeError(f"{name} is not running")
        return matches[0]

    def guest_to_host(self, guest_address: int) -> int:
        return self._guest_map_base + guest_address

    def host_to_guest(self, host_address: int) -> int:
        return host_address - self._guest_map_base

    def query(self, address: int) -> MemoryRegion | None:
        mbi = MEMORY_BASIC_INFORMATION()
        result = VirtualQueryEx(
            self.handle,
            ctypes.c_void_p(address),
            ctypes.byref(mbi),
            ctypes.sizeof(mbi),
        )
        if not result:
            return None
        return MemoryRegion(
            base=int(mbi.BaseAddress),
            size=int(mbi.RegionSize),
            state=int(mbi.State),
            protect=int(mbi.Protect),
            type=int(mbi.Type),
        )

    def iter_regions(self, start: int = GUEST_MAP_BASE, end: int = GUEST_MAP_LIMIT):
        address = start
        while address < end:
            region = self.query(address)
            if region is None or region.size <= 0:
                address += 0x1000
                continue
            yield region
            address = max(address + 0x1000, region.end)

    def readable_regions(self, start: int = GUEST_MAP_BASE, end: int = GUEST_MAP_LIMIT):
        for region in self.iter_regions(start, end):
            if region.readable:
                yield region

    def read(self, address: int, size: int) -> bytes:
        buffer = ctypes.create_string_buffer(size)
        read = ctypes.c_size_t()
        ok = ReadProcessMemory(
            self.handle,
            ctypes.c_void_p(address),
            buffer,
            size,
            ctypes.byref(read),
        )
        if not ok:
            raise OSError(ctypes.get_last_error(), f"ReadProcessMemory failed at 0x{address:X}")
        return buffer.raw[: read.value]

    def read_guest(self, guest_address: int, size: int) -> bytes:
        return self.read(self.guest_to_host(guest_address), size)

    def write(self, address: int, data: bytes) -> int:
        """Write raw bytes to host process memory."""
        if not self.writable:
            raise RuntimeError("XeniaMemory opened without write access. Use writable=True.")
        buf = ctypes.create_string_buffer(data)
        written = ctypes.c_size_t()
        ok = WriteProcessMemory(
            self.handle,
            ctypes.c_void_p(address),
            buf,
            len(data),
            ctypes.byref(written),
        )
        if not ok:
            raise OSError(ctypes.get_last_error(), f"WriteProcessMemory failed at 0x{address:X}")
        return written.value

    def write_guest(self, guest_address: int, data: bytes) -> int:
        """Write raw bytes to a guest virtual address."""
        return self.write(self.guest_to_host(guest_address), data)

    def search(self, needle: bytes, start: int = GUEST_MAP_BASE, end: int = GUEST_MAP_LIMIT, max_hits: int = 64):
        hits: list[int] = []
        for region in self.readable_regions(start, end):
            try:
                data = self.read(region.base, region.size)
            except OSError:
                continue
            offset = 0
            while True:
                found = data.find(needle, offset)
                if found < 0:
                    break
                hits.append(region.base + found)
                if len(hits) >= max_hits:
                    return hits
                offset = found + 1
        return hits


def cmd_summary(mem: XeniaMemory) -> None:
    regions = list(mem.readable_regions())
    mapped = [r for r in regions if r.type == MEM_MAPPED]
    private = [r for r in regions if r.type == MEM_PRIVATE]
    print(f"xenia pid: {mem.process.pid}")
    print(f"readable guest-space regions: {len(regions)}")
    print(f"  mapped: {len(mapped)}")
    print(f"  private: {len(private)}")
    if regions:
        biggest = max(regions, key=lambda r: r.size)
        print(f"largest readable region: 0x{biggest.base:X}-0x{biggest.end:X} ({biggest.size // 1024} KiB)")
    for guest in (ROBOTRON_GUEST_IMAGE_BASE, ROBOTRON_GUEST_ENTRY):
        host = mem.guest_to_host(guest)
        try:
            data = mem.read(host, 16)
            hex_bytes = " ".join(f"{b:02X}" for b in data)
            print(f"guest 0x{guest:08X} -> host 0x{host:X}: {hex_bytes}")
        except OSError as exc:
            print(f"guest 0x{guest:08X} -> host 0x{host:X}: read failed ({exc})")


def cmd_dump(mem: XeniaMemory, guest: int, size: int) -> None:
    data = mem.read_guest(guest, size)
    print(f"guest 0x{guest:08X} -> host 0x{mem.guest_to_host(guest):X}")
    print(data.hex(" "))


def cmd_find_u32(mem: XeniaMemory, value: int, endian: str, max_hits: int) -> None:
    needle = value.to_bytes(4, byteorder=endian, signed=False)
    hits = mem.search(needle, max_hits=max_hits)
    print(f"hits for {endian} u32 0x{value:08X}: {len(hits)}")
    for host in hits:
        guest = mem.host_to_guest(host)
        print(f"host 0x{host:X} guest 0x{guest:08X}")


def cmd_find_text(mem: XeniaMemory, text: str, encoding: str, max_hits: int) -> None:
    needle = text.encode(encoding)
    hits = mem.search(needle, max_hits=max_hits)
    print(f"hits for {encoding} text {text!r}: {len(hits)}")
    for host in hits:
        guest = mem.host_to_guest(host)
        print(f"host 0x{host:X} guest 0x{guest:08X}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read Xenia guest-mapped memory from the running process.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("summary")

    dump = sub.add_parser("dump")
    dump.add_argument("--guest", required=True, type=lambda x: int(x, 0))
    dump.add_argument("--size", required=True, type=lambda x: int(x, 0))

    find_u32 = sub.add_parser("find-u32")
    find_u32.add_argument("--value", required=True, type=lambda x: int(x, 0))
    find_u32.add_argument("--endian", choices=["little", "big"], default="big")
    find_u32.add_argument("--max-hits", type=int, default=32)

    find_text = sub.add_parser("find-text")
    find_text.add_argument("--text", required=True)
    find_text.add_argument("--encoding", choices=["ascii", "utf-16-le", "utf-16-be"], default="utf-16-be")
    find_text.add_argument("--max-hits", type=int, default=32)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    with XeniaMemory() as mem:
        if args.command == "summary":
            cmd_summary(mem)
        elif args.command == "dump":
            cmd_dump(mem, args.guest, args.size)
        elif args.command == "find-u32":
            cmd_find_u32(mem, args.value, args.endian, args.max_hits)
        elif args.command == "find-text":
            cmd_find_text(mem, args.text, args.encoding, args.max_hits)


if __name__ == "__main__":
    main()
