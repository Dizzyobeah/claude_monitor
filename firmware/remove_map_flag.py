"""
remove_map_flag.py — PlatformIO extra_script (pre-link)
Removes the -Wl,-Map=... linker flag that causes "Invalid argument" on Windows
when the build path is long. The .map file is not needed for normal use.
"""

Import("env")

import sys


def remove_map_flag(target, source, env):
    flags = env.get("LINKFLAGS", [])
    env.Replace(LINKFLAGS=[f for f in flags if not str(f).startswith("-Wl,-Map")])


if sys.platform.startswith("win"):
    env.AddPreAction("$BUILD_DIR/${PROGNAME}.elf", remove_map_flag)
