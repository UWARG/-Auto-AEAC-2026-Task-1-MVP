import logging
import threading
import time
from typing import Any, Optional, Tuple, cast

import cv2
import depthai as dai
import numpy as np

FRAME_WIDTH = 640
FRAME_HEIGHT = 360
FRAME_FPS = 20
JPEG_QUALITY = 90
DEPTH_PNG_COMPRESSION = 3
WINDOW_NAME = "OAK-D RGB + Depth"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

class OakCamera:
    """Background capture for aligned RGB and depth frames from an OAK-D Pro."""

    def __init__(self, width: int, height: int) -> None:
        self.width, self.height = width, height
        self._pipeline: Optional[dai.Pipeline] = None
        self._rgb_queue: Optional[Any] = None
        self._depth_queue: Optional[Any] = None
        self._lock = threading.Lock()
        self._latest_rgb: Optional[np.ndarray] = None
        self._latest_depth: Optional[np.ndarray] = None
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._error_message: Optional[str] = None
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _build_pipeline(self) -> Tuple[dai.Pipeline, Any, Any]:
        pipeline = dai.Pipeline()

        rgb = pipeline.create(dai.node.ColorCamera)
        left = pipeline.create(dai.node.MonoCamera)
        right = pipeline.create(dai.node.MonoCamera)
        stereo = pipeline.create(dai.node.StereoDepth)

        rgb.setBoardSocket(dai.CameraBoardSocket.CAM_A)
        rgb.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
        rgb.setPreviewSize(self.width, self.height)
        rgb.setPreviewKeepAspectRatio(False)
        rgb.setInterleaved(False)
        rgb.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)
        rgb.setFps(FRAME_FPS)

        left.setBoardSocket(dai.CameraBoardSocket.CAM_B)
        right.setBoardSocket(dai.CameraBoardSocket.CAM_C)
        left.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
        right.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
        left.setFps(FRAME_FPS)
        right.setFps(FRAME_FPS)

        stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.DENSITY)
        stereo.setDepthAlign(dai.CameraBoardSocket.CAM_A)
        stereo.setOutputSize(self.width, self.height)
        stereo.setSubpixel(True)
        stereo.setLeftRightCheck(True)

        left.out.link(stereo.left)
        right.out.link(stereo.right)
        return pipeline, rgb.preview, stereo.depth

    def wait_until_ready(self, timeout: float = 10.0) -> None:
        if not self._ready_event.wait(timeout):
            raise TimeoutError("Timed out while waiting for the OAK-D stream")
        if self._error_message is not None:
            raise RuntimeError(self._error_message)

    def _capture_loop(self) -> None:
        try:
            pipeline, rgb_output, depth_output = self._build_pipeline()
            self._rgb_queue = rgb_output.createOutputQueue(maxSize=2, blocking=False)
            self._depth_queue = depth_output.createOutputQueue(
                maxSize=2, blocking=False
            )
            pipeline.start()
            self._pipeline = pipeline
            self._ready_event.set()
        except Exception as exc:
            self._error_message = str(exc)
            self._ready_event.set()
            logging.exception("Failed to initialize OAK-D Pro pipeline")
            return

        try:
            while not self._stop_event.is_set():
                rgb_frame = (
                    self._rgb_queue.tryGet() if self._rgb_queue is not None else None
                )
                depth_frame = (
                    self._depth_queue.tryGet() if self._depth_queue is not None else None
                )

                if rgb_frame is not None:
                    with self._lock:
                        rgb_img = cast(Any, rgb_frame).getCvFrame()
                        self._latest_rgb = rgb_img.copy()
                if depth_frame is not None:
                    with self._lock:
                        depth_img = cast(Any, depth_frame).getFrame().copy()
                        self._latest_depth = depth_img
                if rgb_frame is None and depth_frame is None:
                    time.sleep(0.01)
        finally:
            self._ready_event.set()
            self._rgb_queue = None
            self._depth_queue = None
            if self._pipeline is not None:
                try:
                    self._pipeline.stop()
                except Exception:
                    logging.debug("Failed to stop OAK-D pipeline cleanly", exc_info=True)
                finally:
                    self._pipeline = None

    def get_frames(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        with self._lock:
            rgb_frame = None if self._latest_rgb is None else self._latest_rgb.copy()
            depth_frame = (
                None if self._latest_depth is None else self._latest_depth.copy()
            )
        return rgb_frame, depth_frame

    def _center_depth_m(self, depth_frame: np.ndarray) -> float:
        center_y = depth_frame.shape[0] // 2
        center_x = depth_frame.shape[1] // 2
        center_patch = depth_frame[
            max(0, center_y - 4) : min(depth_frame.shape[0], center_y + 5),
            max(0, center_x - 4) : min(depth_frame.shape[1], center_x + 5),
        ]
        valid = center_patch[center_patch > 0]
        return float(np.median(valid) / 1000.0) if valid.size else float("nan")

    def _depth_visualization(self, depth_frame: np.ndarray) -> np.ndarray:
        valid = depth_frame[depth_frame > 0]
        normalized = np.zeros(depth_frame.shape, dtype=np.uint8)
        if valid.size:
            lower = float(np.percentile(valid, 5))
            upper = float(np.percentile(valid, 95))
            if upper <= lower:
                upper = lower + 1.0
            clipped = np.clip(depth_frame.astype(np.float32), lower, upper)
            scaled = ((clipped - lower) * 255.0 / (upper - lower)).astype(np.uint8)
            normalized = 255 - scaled
            normalized[depth_frame == 0] = 0
        return cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)

    def _draw_crosshair(self, frame: np.ndarray) -> None:
        center_x = frame.shape[1] // 2
        center_y = frame.shape[0] // 2
        cv2.line(frame, (center_x - 12, center_y), (center_x + 12, center_y), (255, 255, 255), 1)
        cv2.line(frame, (center_x, center_y - 12), (center_x, center_y + 12), (255, 255, 255), 1)

    def _placeholder_frame(self) -> np.ndarray:
        frame = np.zeros((self.height, self.width * 2, 3), dtype=np.uint8)
        cv2.putText(
            frame,
            "Waiting for OAK-D frames...",
            (20, self.height // 2 - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            "Press q or Esc to exit",
            (20, self.height // 2 + 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (180, 180, 180),
            1,
            cv2.LINE_AA,
        )
        return frame

    def build_preview_frame(self) -> np.ndarray:
        rgb_frame, depth_frame = self.get_frames()
        if rgb_frame is None or depth_frame is None:
            return self._placeholder_frame()

        depth_vis = self._depth_visualization(depth_frame)
        center_depth_m = self._center_depth_m(depth_frame)

        self._draw_crosshair(rgb_frame)
        self._draw_crosshair(depth_vis)

        cv2.putText(
            rgb_frame,
            "RGB",
            (12, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        depth_text = (
            f"Depth center: {center_depth_m:.2f} m"
            if np.isfinite(center_depth_m)
            else "Depth center: n/a"
        )
        cv2.putText(
            depth_vis,
            depth_text,
            (12, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        return np.hstack((rgb_frame, depth_vis))

    def capture_payloads(self) -> Tuple[bytes, bytes, float]:
        rgb_frame, depth_frame = self.get_frames()
        if rgb_frame is None or depth_frame is None:
            return b"", b"", float("nan")

        ok_jpeg, jpeg_buf = cv2.imencode(
            ".jpg",
            rgb_frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
        )
        ok_png, depth_buf = cv2.imencode(
            ".png",
            depth_frame,
            [int(cv2.IMWRITE_PNG_COMPRESSION), DEPTH_PNG_COMPRESSION],
        )
        if not ok_jpeg or not ok_png:
            return b"", b"", float("nan")

        center_depth_m = self._center_depth_m(depth_frame)
        return jpeg_buf.tobytes(), depth_buf.tobytes(), center_depth_m

    def release(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)


def main() -> None:
    camera = OakCamera(FRAME_WIDTH, FRAME_HEIGHT)
    try:
        camera.wait_until_ready(timeout=10.0)
        logging.info("Starting OAK-D preview. Press q or Esc to exit.")

        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW_NAME, FRAME_WIDTH * 2, FRAME_HEIGHT)

        while True:
            cv2.imshow(WINDOW_NAME, camera.build_preview_frame())
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
    except KeyboardInterrupt:
        logging.info("Stopping OAK-D preview")
    except (RuntimeError, TimeoutError) as exc:
        logging.error("Unable to start OAK-D preview: %s", exc)
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()


