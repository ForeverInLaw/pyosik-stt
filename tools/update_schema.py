"""Regenerate the bundled protobuf descriptor from pinned NVIDIA sources."""

import base64
import re
import subprocess
import sys
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen

REVISION = "268890b7286031a6d4950e34f7ce13ed0d4ce621"
ROOT = Path(__file__).resolve().parents[1]


def main():
    with TemporaryDirectory(prefix="pyosik-schema-") as temp:
        directory = Path(temp)
        proto = directory / "riva" / "proto"
        proto.mkdir(parents=True)
        for filename in ("riva_audio.proto", "riva_common.proto", "riva_asr.proto"):
            url = f"https://raw.githubusercontent.com/nvidia-riva/common/{REVISION}/riva/proto/{filename}"
            with urlopen(url, timeout=30) as response:
                (proto / filename).write_bytes(response.read())
        descriptor = directory / "riva.pb"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "grpc_tools.protoc",
                f"-I{directory}",
                f"--descriptor_set_out={descriptor}",
                "--include_imports",
                str(proto / "riva_asr.proto"),
            ],
            check=True,
        )
        encoded = base64.b64encode(
            zlib.compress(descriptor.read_bytes(), level=9)
        ).decode()
    plugin = ROOT / "pyosik.py"
    source, count = re.subn(
        r'^RIVA_SCHEMA = ".*"$',
        f'RIVA_SCHEMA = "{encoded}"',
        plugin.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    if count != 1:
        raise RuntimeError("Expected exactly one RIVA_SCHEMA assignment")
    plugin.write_text(source, encoding="utf-8", newline="\n")
    print(f"Updated Riva schema from {REVISION}, {len(encoded)} base64 characters")


if __name__ == "__main__":
    main()
