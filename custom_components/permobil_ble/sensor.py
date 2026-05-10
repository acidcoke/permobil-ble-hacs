"""Sensor entities for Permobil ConnectMe."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import DEGREE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PermobilCoordinator
from .entity import PermobilEntity
from .parser import WheelchairInfo


@dataclass(frozen=True, kw_only=True)
class PermobilSensorDescription(SensorEntityDescription):
    value_fn: Callable[[WheelchairInfo], float | int | None]


SENSORS: tuple[PermobilSensorDescription, ...] = (
    PermobilSensorDescription(
        key="tilt_angle",
        translation_key="tilt_angle",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.tilt_angle,
    ),
    PermobilSensorDescription(
        key="recline_angle",
        translation_key="recline_angle",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.recline_angle,
    ),
    PermobilSensorDescription(
        key="legrest_angle",
        translation_key="legrest_angle",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.legrest_angle,
    ),
    PermobilSensorDescription(
        key="elevation",
        translation_key="elevation",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.elevation,
    ),
    PermobilSensorDescription(
        key="battery_voltage_raw",
        translation_key="battery_voltage_raw",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.battery_voltage_raw,
        entity_registry_enabled_default=False,
    ),
    PermobilSensorDescription(
        key="chair_type",
        translation_key="chair_type",
        value_fn=lambda d: d.chair_type,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PermobilCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(PermobilSensor(coordinator, desc) for desc in SENSORS)


class PermobilSensor(PermobilEntity, SensorEntity):
    entity_description: PermobilSensorDescription

    def __init__(self, coordinator: PermobilCoordinator, description: PermobilSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | None:
        data = self.coordinator.data
        if data is None:
            return None
        return self.entity_description.value_fn(data)
