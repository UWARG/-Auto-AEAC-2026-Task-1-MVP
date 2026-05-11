import time

from pymavlink import mavutil


FC_ADDR = "udpout:192.168.144.14:5000"
HEARTBEAT_TIMEOUT = 1.0


def main() -> int:
	print(f"Connecting to {FC_ADDR}...")
	mav = mavutil.mavlink_connection(
		FC_ADDR,
		dialect="ardupilotmega",
	)

	print("Waiting for first heartbeat...")
	heartbeat = mav.wait_heartbeat(timeout=HEARTBEAT_TIMEOUT)
	if heartbeat is None:
		raise TimeoutError(
			f"No heartbeat received within {HEARTBEAT_TIMEOUT} seconds from {FC_ADDR}."
		)

	print("Connected. Printing heartbeats once per second.")
	print(heartbeat)
	print(f"System ID: {mav.target_system}, Component ID: {mav.target_component}")

	while True:
		loop_started = time.monotonic()
		heartbeat = mav.recv_match(
			type="HEARTBEAT",
			blocking=True,
			timeout=HEARTBEAT_TIMEOUT,
		)
		if heartbeat is None:
			print("No heartbeat received in the last second.")
		else:
			print(heartbeat)

		remaining = HEARTBEAT_TIMEOUT - (time.monotonic() - loop_started)
		if remaining > 0:
			time.sleep(remaining)

	return 0


if __name__ == "__main__":
	raise SystemExit(main())
