"""
inject_version.py — PlatformIO extra_script (pre-build)
Reads the git-described version and injects it as a -DFW_VERSION build flag
so firmware code can reference FW_VERSION as a string literal.
"""

import subprocess

Import("env")  # noqa: F821 — PlatformIO global


def get_git_version():
    """Get version from git describe, falling back to 'dev'."""
    try:
        version = subprocess.check_output(
            ["git", "describe", "--tags", "--always"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        if version.startswith("v"):
            version = version[1:]
        return version
    except Exception:
        return "dev"


version = get_git_version()
env.Append(CPPDEFINES=[("FW_VERSION", env.StringifyMacro(version))])
print(f"  Firmware version: {version}")
