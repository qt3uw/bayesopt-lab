"""General ARTIQ scaffolding for configurable Bayesian optimization experiments."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from main import Parameter, run as run_bo

try:
    from artiq.experiment import EnvExperiment, NumberValue, delay, kernel, ms, us

    ARTIQ_AVAILABLE = True
    ARTIQ_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - allows import on non-ARTIQ hosts
    ARTIQ_AVAILABLE = False
    ARTIQ_IMPORT_ERROR = exc

    class EnvExperiment:  # type: ignore[override]
        pass

    class NumberValue:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

    def kernel(func):  # type: ignore[override]
        return func

    def delay(_):  # type: ignore[override]
        return None

    ms = 1e-3
    us = 1e-6


@dataclass(frozen=True)
class DeviceSpec:
    """ARTIQ device to bind with setattr_device()."""

    name: str


@dataclass(frozen=True)
class ChannelSpec:
    """Integer-valued channel argument (e.g. dac_channel, adc_channel)."""

    name: str
    default: int = 0
    minimum: int = 0
    maximum: int = 31


@dataclass(frozen=True)
class NumericArgSpec:
    """Numeric host argument exposed with NumberValue."""

    name: str
    default: float
    minimum: float | None = None
    maximum: float | None = None
    unit: str | None = None
    integer: bool = False
    step: float | None = None


@dataclass(frozen=True)
class BOExperimentConfig:
    """Declarative config used to build a BO experiment."""

    devices: list[DeviceSpec] = field(default_factory=list)
    channels: list[ChannelSpec] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    data_arguments: list[NumericArgSpec] = field(default_factory=list)


class ConfigurableBOExperiment(EnvExperiment):
    """General BO runner.

    You can either:
    - set CONFIG directly in the subclass, or
    - set DESCRIPTION_PATH (+ optional DEVICE_DB_PATH) and let config auto-load.
    """

    CONFIG = BOExperimentConfig()
    DESCRIPTION_PATH: str | None = None
    DEVICE_DB_PATH = "device_db.py"

    def _ensure_artiq(self) -> None:
        if not ARTIQ_AVAILABLE:
            raise RuntimeError(
                "ARTIQ is not available in this Python environment. "
                f"Import error: {ARTIQ_IMPORT_ERROR}"
            )

    def _resolve_path(self, path_hint: str) -> Path:
        path = Path(path_hint)
        if path.is_absolute():
            return path
        cwd_path = Path.cwd() / path
        if cwd_path.exists():
            return cwd_path
        module_dir_path = Path(__file__).resolve().parent / path
        return module_dir_path

    def _load_device_db(self, device_db_path: Path) -> dict[str, Any]:
        namespace: dict[str, Any] = {}
        code = device_db_path.read_text(encoding="utf-8")
        exec(compile(code, str(device_db_path), "exec"), namespace)  # noqa: S102
        device_db = namespace.get("device_db")
        if not isinstance(device_db, dict):
            raise RuntimeError(f"{device_db_path} must define a dict named 'device_db'.")
        return device_db

    def _resolve_device_roles(
        self, device_db: dict[str, Any], role_descriptions: list[dict[str, Any]]
    ) -> dict[str, str]:
        role_map: dict[str, str] = {}
        used_devices: set[str] = set()
        for role_spec in role_descriptions:
            role = str(role_spec["role"])
            explicit_device = role_spec.get("device")
            required = bool(role_spec.get("required", True))
            selected_device: str | None = None

            if isinstance(explicit_device, str):
                if explicit_device in device_db:
                    selected_device = explicit_device
                elif required:
                    raise RuntimeError(
                        f"Description requires device '{explicit_device}' for role '{role}', "
                        "but it was not found in device_db."
                    )
            else:
                module = role_spec.get("module")
                cls = role_spec.get("class")
                for name, entry in device_db.items():
                    if name in used_devices or not isinstance(entry, dict):
                        continue
                    if module is not None and entry.get("module") != module:
                        continue
                    if cls is not None and entry.get("class") != cls:
                        continue
                    selected_device = name
                    break
                if selected_device is None and required:
                    raise RuntimeError(
                        f"Unable to resolve required role '{role}' from device_db "
                        f"with filters module={module!r}, class={cls!r}."
                    )

            if selected_device is not None:
                role_map[role] = selected_device
                used_devices.add(selected_device)

        return role_map

    def _load_config_from_description(
        self, description_path: Path, device_db_path: Path
    ) -> tuple[BOExperimentConfig, dict[str, str], dict[str, Any]]:
        description = json.loads(description_path.read_text(encoding="utf-8"))
        if not isinstance(description, dict):
            raise RuntimeError("Description file must be a JSON object.")

        device_db = self._load_device_db(device_db_path)
        role_descriptions = description.get("device_roles", [])
        if not isinstance(role_descriptions, list):
            raise RuntimeError("'device_roles' must be a list.")
        role_map = self._resolve_device_roles(device_db, role_descriptions)

        device_names = [str(name) for name in description.get("devices", [])]
        for role_device in role_map.values():
            if role_device not in device_names:
                device_names.append(role_device)
        devices = [DeviceSpec(name) for name in device_names]

        channels: list[ChannelSpec] = []
        for raw in description.get("channels", []):
            channels.append(
                ChannelSpec(
                    name=str(raw["name"]),
                    default=int(raw.get("default", 0)),
                    minimum=int(raw.get("minimum", 0)),
                    maximum=int(raw.get("maximum", 31)),
                )
            )

        parameters: list[Parameter] = []
        for raw in description.get("parameters", []):
            bounds = raw["bounds"]
            if not isinstance(bounds, list) or len(bounds) != 2:
                raise RuntimeError(f"Parameter '{raw.get('name')}' must define 2-item bounds list.")
            parameters.append(Parameter(str(raw["name"]), (float(bounds[0]), float(bounds[1]))))

        data_arguments: list[NumericArgSpec] = []
        for raw in description.get("data_arguments", []):
            data_arguments.append(
                NumericArgSpec(
                    name=str(raw["name"]),
                    default=float(raw["default"]),
                    minimum=float(raw["minimum"]) if "minimum" in raw else None,
                    maximum=float(raw["maximum"]) if "maximum" in raw else None,
                    unit=str(raw["unit"]) if "unit" in raw else None,
                    integer=bool(raw.get("integer", False)),
                    step=float(raw["step"]) if "step" in raw else None,
                )
            )

        config = BOExperimentConfig(
            devices=devices,
            channels=channels,
            parameters=parameters,
            data_arguments=data_arguments,
        )
        objective_spec = description.get("objective", {})
        if not isinstance(objective_spec, dict):
            raise RuntimeError("'objective' must be a JSON object if provided.")
        return config, role_map, objective_spec

    def _active_config(self) -> BOExperimentConfig:
        config = getattr(self, "_resolved_config", None)
        if config is not None:
            return config

        self.device_roles: dict[str, str] = {}
        self.objective_spec: dict[str, Any] = {}
        config = self.CONFIG
        if self.DESCRIPTION_PATH is not None:
            description_path = self._resolve_path(self.DESCRIPTION_PATH)
            device_db_path = self._resolve_path(self.DEVICE_DB_PATH)
            config, self.device_roles, self.objective_spec = self._load_config_from_description(
                description_path, device_db_path
            )
        self._resolved_config = config
        return config

    def _number_value_for(self, spec: NumericArgSpec) -> NumberValue:
        kwargs: dict[str, Any] = {"default": spec.default}
        if spec.minimum is not None:
            kwargs["min"] = spec.minimum
        if spec.maximum is not None:
            kwargs["max"] = spec.maximum
        if spec.unit is not None:
            kwargs["unit"] = spec.unit
        if spec.step is not None:
            kwargs["step"] = spec.step
        if spec.integer:
            kwargs["ndecimals"] = 0
        return NumberValue(**kwargs)

    def build(self):
        if not ARTIQ_AVAILABLE:
            return
        config = self._active_config()

        for device in config.devices:
            self.setattr_device(device.name)

        for channel in config.channels:
            self.setattr_argument(
                channel.name,
                NumberValue(
                    default=channel.default,
                    min=channel.minimum,
                    max=channel.maximum,
                    step=1,
                    ndecimals=0,
                ),
            )

        for argument in config.data_arguments:
            self.setattr_argument(argument.name, self._number_value_for(argument))

        self.setattr_argument("init_trials", NumberValue(default=5, step=1, ndecimals=0, min=1))
        self.setattr_argument("max_trials", NumberValue(default=30, step=1, ndecimals=0, min=1))
        self.setattr_argument("seed", NumberValue(default=123, step=1, ndecimals=0, min=0))

    def prepare(self):
        if not ARTIQ_AVAILABLE:
            return
        config = self._active_config()

        for channel in config.channels:
            setattr(self, channel.name, int(getattr(self, channel.name)))

        for argument in config.data_arguments:
            current = getattr(self, argument.name)
            casted = int(current) if argument.integer else float(current)
            setattr(self, argument.name, casted)

        self.init_trials = int(self.init_trials)
        self.max_trials = int(self.max_trials)
        self.seed = int(self.seed)

    def parameter_space(self) -> list[Parameter]:
        config = self._active_config()
        if not config.parameters:
            raise RuntimeError("Experiment config must include at least one Parameter.")
        return config.parameters

    def setup_bo_run(self) -> None:
        """Optional setup hook called once before the BO loop."""

    def evaluate(self, params: dict[str, float]) -> float:
        raise NotImplementedError("Subclasses must implement evaluate(params).")

    def run(self):
        self._ensure_artiq()
        self.setup_bo_run()

        best = run_bo(
            experiment=self,
            init_trials=self.init_trials,
            max_trials=self.max_trials,
            seed=self.seed,
        )
        print(f"Hardware BO complete: {best}")

