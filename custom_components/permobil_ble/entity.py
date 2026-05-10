"""Common base class for Permobil entities."""
from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PermobilCoordinator


class PermobilEntity(CoordinatorEntity[PermobilCoordinator]):
    """Base class — wires device info and unique id."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PermobilCoordinator, key: str) -> None:
        super().__init__(coordinator)
        serial = coordinator.slot2.serial if coordinator.slot2 else coordinator.address
        self._attr_unique_id = f"{coordinator.address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            name=f"Permobil {serial}",
            manufacturer="Permobil",
            model="ConnectMe (Gen 1)",
            serial_number=serial,
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None
