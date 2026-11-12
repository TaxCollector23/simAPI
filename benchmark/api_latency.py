"""Measure 100 local HTTP test-client runs per robotics fixture (milliseconds)."""
import os

os.environ["SIMAPI_RATE_LIMIT_ENABLED"] = "false"

import logging
import statistics
import time

from fastapi.testclient import TestClient

from api.server import app

logging.disable(logging.CRITICAL)

def run():
    with TestClient(app) as client:
        for name, jump in (("clean", False), ("teleport", True)):
            rows = [{"t": i*.02, "joint_1_position": 1.2 if jump and i == 4 else i*.02,
                     "joint_1_torque": 95 if jump and i == 4 else 10} for i in range(5)]
            times = []
            for _ in range(100):
                started = time.perf_counter()
                response = client.post('/v1/validate/physics-only', json={"data": rows, "simulation_type": "robotics"})
                response.raise_for_status()
                assert response.json()['status'] == ('failed' if jump else 'warning')
                times.append((time.perf_counter()-started)*1000)
            print(f'{name}: runs=100 p50={statistics.median(times):.2f}ms p95={sorted(times)[94]:.2f}ms')

if __name__ == '__main__':
    run()
