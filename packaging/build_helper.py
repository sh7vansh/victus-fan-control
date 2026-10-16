#!/usr/bin/python3
"""Build a self-contained Linux helper using only Go's standard library."""

import argparse
import os
import platform
import struct
import subprocess

from project import SOURCE, __version__

OUTPUT = SOURCE / "build/native/victus-fan-control-helper"
TEST_OUTPUT = SOURCE / "build/native/fan-control-helper-tests"


def assert_static(path):
    data = path.read_bytes()
    if data[:4] != b"\x7fELF" or data[4] not in (1, 2):
        raise ValueError("The helper must be a Linux ELF executable")
    endian = "<" if data[5] == 1 else ">"
    if data[4] == 2:
        offset = struct.unpack_from(endian + "Q", data, 32)[0]
        size, count = struct.unpack_from(endian + "HH", data, 54)
    else:
        offset = struct.unpack_from(endian + "I", data, 28)[0]
        size, count = struct.unpack_from(endian + "HH", data, 42)
    for index in range(count):
        if struct.unpack_from(endian + "I", data, offset + index * size)[0] == 3:
            raise ValueError("The helper has a dynamic loader dependency")


def build(test=False):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    arches = {"x86_64": "amd64", "aarch64": "arm64", "armv7l": "arm", "i686": "386", "riscv64": "riscv64", "ppc64le": "ppc64le"}
    arch = arches.get(platform.machine())
    if arch is None:
        raise ValueError(f"Unsupported helper build architecture: {platform.machine()}")
    env.update(CGO_ENABLED="0", GOOS="linux", GOARCH=arch, GOAMD64="v1", GOPROXY="off", GOTOOLCHAIN="local")
    subprocess.run(["go", "build", "-trimpath", "-buildvcs=false", "-ldflags", f"-s -w -X main.version={__version__}", "-o", str(OUTPUT), "."],
                   cwd=SOURCE / "native/helper", env=env, check=True)
    assert_static(OUTPUT)
    if test:
        subprocess.run(["go", "test", "./..."], cwd=SOURCE / "native/helper", env=env, check=True)
        subprocess.run(["go", "test", "-c", "-o", str(TEST_OUTPUT)], cwd=SOURCE / "native/helper", env=env, check=True)
    print(f"Built static helper: {OUTPUT}")
    return OUTPUT


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    build(args.test)
