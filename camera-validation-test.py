import argparse
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional, Tuple, cast

import cv2
import depthai as dai
import numpy as np

OAK_WIDTH = 640
OAK_HEIGHT = 360
OAK_FPS = 20
ARDUCAM_WIDTH = 640
ARDUCAM_HEIGHT = 360
DEFAULT_TIMEOUT_S = 8.0

logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s [%(levelname)s] %(message)s",
	datefmt="%Y-%m-%d %H:%M:%S",
)


@dataclass
class ValidationResult:
	name: str
	ok: bool
	details: str


class OakDValidator:
	def __init__(self, width: int, height: int, fps: int) -> None:
		self.width = width
		self.height = height
		self.fps = fps

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
		rgb.setFps(self.fps)

		left.setBoardSocket(dai.CameraBoardSocket.CAM_B)
		right.setBoardSocket(dai.CameraBoardSocket.CAM_C)
		left.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
		right.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
		left.setFps(self.fps)
		right.setFps(self.fps)

		stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.DENSITY)
		stereo.setDepthAlign(dai.CameraBoardSocket.CAM_A)
		stereo.setOutputSize(self.width, self.height)
		stereo.setSubpixel(True)
		stereo.setLeftRightCheck(True)

		left.out.link(stereo.left)
		right.out.link(stereo.right)
		return pipeline, rgb.preview, stereo.depth

	def validate(self, timeout_s: float) -> ValidationResult:
		pipeline: Optional[dai.Pipeline] = None
		try:
			pipeline, rgb_output, depth_output = self._build_pipeline()
			rgb_queue = rgb_output.createOutputQueue(maxSize=2, blocking=False)
			depth_queue = depth_output.createOutputQueue(maxSize=2, blocking=False)
			pipeline.start()

			deadline = time.monotonic() + timeout_s
			rgb_frame: Optional[np.ndarray] = None
			depth_frame: Optional[np.ndarray] = None

			while time.monotonic() < deadline:
				if rgb_frame is None:
					rgb_packet = rgb_queue.tryGet()
					if rgb_packet is not None:
						candidate = cast(Any, rgb_packet).getCvFrame()
						if isinstance(candidate, np.ndarray) and candidate.size > 0:
							rgb_frame = candidate.copy()

				if depth_frame is None:
					depth_packet = depth_queue.tryGet()
					if depth_packet is not None:
						candidate = cast(Any, depth_packet).getFrame()
						if isinstance(candidate, np.ndarray) and candidate.size > 0:
							depth_frame = candidate.copy()

				if rgb_frame is not None and depth_frame is not None:
					center_depth_m = self._center_depth_m(depth_frame)
					depth_text = (
						f", center depth {center_depth_m:.2f} m"
						if np.isfinite(center_depth_m)
						else ""
					)
					return ValidationResult(
						name="OAK-D",
						ok=True,
						details=(
							f"RGB {rgb_frame.shape[1]}x{rgb_frame.shape[0]}, "
							f"depth {depth_frame.shape[1]}x{depth_frame.shape[0]}"
							f"{depth_text}"
						),
					)

				time.sleep(0.01)

			missing = []
			if rgb_frame is None:
				missing.append("RGB")
			if depth_frame is None:
				missing.append("depth")
			return ValidationResult(
				name="OAK-D",
				ok=False,
				details=f"Timed out waiting for {', '.join(missing)} frame(s)",
			)
		except Exception as exc:
			return ValidationResult(name="OAK-D", ok=False, details=str(exc))
		finally:
			if pipeline is not None:
				try:
					pipeline.stop()
				except Exception:
					logging.debug("Failed to stop OAK-D pipeline cleanly", exc_info=True)

	def _center_depth_m(self, depth_frame: np.ndarray) -> float:
		center_y = depth_frame.shape[0] // 2
		center_x = depth_frame.shape[1] // 2
		center_patch = depth_frame[
			max(0, center_y - 4) : min(depth_frame.shape[0], center_y + 5),
			max(0, center_x - 4) : min(depth_frame.shape[1], center_x + 5),
		]
		valid = center_patch[center_patch > 0]
		return float(np.median(valid) / 1000.0) if valid.size else float("nan")


class ArducamValidator:
	def __init__(self, device_index: int, width: int, height: int) -> None:
		self.device_index = device_index
		self.width = width
		self.height = height

	def validate(self, timeout_s: float) -> ValidationResult:
		capture = cv2.VideoCapture(self.device_index)
		if not capture.isOpened():
			capture.release()
			return ValidationResult(
				name="Arducam",
				ok=False,
				details=f"Unable to open video device {self.device_index}",
			)

		try:
			capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
			capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
			deadline = time.monotonic() + timeout_s

			while time.monotonic() < deadline:
				ok, frame = capture.read()
				if ok and isinstance(frame, np.ndarray) and frame.size > 0:
					return ValidationResult(
						name="Arducam",
						ok=True,
						details=f"Frame {frame.shape[1]}x{frame.shape[0]} from device {self.device_index}",
					)
				time.sleep(0.05)

			return ValidationResult(
				name="Arducam",
				ok=False,
				details=(
					f"Timed out waiting for frames from video device {self.device_index}"
				),
			)
		finally:
			capture.release()


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Validate that the OAK-D and Arducam are connected and streaming"
	)
	parser.add_argument(
		"--timeout",
		type=float,
		default=DEFAULT_TIMEOUT_S,
		help="Seconds to wait for each camera stream before failing",
	)
	parser.add_argument(
		"--arducam-index",
		type=int,
		default=0,
		help="OpenCV device index to use for the Arducam",
	)
	return parser.parse_args()


def main() -> int:
	args = parse_args()
	validators = [
		ArducamValidator(args.arducam_index, ARDUCAM_WIDTH, ARDUCAM_HEIGHT),
		OakDValidator(OAK_WIDTH, OAK_HEIGHT, OAK_FPS),
	]

	results = [validator.validate(args.timeout) for validator in validators]
	for result in results:
		status = "PASS" if result.ok else "FAIL"
		print(f"[{status}] {result.name}: {result.details}")

	return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
	raise SystemExit(main())
