# Home Assistant integration tests

These tests run the integration inside the Home Assistant test harness. They are
separate from the engine tests because the harness is large.

```bash
python3.12 -m venv .venv-ha
.venv-ha/bin/pip install -r tests/ha/requirements.txt
PYTHONPATH=. .venv-ha/bin/pytest tests/ha -q --asyncio-mode=auto
```

The tests cover:

- config flow creation,
- invalid token handling,
- full entry setup with sensors, binary sensors, calendar, button, select, and
  service registration,
- battery control decisions (pure control.py),
- arming and applying a current-interval battery setpoint through mocked
  number/select services,
- unsigned magnitude + direction + operating-mode control (official-Anker flow),
- setpoint inversion and SOC guard decisions.

The harness thread check is disabled on macOS because `pycares`/`aiodns` leaves a
daemon thread behind after the test.
