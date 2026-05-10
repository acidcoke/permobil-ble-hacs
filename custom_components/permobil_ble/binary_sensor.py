"""Binary sensor entities for Permobil ConnectMe."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PermobilCoordinator
from .entity import PermobilEntity
from .parser import WheelchairInfo


@dataclass(frozen=True, kw_only=True)
class PermobilBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[WheelchairInfo], bool]


BINARY_SENSORS: tuple[PermobilBinarySensorDescription, ...] = (
    PermobilBinarySensorDescription(
        key="driving",
        translation_key="driving",
        device_class=BinarySensorDeviceClass.MOVING,
        value_fn=lambda d: d.driving,
    ),
    PermobilBinarySensorDescription(
        key="actuator_active",
        translation_key="actuator_active",
        value_fn=lambda d: d.actuator_active,
    ),
    PermobilBinarySensorDescription(
        key="seat_up",
        translation_key="seat_up",
        value_fn=lambda d: d.seat_up,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PermobilCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(PermobilBinarySensor(coordinator, desc) for desc in BINARY_SENSORS)


class PermobilBinarySensor(PermobilEntity, BinarySensorEntity):
    entity_description: PermobilBinarySensorDescription

    def __init__(
        self,
        coordinator: PermobilCoordinator,
        description: PermobilBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None:
            return None
        return self.entity_description.value_fn(data)
