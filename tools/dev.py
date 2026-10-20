"""Use the SDK development server after adb forward tcp:42690 tcp:42690."""

import argparse
import codecs
import json
import socket
import time
from pathlib import Path
from uuid import uuid4


def request(command, **fields):
    request_id = str(uuid4())
    payload = {"@": command, "#": request_id, **fields}
    decoder = json.JSONDecoder()
    utf8 = codecs.getincrementaldecoder("utf-8")()
    data = ""
    with socket.create_connection(("127.0.0.1", 42690), timeout=60) as connection:
        connection.sendall(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                raise ConnectionError("Dev Server closed before responding")
            data += utf8.decode(chunk)
            while data.strip():
                try:
                    response, end = decoder.raw_decode(data.lstrip())
                except json.JSONDecodeError:
                    break
                data = data.lstrip()[end:]
                if response.get("#") == request_id:
                    return response


def wait_for_plugin(*, enabled=None):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        state = request("get_plugins").get("pyosik")
        if state is not None:
            if state.get("error"):
                raise RuntimeError(state["error"])
            if enabled is None or state["enabled"] == enabled:
                return state
        time.sleep(0.25)
    raise TimeoutError("Pyosik did not reach the requested state in 60 seconds")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("ping", "list", "install", "enable", "disable")
    )
    parser.add_argument(
        "--file", type=Path, default=Path(__file__).resolve().parents[1] / "pyosik.py"
    )
    args = parser.parse_args()
    if args.command == "install":
        response = request(
            "write_plugin",
            plugin_id="pyosik",
            content=args.file.read_text(encoding="utf-8"),
        )
        if not response.get("error"):
            wait_for_plugin()
            request("enable_plugin", plugin_id="pyosik")
            response = wait_for_plugin(enabled=True)
    elif args.command in ("enable", "disable"):
        response = request(args.command + "_plugin", plugin_id="pyosik")
        if not response.get("error"):
            response = wait_for_plugin(enabled=args.command == "enable")
    else:
        response = request("get_plugins" if args.command == "list" else "ping")
    print(json.dumps(response, ensure_ascii=False, indent=2))
    if response.get("error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
