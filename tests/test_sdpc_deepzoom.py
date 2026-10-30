"""SDPC DeepZoom tests with a slide stub, without loading the native SDK."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from PIL import Image


class _Slide:
    level_dimensions = ((16, 16),)
    level_downsamples = (1.0,)
    dimensions = (16, 16)
    properties = {}

    def __init__(self, mode):
        self.mode = mode

    def get_best_level_for_downsample(self, downsample):
        return 0

    def read_region(self, location, level, size):
        if self.mode == "RGB":
            return Image.new("RGB", size, (47, 89, 131))
        return Image.new("RGBA", size, (47, 89, 131, 128))


def _deepzoom_class():
    pkg = types.ModuleType("Aslide")
    pkg.__path__ = []
    sub = types.ModuleType("Aslide.sdpc")
    sub.__path__ = []
    slide = types.ModuleType("Aslide.sdpc.sdpc_slide")
    slide.SdpcSlide = _Slide
    source = Path(__file__).resolve().parents[1] / "Aslide/sdpc/sdpc_deepzoom.py"
    spec = importlib.util.spec_from_file_location("Aslide.sdpc.sdpc_deepzoom", source)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"Aslide": pkg, "Aslide.sdpc": sub,
                                  "Aslide.sdpc.sdpc_slide": slide}):
        spec.loader.exec_module(module)
    return module.DeepZoomGenerator


class SdpcDeepZoomTests(unittest.TestCase):
    def test_rgb_tile_preserves_opaque_pixels_without_compositing(self):
        generator = _deepzoom_class()(_Slide("RGB"), tile_size=8, overlap=0)
        with patch("PIL.Image.composite", side_effect=AssertionError("unneeded composite")):
            tile = generator.get_tile(generator.level_count - 1, (0, 0))
        self.assertEqual(tile.mode, "RGB")
        self.assertEqual(tile.size, (8, 8))
        self.assertEqual(tile.getpixel((4, 4)), (47, 89, 131))

    def test_rgba_tile_still_uses_its_alpha_to_composite(self):
        generator = _deepzoom_class()(_Slide("RGBA"), tile_size=8, overlap=0)
        tile = generator.get_tile(generator.level_count - 1, (0, 0))
        expected = Image.composite(Image.new("RGBA", (8, 8), (47, 89, 131, 128)),
                                   Image.new("RGB", (8, 8), "white"),
                                   Image.new("RGBA", (8, 8), (47, 89, 131, 128)))
        self.assertEqual(tile.mode, "RGB")
        self.assertEqual(tile.tobytes(), expected.tobytes())


if __name__ == "__main__":
    unittest.main()
