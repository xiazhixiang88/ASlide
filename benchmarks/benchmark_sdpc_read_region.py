"""Compare this checkout with a Git revision using private local slide files.

Example (run from the repository root with the native SDK available):
    python benchmarks/benchmark_sdpc_read_region.py --baseline origin/main \
        --output /tmp/sdpc-results.json sample.sdpc sample.dyqx

No slide pixels or filenames are included in the JSON output. Timings use warm
reads on one handle and alternate baseline/candidate order; they do not measure
cold storage performance. The conversion microbenchmark excludes SDK reads.
"""

import argparse
import ast
import ctypes
import hashlib
import json
import platform
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time

import numpy as np
import PIL
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def compare_times(old, new, rounds):
    old()
    new()
    timings = {"baseline": [], "candidate": []}
    for i in range(rounds):
        pair = [("baseline", old), ("candidate", new)]
        for label, fn in pair if i % 2 == 0 else pair[::-1]:
            start = time.perf_counter()
            fn()
            timings[label].append((time.perf_counter() - start) * 1000)
    old_ms = statistics.median(timings["baseline"])
    new_ms = statistics.median(timings["candidate"])
    return {"baseline_ms": old_ms, "candidate_ms": new_ms,
            "speedup": old_ms / new_ms, "samples_ms": timings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slides", nargs="+")
    parser.add_argument("--baseline", default="origin/main")
    parser.add_argument("--rounds", type=int, default=12)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be positive")

    from Aslide.sdpc import sdpc_slide

    source = subprocess.check_output(
        ["git", "show", f"{args.baseline}:Aslide/sdpc/sdpc_slide.py"],
        cwd=ROOT, text=True)
    cls = next(n for n in ast.parse(source).body
               if isinstance(n, ast.ClassDef) and n.name == "SdpcSlide")
    method = next(n for n in cls.body
                  if isinstance(n, ast.FunctionDef) and n.name == "read_region")
    namespace = dict(vars(sdpc_slide), np=np)
    exec(compile(ast.Module(body=[method], type_ignores=[]),
                 "<baseline read_region>", "exec"), namespace)
    baseline = namespace["read_region"]
    candidate = sdpc_slide.SdpcSlide.read_region
    result = {
        "baseline_commit": subprocess.check_output(
            ["git", "rev-parse", args.baseline], cwd=ROOT, text=True).strip(),
        "candidate_source_sha256": hashlib.sha256(
            Path(sdpc_slide.__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(), "pillow": PIL.__version__,
        "numpy": np.__version__, "platform": platform.platform(),
        "rounds": args.rounds, "conversion": [], "slides": [],
    }
    for size in (512, 1024, 2048):
        # Nonconstant input exercises every byte value, including the fourth byte.
        raw = np.arange(size * size * 4, dtype=np.uint8)
        buffer = (ctypes.c_ubyte * raw.size).from_buffer_copy(raw)

        def old_conversion():
            bgra = np.frombuffer(buffer, dtype=np.uint8).reshape(size, size, 4)
            return Image.fromarray(bgra[:, :, [2, 1, 0]], "RGB")

        def new_conversion():
            return Image.frombytes("RGB", (size, size), buffer, "raw", "BGRX", 0, 1)

        assert old_conversion().tobytes() == new_conversion().tobytes()
        result["conversion"].append(dict(size=size, **compare_times(
            old_conversion, new_conversion, args.rounds)))

    for number, filename in enumerate(args.slides):
        slide = sdpc_slide.SdpcSlide(filename)
        report = {"sample": number + 1, "format": Path(filename).suffix.lower(),
                  "equal_regions": 0, "matching_failures": 0, "timings": []}
        try:
            rng = random.Random(20260929)
            for level in range(min(2, slide.level_count)):
                width, height = slide.level_dimensions[level]
                ds = slide.level_downsamples[level]
                for size in (256, 672, 1024):
                    if min(width, height) < size:
                        continue
                    locations = [(0, 0)] + [
                        (int(rng.randrange(width - size + 1) * ds),
                         int(rng.randrange(height - size + 1) * ds))
                        for _ in range(3)]
                    for location in locations:
                        old = baseline(slide, location, level, (size, size))
                        new = candidate(slide, location, level, (size, size))
                        assert old.mode == new.mode == "RGB"
                        assert old.size == new.size == (size, size)
                        assert old.tobytes() == new.tobytes(), (level, size, location)
                        report["equal_regions"] += 1
                # SDK errors must retain the same type and text. If a particular
                # SDK supports these reads, compare its pixels instead.
                for location in ((int((width - 1) * ds), int((height - 1) * ds)),
                                 (int((width + 1024) * ds), 0)):
                    outcomes = []
                    for fn in (baseline, candidate):
                        try:
                            image = fn(slide, location, level, (256, 256))
                            outcomes.append((image.mode, image.size, image.tobytes()))
                        except RuntimeError as error:
                            outcomes.append((type(error).__name__, str(error)))
                    assert outcomes[0] == outcomes[1]
                    if len(outcomes[0]) == 2:
                        report["matching_failures"] += 1
                    else:
                        report["equal_regions"] += 1
            width, height = slide.dimensions
            for size in (512, 1024, 2048):
                if min(width, height) < size:
                    continue
                location = ((width - size) // 2, (height - size) // 2)
                report["timings"].append(dict(size=size, **compare_times(
                    lambda: baseline(slide, location, 0, (size, size)),
                    lambda: candidate(slide, location, 0, (size, size)), args.rounds)))
        finally:
            slide.close()
        result["slides"].append(report)
        print(json.dumps(report), flush=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
