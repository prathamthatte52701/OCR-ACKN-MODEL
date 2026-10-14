import os

# Backup limit inside OpenCV (see core/image_limits.MAX_PIXELS). Must be set before cv2 is
# imported anywhere; the package init runs before every submodule.
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", "50000000")
