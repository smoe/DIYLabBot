"""Native H03 adapter using the common expression-driven mechanical backend."""
import sys
import build_tube_carrier_freecad as adapter
import tube_cam_model
if __name__=='__main__':
    adapter.model=tube_cam_model
    adapter.main(*sys.argv[1:])
