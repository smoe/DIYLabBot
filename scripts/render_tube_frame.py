"""Render H02 with the common model-health/provenance renderer."""
import render_tube_carrier as renderer
import tube_frame_model

if __name__ == '__main__':
    renderer.model = tube_frame_model
    renderer.main()
