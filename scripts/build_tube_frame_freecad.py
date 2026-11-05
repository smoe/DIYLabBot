"""Bind the H02 semantic source to the existing native FreeCAD adapter."""
import sys
import build_tube_carrier_freecad as adapter
import tube_frame_model

if __name__ == '__main__':
    adapter.model = tube_frame_model
    adapter.main(*sys.argv[1:])
