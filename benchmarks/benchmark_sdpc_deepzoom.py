"""Compare full SDPC DeepZoom tiles against a Git baseline using local slides.

Run from a checkout with the native SDK available. Output contains no paths
or pixels. This measures warm reads, not cold storage or model inference.
"""
import argparse
import ast
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark_sdpc_read_region import compare_times
from Aslide.sdpc import sdpc_slide, sdpc_deepzoom


def method_at(ref, filename, class_name, method_name, module):
    source = subprocess.check_output(['git', 'show', f'{ref}:{filename}'], text=True)
    cls = next(n for n in ast.parse(source).body
               if isinstance(n, ast.ClassDef) and n.name == class_name)
    method = next(n for n in cls.body
                  if isinstance(n, ast.FunctionDef) and n.name == method_name)
    namespace = dict(vars(module))
    import numpy as np
    namespace['np'] = np
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<baseline>', 'exec'), namespace)
    return namespace[method_name]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--rounds', type=int, default=20)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('slides', nargs='+')
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error('--rounds must be positive')
    old_read = method_at(args.baseline, 'Aslide/sdpc/sdpc_slide.py',
                         'SdpcSlide', 'read_region', sdpc_slide)
    old_tile = method_at(args.baseline, 'Aslide/sdpc/sdpc_deepzoom.py',
                         'DeepZoomGenerator', 'get_tile', sdpc_deepzoom)
    reports = []
    for number, filename in enumerate(args.slides, 1):
        slide = sdpc_slide.SdpcSlide(filename)
        try:
            dz = sdpc_deepzoom.DeepZoomGenerator(slide)
            current = slide.read_region

            def baseline(level, address):
                slide.read_region = old_read.__get__(slide)
                try:
                    return old_tile(dz, level, address)
                finally:
                    slide.read_region = current

            checks = 0
            for level in (dz.level_count - 1, dz.level_count - 3, dz.level_count - 6):
                tx, ty = dz.level_tiles[level]
                for address in ((0, 0), (tx // 2, ty // 2), (tx - 1, ty - 1)):
                    old, new = baseline(level, address), dz.get_tile(level, address)
                    assert (old.mode, old.size, old.tobytes()) == (new.mode, new.size, new.tobytes())
                    checks += 1
            level = dz.level_count - 1
            tx, ty = dz.level_tiles[level]
            address = (tx // 2, ty // 2)
            reports.append(dict(sample=number, format=Path(filename).suffix,
                equal_tiles=checks, **compare_times(lambda: baseline(level, address),
                lambda: dz.get_tile(level, address), args.rounds)))
        finally:
            slide.close()
    result = dict(baseline_commit=subprocess.check_output(
        ['git', 'rev-parse', args.baseline], text=True).strip(),
        candidate_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        rounds=args.rounds, slides=reports)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
