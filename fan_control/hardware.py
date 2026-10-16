"""Read-only hardware discovery and validated write requests. No GTK dependency."""

from dataclasses import dataclass
from pathlib import Path


PROFILES = {
    "quiet": ("Quiet", "Reduce fan noise for lighter tasks", "audio-volume-low-symbolic"),
    "cool": ("Cool", "Prioritize a cooler chassis", "weather-snow-symbolic"),
    "balanced": ("Balanced", "Let the firmware balance cooling and performance", "power-profile-balanced-symbolic"),
    "performance": ("Performance", "Favor performance with more aggressive cooling", "power-profile-performance-symbolic"),
}


def read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except (OSError, UnicodeError):
        return None


def read_number(path: Path) -> int | None:
    value = read_text(path)
    try:
        result = int(value) if value is not None else -1
        return result if result >= 0 else None
    except ValueError:
        return None


@dataclass(frozen=True)
class Snapshot:
    profile: str | None
    choices: tuple[str, ...]
    controller: Path | None
    mode: int | None
    rpm: tuple[int | None, int | None]
    labels: tuple[str, str]


@dataclass(frozen=True)
class WriteRequest:
    path: Path
    value: str


class Hardware:
    def __init__(self, root: Path = Path("/sys")):
        self.root = root
        self.profile_path = root / "firmware/acpi/platform_profile"

    def discover_controller(self) -> Path | None:
        for candidate in sorted((self.root / "class/hwmon").glob("hwmon*")):
            try:
                target = candidate.resolve(strict=True)
                hp_platform = (self.root / "devices/platform/hp-wmi").resolve()
                if target.is_relative_to(hp_platform) and read_text(target / "name") == "hp":
                    return target
            except (OSError, RuntimeError):
                continue
        return None

    def read(self) -> Snapshot:
        controller = self.discover_controller()
        return Snapshot(
            profile=read_text(self.profile_path),
            choices=tuple((read_text(self.profile_path.with_name("platform_profile_choices")) or "").split()),
            controller=controller,
            mode=read_number(controller / "pwm1_enable") if controller else None,
            rpm=tuple(read_number(controller / f"fan{i}_input") if controller else None for i in (1, 2)),
            labels=tuple((read_text(controller / f"fan{i}_label") if controller else None) or label
                         for i, label in ((1, "CPU fan"), (2, "GPU fan"))),
        )

    def profile_request(self, value: str) -> WriteRequest:
        snapshot = self.read()
        if value not in PROFILES or value not in snapshot.choices:
            raise ValueError("This thermal profile is not supported by your firmware.")
        if snapshot.profile is None:
            raise ValueError("The thermal profile is unavailable. Check that your firmware exposes platform profiles.")
        return WriteRequest(self.profile_path, value)

    def fan_request(self, maximum: bool) -> WriteRequest:
        snapshot = self.read()
        if snapshot.controller is None or snapshot.mode is None:
            raise ValueError("The HP fan controller is unavailable. Check that hp-wmi is loaded.")
        return WriteRequest(snapshot.controller / "pwm1_enable", "0" if maximum else "2")

    @staticmethod
    def verify(request: WriteRequest) -> None:
        if read_text(request.path) != request.value:
            raise ValueError("The setting did not stay applied. The firmware or another power management app may have changed it.")


class DemoHardware:
    """In-memory preview. Never reads or writes hardware."""

    def __init__(self):
        self.profile = "balanced"
        self.maximum = False

    def read(self) -> Snapshot:
        return Snapshot(self.profile, tuple(PROFILES), Path("/demo/hp-wmi"),
                        0 if self.maximum else 2,
                        (5200, 4900) if self.maximum else (1850, 1700),
                        ("CPU fan", "GPU fan"))

    def profile_request(self, value: str) -> WriteRequest:
        if value not in PROFILES:
            raise ValueError("Unknown thermal profile.")
        return WriteRequest(Path("/demo/platform_profile"), value)

    def fan_request(self, maximum: bool) -> WriteRequest:
        return WriteRequest(Path("/demo/pwm1_enable"), "0" if maximum else "2")

    def apply(self, request: WriteRequest) -> None:
        if request.path.name == "platform_profile":
            self.profile = request.value
        else:
            self.maximum = request.value == "0"

    def verify(self, request: WriteRequest) -> None:
        actual = self.profile if request.path.name == "platform_profile" else ("0" if self.maximum else "2")
        if actual != request.value:
            raise ValueError("Preview setting did not apply.")
