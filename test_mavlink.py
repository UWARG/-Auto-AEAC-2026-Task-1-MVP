import math
import time
from collections import Counter

from pymavlink import mavutil


FC_ADDR = "/dev/ttyAMA0"
FC_BAUD = 115200  # Pixhawk telemetry port baud (matches pymavlink default)
HEARTBEAT_TIMEOUT = 1.0
ATTITUDE_INTERVAL_US = 100_000  # 10 Hz
REREQUEST_PERIOD_S = 2.0
STATS_PERIOD_S = 5.0


def send_requests(mav, target_component: int) -> None:
	"""Ask the FC for ATTITUDE via both modern and legacy methods."""
	mav.mav.command_long_send(
		mav.target_system,
		target_component,
		mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
		0,
		float(mavutil.mavlink.MAVLINK_MSG_ID_ATTITUDE),
		float(ATTITUDE_INTERVAL_US),
		0,
		0,
		0,
		0,
		0,
	)
	mav.mav.request_data_stream_send(
		mav.target_system,
		target_component,
		mavutil.mavlink.MAV_DATA_STREAM_EXTRA1,
		10,
		1,
	)
	mav.mav.request_data_stream_send(
		mav.target_system,
		target_component,
		mavutil.mavlink.MAV_DATA_STREAM_ALL,
		4,
		1,
	)


def send_gcs_heartbeat(mav) -> None:
	"""Send our own HEARTBEAT so the FC treats us as an active GCS."""
	mav.mav.heartbeat_send(
		mavutil.mavlink.MAV_TYPE_GCS,
		mavutil.mavlink.MAV_AUTOPILOT_INVALID,
		0,
		0,
		mavutil.mavlink.MAV_STATE_ACTIVE,
	)


def main() -> int:
	print(f"Connecting to {FC_ADDR} at {FC_BAUD} baud...")
	mav = mavutil.mavlink_connection(
		FC_ADDR,
		baud=FC_BAUD,
		dialect="ardupilotmega",
		source_system=255,
		source_component=mavutil.mavlink.MAV_COMP_ID_MISSIONPLANNER,
	)

	print("Waiting for first heartbeat...")
	heartbeat = mav.wait_heartbeat(timeout=10.0)
	if heartbeat is None:
		raise TimeoutError(
			f"No heartbeat received within 10 seconds from {FC_ADDR}."
		)

	src_system = heartbeat.get_srcSystem()
	src_component = heartbeat.get_srcComponent()
	print(f"Heartbeat source sys/comp: {src_system}/{src_component}")
	print(f"target_system={mav.target_system}, target_component={mav.target_component}")

	# Per ArduPilot docs, target_component should normally be 0.
	target_component = 0

	print(
		f"Requesting ATTITUDE every {ATTITUDE_INTERVAL_US} us "
		f"(target sys={mav.target_system}, comp={target_component})..."
	)
	send_gcs_heartbeat(mav)
	send_requests(mav, target_component)

	counts: Counter = Counter()
	last_rerequest = time.monotonic()
	last_stats = time.monotonic()
	last_heartbeat_tx = 0.0

	while True:
		now = time.monotonic()

		if now - last_heartbeat_tx >= 1.0:
			send_gcs_heartbeat(mav)
			last_heartbeat_tx = now

		if now - last_rerequest >= REREQUEST_PERIOD_S:
			send_requests(mav, target_component)
			last_rerequest = now

		msg = mav.recv_match(blocking=True, timeout=0.2)
		if msg is not None:
			mtype = msg.get_type()
			counts[mtype] += 1

			if mtype == "ATTITUDE":
				pitch_deg = math.degrees(float(msg.pitch))
				roll_deg = math.degrees(float(msg.roll))
				print(
					f"ATTITUDE pitch={msg.pitch:.4f} rad ({pitch_deg:.2f} deg), "
					f"roll={msg.roll:.4f} rad ({roll_deg:.2f} deg)"
				)
			elif mtype == "COMMAND_ACK":
				print(f"COMMAND_ACK: {msg}")
			elif mtype == "STATUSTEXT":
				print(f"STATUSTEXT: {msg.text}")
			elif mtype == "BAD_DATA":
				pass

		if now - last_stats >= STATS_PERIOD_S:
			summary = ", ".join(
				f"{name}:{count}" for name, count in counts.most_common()
			)
			print(f"[stats over {STATS_PERIOD_S:.0f}s] {summary or '(no messages)'}")
			counts.clear()
			last_stats = now

	return 0


if __name__ == "__main__":
	raise SystemExit(main())
