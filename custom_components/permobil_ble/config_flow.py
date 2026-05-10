"""Config flow for Permobil ConnectMe."""
from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers.device_registry import format_mac

from .const import DOMAIN, SERVICE_UUID

MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$")


class PermobilConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Permobil ConnectMe."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_address: str | None = None
        self._discovered_name: str | None = None
        self._discovered: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Triggered by HA when a chair advertisement is seen."""
        await self.async_set_unique_id(format_mac(discovery_info.address))
        self._abort_if_unique_id_configured()

        if SERVICE_UUID.lower() not in (u.lower() for u in discovery_info.service_uuids):
            return self.async_abort(reason="not_supported")

        self._discovered_address = discovery_info.address
        self._discovered_name = discovery_info.name or discovery_info.address
        self.context["title_placeholders"] = {"name": self._discovered_name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovered_address is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered_name or self._discovered_address,
                data={CONF_ADDRESS: self._discovered_address},
            )
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._discovered_name or self._discovered_address},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a discovered chair, or proceed to manual MAC entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            address: str = user_input[CONF_ADDRESS]
            if address == "__manual__":
                return await self.async_step_manual()
            await self.async_set_unique_id(format_mac(address), raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=self._discovered.get(address, address),
                data={CONF_ADDRESS: address},
            )

        current_addresses = {e.unique_id for e in self._async_current_entries()}
        for info in async_discovered_service_info(self.hass):
            mac = format_mac(info.address)
            if mac in current_addresses:
                continue
            uuids_lc = [u.lower() for u in info.service_uuids]
            label = info.name or info.address
            if SERVICE_UUID.lower() in uuids_lc:
                self._discovered[info.address] = f"{label} (Permobil)"
            else:
                # show all nearby BLE devices so the user can still pick the
                # chair if it doesn't advertise the service UUID in adv data
                self._discovered[info.address] = label

        choices: dict[str, str] = dict(sorted(self._discovered.items(), key=lambda kv: kv[1]))
        choices["__manual__"] = "Enter MAC manually..."

        schema = vol.Schema({vol.Required(CONF_ADDRESS): vol.In(choices)})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper().replace("-", ":")
            if not MAC_RE.match(address):
                errors[CONF_ADDRESS] = "invalid_mac"
            else:
                await self.async_set_unique_id(format_mac(address), raise_on_progress=False)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=address, data={CONF_ADDRESS: address})

        schema = vol.Schema({vol.Required(CONF_ADDRESS): str})
        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)
