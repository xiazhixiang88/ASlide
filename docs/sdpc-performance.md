# SDPC/DYQX region conversion and DeepZoom performance

SDPC and DYQX share the SDPC backend. Decode the SDK BGRA buffer directly
with Pillow's BGRX raw decoder instead of using NumPy advanced indexing and
then constructing a Pillow image. The result remains an independently owned
RGB image; the fourth byte is ignored exactly as before. Keep zero-initialized
buffers, coordinate conversion, parameter validation and native error handling.

Opaque RGB DeepZoom tiles can bypass RGBA conversion and background compositing.
Non-RGB tiles retain the existing alpha compositing behavior. This change adds
no dependencies, changes no native binaries and preserves public interfaces.

## Validation on 2026-10-30

Baseline: upstream `c4a817c0a5ae98cc2b6a1dfce6a31e0eeee54507`.
Python 3.12.14, Pillow 12.3.0, NumPy 2.5.2, Linux x86_64. Single-threaded
OpenBLAS/OMP configuration on a shared server. No GPU is used.

- All 9 SDK-independent regression tests passed, covering RGB channel/row
  order, discarded fourth bytes, result ownership, coordinates, validation,
  closed handles, SDK failures and RGB/RGBA DeepZoom behavior.
- Four real slides (two SDPC and two DYQX): 96 regions byte-identical over
  levels 0/1 and 256/672/1024 sizes; 16 edge/out-of-bounds failures identical.
- Two real slides: 18 DeepZoom tiles byte-identical across three zoom levels,
  including origin, center and the last tile.

Warm region reads, median of 20 alternating baseline/candidate measurements
at a single center location per size, using the same open handle:

| Sample | 1024 baseline | 1024 candidate | Speed ratio |
| --- | ---: | ---: | ---: |
| SDPC 1 | 42.60 ms | 36.89 ms | 1.15x |
| DYQX 1 | 49.09 ms | 43.19 ms | 1.14x |
| SDPC 2 | 40.87 ms | 35.27 ms | 1.16x |
| DYQX 2 | 12.11 ms | 6.46 ms | 1.88x |

DeepZoom get_tile medians were 9.86 to 9.11 ms (SDPC, 1.08x) and
23.09 to 22.32 ms (DYQX, 1.03x), comparing both region conversion and
compositing changes against the baseline. Region timings call the backend
directly, before the public Slide wrapper's RGB-to-RGBA conversion.

These small warm-cache tests do not measure cold storage, browser/network
latency, model inference or full-slide throughput. SDK time and sample content
affect the gain. Earlier project-specific direct-NumPy measurements used a
different output API and must not be substituted for these numbers.

## Reproduce

Use your own local slides; no slide pixels or filenames are written to JSON.
Run from the repository root with the native SDK available:

```bash
python -m unittest discover -s tests -v
python benchmarks/benchmark_sdpc_read_region.py --baseline c4a817c \
  --rounds 20 --output /tmp/regions.json sample.sdpc sample.dyqx
python benchmarks/benchmark_sdpc_deepzoom.py --baseline c4a817c \
  --rounds 20 --output /tmp/tiles.json sample.sdpc sample.dyqx
```
