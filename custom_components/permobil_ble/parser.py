"""Permobil ConnectMe (Gen 1) protocol parser.

Ports the Java `Slot2Data`, `MessageParser`, and `WheelchairInfo` logic
from the decompiled MyPermobil app.
"""
from __future__ import annotations

from dataclasses import dataclass

from .const import (
    ANGLE_HYSTERESIS,
    ANGLE_SCALE,
    CHAIR_TYPES_ALT_TILT,
    LIFT_HYSTERESIS,
    SEAT_UP_LIMIT,
    SLOT2_MIN_LEN,
    STATUS_BIT_ACTUATOR_ACTIVE,
    STATUS_BIT_DRIVING,
    TILT_SCALE_ALT,
    TILT_SCALE_DEFAULT,
    VSC_KEY_BACK_ANGLE,
    VSC_KEY_CHAIR_TYPE,
    VSC_KEY_LEG_ANGLE,
    VSC_KEY_LIFT_HEIGHT,
    VSC_KEY_STATUS,
    VSC_KEY_TILT_ANGLE,
    VSC_KEY_VOLTAGE,
)


class Slot2DataError(ValueError):
    """Raised when the TIMER read payload cannot be parsed."""


@dataclass(frozen=True)
class Slot2Data:
    """Parsed TIMER characteristic payload."""

    status_code: int
    sec: int
    serial: str

    @property
    def ownership_held(self) -> bool:
        return self.status_code != 0


def parse_slot2(data: bytes) -> Slot2Data:
    if data is None or len(data) < SLOT2_MIN_LEN:
        raise Slot2DataError(f"slot2 payload too short: {len(data) if data else 0} < {SLOT2_MIN_LEN}")
    status_code = (data[0] & 0x80) >> 7
    sec = data[1] & 0xFF
    serial = data[4:].decode("utf-8", errors="strict").strip().rstrip("\x00").strip()
    return Slot2Data(status_code=status_code, sec=sec, serial=serial)


class Hysteresis:
    """Deadband filter — emit only when delta exceeds threshold."""

    __slots__ = ("threshold", "_last")

    def __init__(self, threshold: float) -> None:
        self.threshold = threshold
        self._last: float | None = None

    def filter(self, value: float) -> float:
        if self._last is None or abs(value - self._last) > self.threshold:
            self._last = value
        return self._last


def _to_signed16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


class FrameBuffer:
    """Accumulates RX bytes and yields complete frames split on CRLF."""

    __slots__ = ("_buf",)

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buf.extend(chunk)
        out: list[bytes] = []
        while True:
            idx = self._buf.find(b"\r\n")
            if idx < 0:
                break
            frame = bytes(self._buf[:idx])
            del self._buf[: idx + 2]
            if frame:
                out.append(frame)
        return out


def parse_vsc_frame(frame: bytes) -> dict[int, int] | None:
    """Parse one VSC frame body (without trailing CRLF).

    Returns a dict of key -> raw int value, or None if malformed or
    checksum-invalid.
    """
    if not frame or frame[0:1] != b"S":
        return None
    k_idx = frame.rfind(b"K")
    if k_idx < 1 or k_idx + 3 > len(frame):
        return None
    body = frame[:k_idx]
    cksum_str = frame[k_idx + 1 : k_idx + 3]
    try:
        expected = int(cksum_str, 16)
    except ValueError:
        return None
    actual = sum(body) & 0xFF
    if actual != expected:
        return None
    out: dict[int, int] = {}
    for entry in body.split(b"S"):
        if not entry:
            continue
        k, sep, v = entry.partition(b":")
        if not sep:
            continue
        try:
            out[int(k, 16)] = int(v, 16)
        except ValueError:
            continue
    return out


@dataclass
class WheelchairInfo:
    tilt_angle: float
    recline_angle: float
    legrest_angle: float
    elevation: float
    battery_voltage_raw: int | None
    chair_type: int
    seat_up: bool
    actuator_active: bool
    driving: bool


REQUIRED_KEYS = (
    VSC_KEY_LEG_ANGLE,
    VSC_KEY_BACK_ANGLE,
    VSC_KEY_TILT_ANGLE,
    VSC_KEY_LIFT_HEIGHT,
    VSC_KEY_CHAIR_TYPE,
)


class TelemetryDecoder:
    """Stateful decoder: VSC frame dict -> WheelchairInfo (with hysteresis)."""

    def __init__(self) -> None:
        self._h_tilt = Hysteresis(ANGLE_HYSTERESIS)
        self._h_recline = Hysteresis(ANGLE_HYSTERESIS)
        self._h_legrest = Hysteresis(ANGLE_HYSTERESIS)
        self._h_lift = Hysteresis(LIFT_HYSTERESIS)

    def decode(self, values: dict[int, int]) -> WheelchairInfo | None:
        if any(k not in values for k in REQUIRED_KEYS):
            return None

        chair_type = values[VSC_KEY_CHAIR_TYPE] & 0xFF
        tilt_scale = TILT_SCALE_ALT if chair_type in CHAIR_TYPES_ALT_TILT else TILT_SCALE_DEFAULT

        tilt_raw = _to_signed16(values[VSC_KEY_TILT_ANGLE]) * tilt_scale
        back_raw = _to_signed16(values[VSC_KEY_BACK_ANGLE]) * ANGLE_SCALE
        leg_raw = _to_signed16(values[VSC_KEY_LEG_ANGLE]) * ANGLE_SCALE
        lift_raw = float(_to_signed16(values[VSC_KEY_LIFT_HEIGHT]))

        tilt = self._h_tilt.filter(tilt_raw)
        recline = self._h_recline.filter(back_raw - tilt)
        legrest = self._h_legrest.filter(leg_raw - tilt)
        elevation = self._h_lift.filter(lift_raw)

        status = values.get(VSC_KEY_STATUS, 0) & 0xFF
        voltage = values.get(VSC_KEY_VOLTAGE)

        return WheelchairInfo(
            tilt_angle=round(tilt, 1),
            recline_angle=round(recline, 1),
            legrest_angle=round(legrest, 1),
            elevation=elevation,
            battery_voltage_raw=voltage,
            chair_type=chair_type,
            seat_up=elevation >= SEAT_UP_LIMIT,
            actuator_active=bool(status & STATUS_BIT_ACTUATOR_ACTIVE),
            driving=bool(status & STATUS_BIT_DRIVING),
        )
