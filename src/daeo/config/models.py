"""Configuration schema for DAEO 2.

The schema is the single source of truth for forms, validation, API payloads, and
documentation. It is intentionally strict: unknown keys are errors, and there are no
legacy aliases or migration layers.
"""

from __future__ import annotations

from datetime import date, time
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from daeo.domain.enums import (
    Country,
    GridMode,
    Interval,
    LoadSource,
    Objective,
    PriceSource,
    SolarForecastSource,
    TariffPreset,
    TaskAction,
)

ENTITY_ID_PATTERN = r"^[a-z_][a-z0-9_]*\.[a-z0-9_]+$"

EntityId = Annotated[
    str,
    StringConstraints(pattern=ENTITY_ID_PATTERN),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": ENTITY_ID_PATTERN,
            "x-help": "Home Assistant entity ID in the form domain.object_id.",
        }
    ),
]


class DaeoModel(BaseModel):
    """Base model with strict validation."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class HomeConfig(DaeoModel):
    """Location and locale."""

    name: str = Field(
        default="Home",
        min_length=1,
        max_length=80,
        json_schema_extra={"x-ui-section": "Home", "x-ui-group": "Home"},
    )
    latitude: float = Field(
        default=52.37,
        ge=-90,
        le=90,
        json_schema_extra={"x-ui-section": "Home", "x-ui-group": "Home"},
    )
    longitude: float = Field(
        default=4.89,
        ge=-180,
        le=180,
        json_schema_extra={"x-ui-section": "Home", "x-ui-group": "Home"},
    )
    timezone: str = Field(
        default="Europe/Amsterdam",
        json_schema_extra={"x-ui-section": "Home", "x-ui-group": "Home"},
    )
    country: Country = Field(
        default=Country.NL,
        json_schema_extra={"x-ui-section": "Home", "x-ui-group": "Home"},
    )
    currency: Literal["EUR"] = Field(
        default="EUR",
        json_schema_extra={"x-ui-section": "Home", "x-ui-group": "Home"},
    )


class PricingConfig(DaeoModel):
    """Day-ahead prices and all-in tariff components."""

    source: PriceSource = Field(
        default=PriceSource.ENTSOE,
        description="Where day-ahead spot prices come from.",
        json_schema_extra={
            "x-ui-group": "Pricing",
            "x-ui-section": "Price source",
            "x-help": "Use an existing HA price sensor when possible. Otherwise choose "
            "EnergyZero (NL, all-in consumer prices), ENTSO-E, Nordpool, Tibber, or a "
            "fixed tariff.",
        },
    )
    area: str = Field(
        default="NL",
        min_length=2,
        max_length=8,
        description="Bidding zone or price area.",
        json_schema_extra={"x-ui-group": "Pricing", "x-ui-section": "Price source"},
    )
    price_sensor: EntityId | None = Field(
        default=None,
        description="Existing HA sensor with the all-in import price in EUR/kWh.",
        json_schema_extra={
            "x-ui-group": "Pricing",
            "x-ui-section": "Price source",
            "x-ui-widget-filter": "sensor",
            "x-unit": "EUR/kWh",
        },
    )
    preset: TariffPreset = Field(
        default=TariffPreset.NL,
        json_schema_extra={"x-ui-group": "Pricing", "x-ui-section": "Tariff"},
    )
    fixed_import_price_eur_kwh: float | None = Field(
        default=None,
        ge=0,
        json_schema_extra={
            "x-ui-group": "Pricing",
            "x-ui-section": "Price source",
            "x-unit": "EUR/kWh",
        },
    )
    fixed_export_price_eur_kwh: float | None = Field(
        default=None,
        ge=0,
        json_schema_extra={
            "x-ui-group": "Pricing",
            "x-ui-section": "Price source",
            "x-unit": "EUR/kWh",
        },
    )
    supplier_markup_import_eur_kwh: float = Field(
        default=0.02,
        ge=0,
        json_schema_extra={
            "x-ui-group": "Pricing",
            "x-ui-section": "Tariff",
            "x-unit": "EUR/kWh",
        },
    )
    supplier_markup_export_eur_kwh: float = Field(
        default=0.0,
        ge=0,
        json_schema_extra={
            "x-ui-group": "Pricing",
            "x-ui-section": "Tariff",
            "x-unit": "EUR/kWh",
        },
    )
    energy_tax_import_eur_kwh: float = Field(
        default=0.11,
        ge=0,
        json_schema_extra={
            "x-ui-group": "Pricing",
            "x-ui-section": "Tariff",
            "x-unit": "EUR/kWh",
        },
    )
    energy_tax_export_eur_kwh: float = Field(
        default=0.0,
        ge=0,
        json_schema_extra={
            "x-ui-group": "Pricing",
            "x-ui-section": "Tariff",
            "x-unit": "EUR/kWh",
        },
    )
    vat_pct: float = Field(
        default=21.0,
        ge=0,
        le=100,
        json_schema_extra={
            "x-ui-group": "Pricing",
            "x-ui-section": "Tariff",
            "x-unit": "%",
        },
    )
    feed_in_tariff_eur_kwh: float = Field(
        default=0.0,
        ge=0,
        json_schema_extra={
            "x-ui-group": "Pricing",
            "x-ui-section": "Tariff",
            "x-unit": "EUR/kWh",
        },
    )
    tax_refund: bool = Field(
        default=True,
        json_schema_extra={
            "x-ui-group": "Pricing",
            "x-ui-section": "Tariff",
            "x-help": "Whether energy tax paid on import is refunded on export.",
        },
    )
    contract_start: date | None = Field(
        default=None,
        json_schema_extra={"x-ui-group": "Pricing", "x-ui-section": "Contract"},
    )
    multiplier_import: float = Field(
        default=1.0,
        gt=0,
        json_schema_extra={"x-ui-group": "Pricing", "x-ui-section": "Tariff"},
    )
    multiplier_export: float = Field(
        default=1.0,
        gt=0,
        json_schema_extra={"x-ui-group": "Pricing", "x-ui-section": "Tariff"},
    )

    @model_validator(mode="after")
    def check_source_fields(self) -> Self:
        if self.source is PriceSource.HA_SENSOR and self.price_sensor is None:
            raise ValueError("price_sensor is required when source is ha_sensor")
        if self.source is PriceSource.FIXED and self.fixed_import_price_eur_kwh is None:
            raise ValueError("fixed_import_price_eur_kwh is required when source is fixed")
        return self


class LoadConfig(DaeoModel):
    """Historical load profile from the Home Assistant recorder database."""

    source: LoadSource = Field(
        default=LoadSource.SYNTHETIC,
        json_schema_extra={
            "x-ui-group": "Load profile",
            "x-ui-section": "Source",
            "x-help": "Use 'recorder' to derive month/hour load profiles from the HA "
            "recorder statistics. The add-on mounts the HA config directory read-only.",
        },
    )
    database_url: str = Field(
        default="/homeassistant/home-assistant_v2.db",
        json_schema_extra={
            "x-ui-group": "Load profile",
            "x-ui-section": "Source",
            "x-help": "Path to the HA SQLite recorder database. The add-on default is "
            "/homeassistant/home-assistant_v2.db. Only SQLite is supported.",
        },
    )
    lookback_days: int = Field(
        default=365,
        ge=30,
        le=730,
        json_schema_extra={
            "x-ui-group": "Load profile",
            "x-ui-section": "Source",
            "x-unit": "days",
            "x-help": "How much long-term statistics history to aggregate. 365 days "
            "gives one profile per month and hour.",
        },
    )
    grid_import_sensors: list[EntityId] = Field(
        default_factory=list,
        json_schema_extra={
            "x-ui-group": "Load profile",
            "x-ui-section": "Metering",
            "x-ui-widget-filter": "sensor",
            "x-help": "P1/grid import sensors (energy kWh or power W).",
        },
    )
    grid_export_sensors: list[EntityId] = Field(
        default_factory=list,
        json_schema_extra={
            "x-ui-group": "Load profile",
            "x-ui-section": "Metering",
            "x-ui-widget-filter": "sensor",
            "x-help": "P1/grid export sensors (energy kWh or power W).",
        },
    )
    solar_production_sensors: list[EntityId] = Field(
        default_factory=list,
        json_schema_extra={
            "x-ui-group": "Load profile",
            "x-ui-section": "Metering",
            "x-ui-widget-filter": "sensor",
            "x-help": "Actual PV production sensors. Used to turn net P1 import into "
            "gross household load.",
        },
    )
    battery_charge_sensors: list[EntityId] = Field(
        default_factory=list,
        json_schema_extra={
            "x-ui-group": "Load profile",
            "x-ui-section": "Metering",
            "x-ui-widget-filter": "sensor",
        },
    )
    battery_discharge_sensors: list[EntityId] = Field(
        default_factory=list,
        json_schema_extra={
            "x-ui-group": "Load profile",
            "x-ui-section": "Metering",
            "x-ui-widget-filter": "sensor",
        },
    )
    ev_charge_sensors: list[EntityId] = Field(
        default_factory=list,
        json_schema_extra={
            "x-ui-group": "Load profile",
            "x-ui-section": "Metering",
            "x-ui-widget-filter": "sensor",
        },
    )
    boiler_sensors: list[EntityId] = Field(
        default_factory=list,
        json_schema_extra={
            "x-ui-group": "Load profile",
            "x-ui-section": "Metering",
            "x-ui-widget-filter": "sensor",
        },
    )
    heat_pump_sensors: list[EntityId] = Field(
        default_factory=list,
        json_schema_extra={
            "x-ui-group": "Load profile",
            "x-ui-section": "Metering",
            "x-ui-widget-filter": "sensor",
        },
    )
    machine_sensors: list[EntityId] = Field(
        default_factory=list,
        json_schema_extra={
            "x-ui-group": "Load profile",
            "x-ui-section": "Metering",
            "x-ui-widget-filter": "sensor",
        },
    )

    @model_validator(mode="after")
    def check_recorder_sensors(self) -> Self:
        if (
            self.source is LoadSource.RECORDER
            and not self.grid_import_sensors
            and not self.grid_export_sensors
        ):
            raise ValueError(
                "recorder load profiles require at least one grid import or export sensor"
            )
        return self


class ForecastConfig(DaeoModel):
    """Forecast providers."""

    solar_source: SolarForecastSource = Field(
        default=SolarForecastSource.SYNTHETIC,
        description="Source of the PV forecast.",
        json_schema_extra={
            "x-ui-group": "Forecast",
            "x-ui-section": "Solar forecast",
            "x-ui-label": "Source",
            "x-help": "Use Forecast.Solar for a location-aware PV forecast, or keep the "
            "synthetic demo curve. An existing HA forecast sensor is used by the "
            "Home Assistant integration in a later milestone.",
        },
    )


class SolarConfig(DaeoModel):
    """One PV array."""

    name: str = Field(default="Solar", min_length=1, max_length=80)
    enabled: bool = Field(default=True)
    peak_power_wp: float = Field(
        gt=0,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Solar", "x-unit": "Wp"},
    )
    dc_coupled: bool = Field(
        default=False,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Solar",
            "x-help": "DC-coupled arrays charge the battery before the inverter.",
        },
    )
    tilt_deg: float = Field(
        default=35,
        ge=0,
        le=90,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Solar", "x-unit": "deg"},
    )
    azimuth_deg: float = Field(
        default=180,
        ge=0,
        le=360,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Solar", "x-unit": "deg"},
    )
    forecast_entity: EntityId | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Solar",
            "x-ui-widget-filter": "sensor",
            "x-help": "Optional existing PV forecast sensor. When set, no weather API is required.",
        },
    )
    production_entity: EntityId | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Solar",
            "x-ui-widget-filter": "sensor",
        },
    )


class BatteryStageConfig(DaeoModel):
    """One charge or discharge power/efficiency point."""

    power_kw: float = Field(
        ge=0,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery stages",
            "x-unit": "kW",
        },
    )
    efficiency: float = Field(
        gt=0,
        le=1,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery stages",
            "x-help": "AC/DC conversion efficiency at this AC-side power level.",
        },
    )


class SocPowerLimitConfig(DaeoModel):
    """A maximum battery power at a given SOC."""

    soc_pct: float = Field(
        ge=0,
        le=100,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery power limits",
            "x-unit": "%",
        },
    )
    power_kw: float = Field(
        ge=0,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery power limits",
            "x-unit": "kW",
        },
    )


class BatteryConfig(DaeoModel):
    """Battery specification and control surface."""

    name: str = Field(default="Battery", min_length=1, max_length=80)
    enabled: bool = Field(default=True)
    capacity_kwh: float = Field(
        gt=0,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Battery", "x-unit": "kWh"},
    )
    max_charge_kw: float = Field(
        gt=0,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Battery", "x-unit": "kW"},
    )
    max_discharge_kw: float = Field(
        gt=0,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Battery", "x-unit": "kW"},
    )
    efficiency: float = Field(
        default=0.95,
        gt=0,
        le=1,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery",
            "x-help": "Fallback one-way efficiency used when no charge/discharge stages are configured.",
        },
    )
    charge_stages: list[BatteryStageConfig] = Field(
        default_factory=list,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery stages",
            "x-help": "Optional AC-side charge power/efficiency curve. Points are sorted by power; a zero-power point is added automatically.",
        },
    )
    discharge_stages: list[BatteryStageConfig] = Field(
        default_factory=list,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery stages",
            "x-help": "Optional AC-side discharge power/efficiency curve.",
        },
    )
    dc_to_bat_efficiency: float = Field(
        default=1.0,
        gt=0,
        le=1,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery stages",
            "x-help": "Additional efficiency between the inverter DC bus and the battery during charging.",
        },
    )
    bat_to_dc_efficiency: float = Field(
        default=1.0,
        gt=0,
        le=1,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery stages",
            "x-help": "Additional efficiency between the battery and the inverter DC bus during discharging.",
        },
    )
    minimum_power_kw: float = Field(
        default=0.0,
        ge=0,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery",
            "x-unit": "kW",
            "x-help": "Minimum AC-side power when the battery is charging or discharging. Zero disables it.",
        },
    )
    reduce_power_low_soc: list[SocPowerLimitConfig] = Field(
        default_factory=list,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery power limits",
            "x-help": "Piecewise maximum discharge power as SOC approaches the lower limit.",
        },
    )
    reduce_power_high_soc: list[SocPowerLimitConfig] = Field(
        default_factory=list,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery power limits",
            "x-help": "Piecewise maximum charge power as SOC approaches the upper limit.",
        },
    )
    min_soc_end_pct: float | None = Field(
        default=None,
        ge=0,
        le=100,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery",
            "x-unit": "%",
            "x-help": "Terminal SOC target. Defaults to the initial SOC so the plan does not consume energy that was already in the battery.",
        },
    )
    max_soc_end_pct: float = Field(
        default=100,
        ge=0,
        le=100,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery",
            "x-unit": "%",
        },
    )
    min_soc_pct: float = Field(
        default=20,
        ge=0,
        le=100,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Battery", "x-unit": "%"},
    )
    max_soc_pct: float = Field(
        default=100,
        ge=0,
        le=100,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Battery", "x-unit": "%"},
    )
    soc_entity: EntityId | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery",
            "x-ui-widget-filter": "sensor",
            "x-unit": "%",
        },
    )
    setpoint_entity: EntityId | None = Field(
        default=None,
        description="Entity that accepts the battery power setpoint in W (positive = charge).",
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery",
            "x-ui-widget-filter": "number,input_number",
            "x-help": "Number or input_number entity that accepts the battery power setpoint in W. "
            "Positive values charge the battery; negative values discharge it.",
        },
    )
    mode_entity: EntityId | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery",
            "x-ui-widget-filter": "select,input_select",
        },
    )
    mode_charge: str | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery control",
            "x-help": "Value for mode_entity when charging. For the official Anker integration "
            "this is 'charge' on the Grid Flow select.",
        },
    )
    mode_discharge: str | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery control",
        },
    )
    mode_idle: str | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery control",
        },
    )
    control_switch_entity: EntityId | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery control",
            "x-ui-widget-filter": "switch,input_boolean",
            "x-help": "Optional master switch that enables third-party/VPP control. DAEO turns it "
            "on when armed and off on disarm/fallback (for example the Anker X1 Modbus Control "
            "switch).",
        },
    )
    control_mode_entity: EntityId | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery control",
            "x-ui-widget-filter": "select,input_select",
            "x-help": "Optional operating-mode select. For the official Anker integration this is "
            "the Operating Mode select; DAEO sets it to third_party_control while armed and "
            "back to self_consumption on disarm.",
        },
    )
    control_mode_value: str | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery control",
            "x-help": "Operating mode used while control is armed, e.g. third_party_control.",
        },
    )
    control_mode_fallback: str | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery control",
            "x-help": "Operating mode restored on disarm/fallback, e.g. self_consumption.",
        },
    )
    setpoint_is_unsigned: bool = Field(
        default=False,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery control",
            "x-help": "Set when the setpoint entity expects a positive magnitude and the "
            "charge/discharge direction is a separate mode entity (official Anker "
            "integration: Power Control + Grid Flow).",
        },
    )
    invert_setpoint: bool = Field(
        default=False,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery control",
            "x-help": "Invert the signed setpoint for vendors that use + discharge / - charge.",
        },
    )
    setpoint_feedback_entity: EntityId | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Battery control",
            "x-ui-widget-filter": "sensor,number,input_number",
            "x-help": "Optional entity that reports the written setpoint for verification when "
            "the setpoint entity itself reports actual power.",
        },
    )

    @model_validator(mode="after")
    def check_soc(self) -> Self:
        if self.min_soc_pct >= self.max_soc_pct:
            raise ValueError("min_soc_pct must be below max_soc_pct")
        if self.min_soc_end_pct is not None and self.min_soc_end_pct > self.max_soc_end_pct:
            raise ValueError("min_soc_end_pct must not exceed max_soc_end_pct")
        if self.minimum_power_kw > self.max_charge_kw or self.minimum_power_kw > self.max_discharge_kw:
            raise ValueError("minimum_power_kw must not exceed the charge/discharge power limits")
        if self.setpoint_is_unsigned:
            if self.mode_entity is None:
                raise ValueError("setpoint_is_unsigned requires a mode_entity direction select")
            if not self.mode_charge or not self.mode_discharge:
                raise ValueError(
                    "setpoint_is_unsigned requires mode_charge and mode_discharge values"
                )
        return self


class BoilerConfig(DaeoModel):
    """Hot water boiler."""

    enabled: bool = Field(
        default=False,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Boiler"},
    )
    volume_l: float = Field(
        default=180,
        gt=0,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Boiler", "x-unit": "L"},
    )
    power_kw: float = Field(
        default=1.5,
        gt=0,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Boiler", "x-unit": "kW"},
    )
    cop: float = Field(
        default=1.0,
        gt=0,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Boiler"},
    )
    target_temp_c: float = Field(
        default=60,
        ge=0,
        le=100,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Boiler", "x-unit": "C"},
    )
    hysteresis_c: float = Field(
        default=5,
        ge=0,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Boiler", "x-unit": "C"},
    )
    temp_entity: EntityId | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Boiler",
            "x-ui-widget-filter": "sensor",
            "x-unit": "C",
        },
    )
    setpoint_entity: EntityId | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Boiler",
            "x-ui-widget-filter": "number,input_number",
        },
    )
    trigger_entity: EntityId | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Boiler",
            "x-ui-widget-filter": "button,switch,input_boolean",
        },
    )


class HeatPumpStage(DaeoModel):
    """One heat pump power stage."""

    max_power_kw: float = Field(gt=0)
    cop: float = Field(gt=0)


class HeatPumpConfig(DaeoModel):
    """Heat pump / heating system."""

    enabled: bool = Field(
        default=False,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Heat pump"},
    )
    stages: list[HeatPumpStage] = Field(default_factory=list)
    heating_curve_entity: EntityId | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Heat pump",
            "x-ui-widget-filter": "number,input_number",
        },
    )
    adjustment_factor: float = Field(default=0.04, ge=0)
    degree_days_factor: float = Field(default=3.6, ge=0)


class EVConfig(DaeoModel):
    """Electric vehicle charging request."""

    name: str = Field(default="EV", min_length=1, max_length=80)
    enabled: bool = Field(default=True)
    capacity_kwh: float = Field(
        gt=0,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "EV", "x-unit": "kWh"},
    )
    max_charge_kw: float = Field(
        gt=0,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "EV", "x-unit": "kW"},
    )
    phases: Literal[1, 3] = Field(
        default=3,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "EV"},
    )
    connected_entity: EntityId | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "EV",
            "x-ui-widget-filter": "binary_sensor,switch,input_boolean",
        },
    )
    soc_entity: EntityId | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "EV",
            "x-ui-widget-filter": "sensor",
            "x-unit": "%",
        },
    )
    switch_entity: EntityId | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "EV",
            "x-ui-widget-filter": "switch",
        },
    )
    target_soc_pct: float = Field(
        default=80,
        ge=0,
        le=100,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "EV", "x-unit": "%"},
    )
    ready_by: time = Field(
        default=time(7, 0),
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "EV"},
    )


class MachineConfig(DaeoModel):
    """Appliance that must run inside a window."""

    name: str = Field(default="Machine", min_length=1, max_length=80)
    enabled: bool = Field(default=True)
    power_kw: float = Field(
        gt=0,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Machines", "x-unit": "kW"},
    )
    duration_minutes: int = Field(
        gt=0,
        le=24 * 60,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Machines", "x-unit": "min"},
    )
    entity: EntityId | None = Field(
        default=None,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Machines",
            "x-ui-widget-filter": "switch,input_boolean,button",
        },
    )
    earliest_start: time = Field(default=time(0, 0))
    deadline: time = Field(default=time(23, 59))


class GridConfig(DaeoModel):
    """Grid connection limits."""

    max_import_kw: float = Field(
        default=17,
        gt=0,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Grid", "x-unit": "kW"},
    )
    max_export_kw: float = Field(
        default=17,
        gt=0,
        json_schema_extra={"x-ui-group": "Devices", "x-ui-section": "Grid", "x-unit": "kW"},
    )
    power_sensor_entity: EntityId | None = Field(
        default=None,
        description="Net grid power sensor in W. Positive means import, negative means export.",
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Realtime grid control",
            "x-ui-widget-filter": "sensor",
            "x-unit": "W",
            "x-help": "Optional P1/net-meter power sensor. When set, DAEO corrects "
            "the battery setpoint against the live meter in plan intervals that "
            "target zero grid import/export.",
        },
    )
    power_sensor_invert: bool = Field(
        default=False,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Realtime grid control",
            "x-help": "Enable when the power sensor reports export as positive and "
            "import as negative.",
        },
    )
    zero_grid_deadband_w: float = Field(
        default=30.0,
        ge=0,
        le=500,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Realtime grid control",
            "x-unit": "W",
            "x-help": "Ignore meter errors inside this band to avoid setpoint hunting.",
        },
    )
    zero_grid_max_step_w: float = Field(
        default=1000.0,
        ge=0,
        le=5000,
        json_schema_extra={
            "x-ui-group": "Devices",
            "x-ui-section": "Realtime grid control",
            "x-unit": "W",
            "x-help": "Maximum battery setpoint change per control tick. Zero disables "
            "the ramp limit.",
        },
    )


class StrategyConfig(DaeoModel):
    """Optimization objective and constraints."""

    objective: Objective = Field(
        default=Objective.MINIMIZE_COST,
        json_schema_extra={"x-ui-group": "Optimization", "x-ui-section": "Strategy"},
    )
    grid_mode: GridMode = Field(
        default=GridMode.SELF_CONSUMPTION,
        description="Self-consumption keeps the meter at zero while the battery can balance; arbitrage allows planned grid charging and export.",
        json_schema_extra={
            "x-ui-group": "Optimization",
            "x-ui-section": "Strategy",
            "x-help": "Self-consumption prioritises zero P1, consumes PV before export or "
            "curtailment, and only imports when the battery cannot cover the load. "
            "Arbitrage allows profitable grid charging and export.",
        },
    )
    interval: Interval = Field(
        default=Interval.QUARTER_HOUR,
        json_schema_extra={"x-ui-group": "Optimization", "x-ui-section": "Strategy"},
    )
    allow_export: bool = Field(default=True)
    reserve_soc_pct: float = Field(default=20, ge=0, le=100)
    cycle_cost_eur_kwh: float = Field(
        default=0.02,
        ge=0,
        json_schema_extra={
            "x-ui-group": "Optimization",
            "x-ui-section": "Strategy",
            "x-unit": "EUR/kWh",
        },
    )
    max_gap_eur: float = Field(
        default=0.005,
        ge=0,
        le=1,
        json_schema_extra={"x-ui-group": "Optimization", "x-ui-section": "Solver"},
    )
    solver_threads: int = Field(default=0, ge=0, le=64)


class ScheduleEntry(DaeoModel):
    """One scheduled action."""

    at: str = Field(
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
        description="Local time in HH:MM.",
        json_schema_extra={"x-ui-group": "Optimization", "x-ui-section": "Scheduler"},
    )
    action: TaskAction = Field(
        json_schema_extra={"x-ui-group": "Optimization", "x-ui-section": "Scheduler"}
    )


class SchedulerConfig(DaeoModel):
    """Scheduled engine actions."""

    enabled: bool = Field(default=True)
    entries: list[ScheduleEntry] = Field(default_factory=list)

    @field_validator("entries")
    @classmethod
    def check_duplicate_times(cls, value: list[ScheduleEntry]) -> list[ScheduleEntry]:
        times = [entry.at for entry in value]
        if len(times) != len(set(times)):
            raise ValueError("scheduler entries must not share a time")
        return value


class StorageConfig(DaeoModel):
    """Local persistence."""

    data_dir: str = Field(default="/data")
    retention_days: int = Field(default=30, ge=1, le=3650)


class Config(DaeoModel):
    """Root configuration document."""

    schema_version: Literal[1] = 1
    home: HomeConfig = Field(default_factory=HomeConfig)
    prices: PricingConfig = Field(default_factory=PricingConfig)
    forecast: ForecastConfig = Field(default_factory=ForecastConfig)
    load: LoadConfig = Field(default_factory=LoadConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    grid: GridConfig = Field(default_factory=GridConfig)
    solar: list[SolarConfig] = Field(default_factory=list)
    batteries: list[BatteryConfig] = Field(default_factory=list)
    electric_vehicles: list[EVConfig] = Field(default_factory=list)
    machines: list[MachineConfig] = Field(default_factory=list)
    boiler: BoilerConfig | None = None
    heat_pump: HeatPumpConfig | None = None
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)

    @model_validator(mode="after")
    def check_names(self) -> Self:
        for label, items in (
            ("solar", self.solar),
            ("batteries", self.batteries),
            ("electric_vehicles", self.electric_vehicles),
            ("machines", self.machines),
        ):
            names = [item.name for item in items]
            if len(names) != len(set(names)):
                raise ValueError(f"{label} names must be unique")
        return self

    @classmethod
    def default(cls) -> Config:
        """Return a usable NL preset with no devices."""
        return cls(
            scheduler=SchedulerConfig(
                entries=[
                    ScheduleEntry(at="13:55", action=TaskAction.FETCH_PRICES),
                    ScheduleEntry(at="14:05", action=TaskAction.FETCH_WEATHER),
                    ScheduleEntry(at="14:15", action=TaskAction.OPTIMIZE),
                ]
            )
        )

    @classmethod
    def demo(cls) -> Config:
        """Return a sample configuration for the standalone demo."""
        config = cls.default()
        config.solar = [SolarConfig(name="Roof", peak_power_wp=5000)]
        config.batteries = [
            BatteryConfig(
                name="Home battery",
                capacity_kwh=10,
                max_charge_kw=5,
                max_discharge_kw=5,
                min_soc_pct=20,
                max_soc_pct=100,
            )
        ]
        config.electric_vehicles = [
            EVConfig(
                name="Car",
                capacity_kwh=60,
                max_charge_kw=11,
                target_soc_pct=80,
                ready_by=time(7, 0),
            )
        ]
        config.boiler = BoilerConfig(
            enabled=True,
            volume_l=180,
            power_kw=1.5,
            cop=1.0,
            target_temp_c=60,
        )
        return config
