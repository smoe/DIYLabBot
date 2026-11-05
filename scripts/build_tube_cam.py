"""Build H03 from the shared robot-operated cam/latch source."""
import tube_cam_model
import build_tube_carrier as pipeline
if __name__=='__main__':
    pipeline.model=tube_cam_model
    pipeline.main()
