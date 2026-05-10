"""Coordinator for the Permobil ConnectMe BLE integration.

Holds a persistent GATT connection, performs the take-ownership handshake,
subscribes to RX notifications, parses VSC frames, and pushes a
`WheelchairInfo` snapshot to entities via `async_set_updated_data`.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
)
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CMD_TAKE_OWNERSHIP,
    DOMAIN,
    RX_UUID,
    SERVICE_UUID,
    TIMER_UUID,
    TX_UUID,
)

# Gen 2 (PowerPlatform) seat service — used only to detect mismatched chairs
# and emit a helpful error.
GEN2_SEAT_SERVICE = "6164616d-6261-636f-a4c4-4e9c678ad2a0"
from .parser import (
    FrameBuffer,
    Slot2Data,
    Slot2DataError,
    TelemetryDecoder,
    WheelchairInfo,
    parse_slot2,
    parse_vsc_frame,
)

_LOGGER = logging.getLogger(__name__)

RECONNECT_BACKOFF_S = (5, 10, 20, 30, 60)


class PermobilCoordinator(DataUpdateCoordinator[WheelchairInfo]):
    """Drives the BLE connection and feeds entity state."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, address: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {address}",
            update_interval=None,
        )
        self.address = address.upper()
        self.entry = entry
        self.slot2: Slot2Data | None = None
        self._decoder = TelemetryDecoder()
        self._buffer = FrameBuffer()
        self._client: BleakClient | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._connected_evt = asyncio.Event()

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def async_start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = self.hass.loop.create_task(self._run())

    async def async_stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        await self._disconnect()

    async def _run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                await self._connect_and_stream()
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Permobil %s: session ended (%s)", self.address, err)
            if self._stop.is_set():
                break
            delay = RECONNECT_BACKOFF_S[min(attempt, len(RECONNECT_BACKOFF_S) - 1)]
            attempt += 1
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
                return
            except asyncio.TimeoutError:
                pass

    def _log_gatt_tree(self, client: BleakClient) -> None:
        services = client.services
        if not services:
            _LOGGER.warning("Permobil %s: no services discovered", self.address)
            return
        for svc in services:
            _LOGGER.info("Permobil %s: service %s", self.address, svc.uuid)
            for char in svc.characteristics:
                _LOGGER.info(
                    "Permobil %s:   char %s handle=%s props=%s",
                    self.address,
                    char.uuid,
                    char.handle,
                    char.properties,
                )

    def _verify_gen1_service(self, client: BleakClient) -> None:
        uuids = {s.uuid.lower() for s in client.services}
        if SERVICE_UUID.lower() in uuids:
            return
        if GEN2_SEAT_SERVICE in uuids:
            raise RuntimeError(
                "This chair exposes the Gen 2 (PowerPlatform) seat service, not "
                "the Gen 1 (ConnectMe) service. This integration currently only "
                "supports Gen 1 chairs."
            )
        raise RuntimeError(
            f"Service {SERVICE_UUID} not present on {self.address}. "
            "This device is not a supported Permobil ConnectMe chair."
        )

    async def _resolve_device(self) -> BLEDevice | None:
        return bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)

    async def _connect_and_stream(self) -> None:
        device = await self._resolve_device()
        if device is None:
            raise RuntimeError(f"BLE device {self.address} not present")

        _LOGGER.debug("Permobil %s: connecting", self.address)
        client = await establish_connection(
            BleakClientWithServiceCache,
            device,
            self.address,
            disconnected_callback=self._on_disconnected,
            use_services_cache=False,
            max_attempts=3,
        )
        self._client = client
        self._connected_evt.set()

        try:
            self._log_gatt_tree(client)
            self._verify_gen1_service(client)
            timer_data = await client.read_gatt_char(TIMER_UUID)
            try:
                self.slot2 = parse_slot2(bytes(timer_data))
            except Slot2DataError as err:
                raise RuntimeError(f"slot2 parse failed: {err}") from err
            _LOGGER.info(
                "Permobil %s: serial=%s ownership_held=%s sec=%d",
                self.address,
                self.slot2.serial,
                self.slot2.ownership_held,
                self.slot2.sec,
            )

            if self.slot2.sec > 0:
                _LOGGER.info(
                    "Permobil %s: ownership held by another client, waiting %ds",
                    self.address,
                    self.slot2.sec,
                )
                await asyncio.sleep(self.slot2.sec)

            # Match the MyPermobil app order: write TAKE first, then enable
            # notifications. WheelchairSocket.AnonymousClass6 -> takeOwnership
            # -> setCharacteristicNotification.
            _LOGGER.debug("Permobil %s: writing #TAKE", self.address)
            await client.write_gatt_char(TX_UUID, CMD_TAKE_OWNERSHIP, response=True)
            _LOGGER.debug("Permobil %s: subscribing RX", self.address)
            await client.start_notify(RX_UUID, self._on_rx)
            _LOGGER.info("Permobil %s: streaming telemetry", self.address)

            while client.is_connected and not self._stop.is_set():
                await asyncio.sleep(1.0)
        finally:
            await self._safe_stop_notify()
            await self._disconnect()

    def _on_rx(self, _sender: Any, data: bytearray) -> None:
        _LOGGER.debug("Permobil %s: rx %d bytes: %s", self.address, len(data), bytes(data).hex())
        for frame in self._buffer.feed(bytes(data)):
            values = parse_vsc_frame(frame)
            if values is None:
                _LOGGER.debug("Permobil %s: rejected frame %r", self.address, frame)
                continue
            _LOGGER.debug("Permobil %s: frame keys=%s", self.address, sorted(values.keys()))
            info = self._decoder.decode(values)
            if info is None:
                _LOGGER.debug("Permobil %s: incomplete frame, missing required keys", self.address)
                continue
            self.async_set_updated_data(info)

    def _on_disconnected(self, _client: BleakClient) -> None:
        _LOGGER.debug("Permobil %s: GATT disconnected", self.address)
        self._connected_evt.clear()

    async def _safe_stop_notify(self) -> None:
        if self._client is None or not self._client.is_connected:
            return
        try:
            await self._client.stop_notify(RX_UUID)
        except Exception:  # noqa: BLE001
            pass

    async def _disconnect(self) -> None:
        client = self._client
        self._client = None
        self._connected_evt.clear()
        if client is None:
            return
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
