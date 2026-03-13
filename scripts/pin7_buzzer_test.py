#!/usr/bin/env python3

import argparse
import math
import shutil
import subprocess
import sys


DEFAULT_LINE_NAME = "PAC.06"


def run_checked(args: list[str], capture_output: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=True,
        text=True,
        capture_output=capture_output,
    )


def resolve_gpio_line(line_name: str) -> tuple[str, str]:
    result = run_checked(["gpiofind", line_name])
    parts = result.stdout.strip().split()
    if len(parts) != 2:
        raise RuntimeError(f"unexpected gpiofind output for {line_name!r}: {result.stdout!r}")
    return parts[0], parts[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Drive Jetson header pin 7 low-active for a fixed duration to test a buzzer."
    )
    parser.add_argument("--seconds", type=float, default=10.0, help="time to hold the buzzer active")
    parser.add_argument(
        "--line-name",
        default=DEFAULT_LINE_NAME,
        help=f"GPIO line name to resolve with gpiofind (default: {DEFAULT_LINE_NAME})",
    )
    args = parser.parse_args()

    if args.seconds <= 0:
        print("--seconds must be > 0", file=sys.stderr)
        return 2

    for cmd in ("gpiofind", "gpioset"):
        if shutil.which(cmd) is None:
            print(f"missing required command: {cmd}", file=sys.stderr)
            return 1

    try:
        chip, offset = resolve_gpio_line(args.line_name)
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or exc.stdout or str(exc), file=sys.stderr)
        return exc.returncode or 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        f"Activating buzzer on {chip} offset {offset} "
        f"(line {args.line_name}, low-active) for {args.seconds:.3f} seconds..."
    )

    whole_seconds = math.floor(args.seconds)
    micros = round((args.seconds - whole_seconds) * 1_000_000)
    if micros == 1_000_000:
        whole_seconds += 1
        micros = 0

    try:
        subprocess.run(
            [
                "gpioset",
                "-m",
                "time",
                "-s",
                str(whole_seconds),
                "-u",
                str(micros),
                "-l",
                chip,
                f"{offset}=1",
            ],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"gpioset failed with exit code {exc.returncode}", file=sys.stderr)
        return exc.returncode or 1

    print("Buzzer pulse complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
