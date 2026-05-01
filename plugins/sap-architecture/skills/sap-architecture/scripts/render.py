#!/usr/bin/env python3
"""Render a `.drawio` file to PNG/SVG/PDF using the draw.io desktop CLI.

The structural fingerprint score in `compare.py` is necessary but not
sufficient — two diagrams can have similar fingerprints yet look very
different. Rendering both to PNG enables side-by-side visual review and
makes manual iteration in draw.io desktop fast and deliberate.

Why this script matters:
  * The eval-corpus loop has plateaued at ~22/63 leave-one-out passes.
  * The remaining gap is structural / geometric — it cannot be closed
    by more LLM retries against an XML fingerprint.
  * The realistic last-mile workflow is: scaffold → manual edit → render
    → side-by-side compare against the SAP reference → iterate.

Usage:
  render.py my-diagram.drawio                              # PNG, same dir
  render.py my-diagram.drawio -o /tmp/out.png
  render.py --format svg --scale 1.5 my-diagram.drawio
  render.py --transparent --border 20 my-diagram.drawio
  render.py --batch <dir> --format png                     # render every .drawio in dir

Exit code:
  0 — render succeeded
  1 — render failed
  2 — usage / draw.io CLI not found
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_DRAWIO_PATHS = [
    "/Applications/draw.io.app/Contents/MacOS/draw.io",          # macOS
    "/usr/bin/drawio",                                           # Linux package
    "/usr/local/bin/drawio",
    "/snap/bin/drawio",
    "/mnt/c/Program Files/draw.io/draw.io.exe",                  # WSL2
    "C:\\Program Files\\draw.io\\draw.io.exe",                   # Windows
]


def find_drawio_cli() -> str | None:
    """Locate the draw.io desktop binary.

    Honors $DRAWIO_CLI first (override), then $PATH, then the canonical
    install paths on each platform. Returns None if nothing is found.
    """
    env = os.environ.get("DRAWIO_CLI")
    if env and Path(env).exists():
        return env
    which = shutil.which("drawio") or shutil.which("draw.io")
    if which:
        return which
    for candidate in DEFAULT_DRAWIO_PATHS:
        if Path(candidate).exists():
            return candidate
    return None


def render_one(
    drawio_cli: str,
    src: Path,
    dest: Path,
    fmt: str,
    scale: float,
    border: int,
    transparent: bool,
    quiet: bool,
) -> int:
    """Render a single .drawio file. Returns the draw.io CLI exit code.

    draw.io CLI infers format from extension when -f is omitted, but we
    pass -f explicitly to keep the output deterministic.
    """
    args = [
        drawio_cli,
        "-x",
        "-f", fmt,
        "-o", str(dest),
        "-s", str(scale),
        "-b", str(border),
    ]
    if transparent and fmt == "png":
        args.append("-t")
    args.append(str(src))
    try:
        proc = subprocess.run(
            args,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        if not quiet:
            print(f"{src}: render timed out after 120s", file=sys.stderr)
        return 1
    if proc.returncode != 0 and not quiet:
        sys.stderr.write(proc.stdout.decode(errors="replace"))
        sys.stderr.write(proc.stderr.decode(errors="replace"))
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path, nargs="?")
    ap.add_argument(
        "-o", "--output",
        type=Path,
        help="output path (default: alongside source with the chosen extension)",
    )
    ap.add_argument("--format", default="png", choices=("png", "svg", "pdf", "jpg"))
    ap.add_argument("--scale", type=float, default=1.0, help="render scale, 1.0 = native")
    ap.add_argument("--border", type=int, default=10, help="border in px around the diagram")
    ap.add_argument("--transparent", action="store_true", help="transparent background (PNG only)")
    ap.add_argument("--batch", type=Path, help="render every .drawio file in this directory")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    cli = find_drawio_cli()
    if not cli:
        print(
            "draw.io CLI not found. Install draw.io desktop and re-run, or set "
            "$DRAWIO_CLI to the binary path.\n"
            "  macOS:   /Applications/draw.io.app/Contents/MacOS/draw.io\n"
            "  Linux:   apt/snap/yum install drawio (or download .deb/.rpm)\n"
            "  Windows: choco install drawio  (or installer from drawio.com)",
            file=sys.stderr,
        )
        return 2

    targets: list[Path] = []
    if args.batch:
        if not args.batch.is_dir():
            print(f"--batch: {args.batch} is not a directory", file=sys.stderr)
            return 2
        targets = sorted(args.batch.rglob("*.drawio"))
        if not targets:
            print(f"--batch: no .drawio files in {args.batch}", file=sys.stderr)
            return 1
    elif args.source:
        if not args.source.exists():
            print(f"{args.source}: not found", file=sys.stderr)
            return 1
        targets = [args.source]
    else:
        ap.print_usage(sys.stderr)
        return 2

    failures = 0
    for src in targets:
        if args.batch:
            dest = src.with_suffix(f".{args.format}")
        else:
            dest = args.output or src.with_suffix(f".{args.format}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        rc = render_one(
            cli, src, dest,
            fmt=args.format,
            scale=args.scale,
            border=args.border,
            transparent=args.transparent,
            quiet=args.quiet,
        )
        if rc != 0:
            failures += 1
            continue
        if not args.quiet:
            print(f"{src} → {dest}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
