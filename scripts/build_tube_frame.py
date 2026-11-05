"""Build H02 using the shared native-CAD pipeline retained from H01."""
import build_tube_carrier as pipeline
import tube_frame_model

if __name__ == '__main__':
    pipeline.model = tube_frame_model
    pipeline.main()
