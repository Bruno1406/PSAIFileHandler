from __future__ import annotations

import re
from collections.abc import Mapping

# Fast-path dictionary for standard single-letter and CFD mathematical shorthands.
# Multi-word descriptive patterns (e.g. "Velocity_field", "Total_traction") are handled by DEFAULT_REGEX_RULES below.
DEFAULT_FIELD_ALIASES: dict[str, str] = {
    # Pressure
    "p": "pressure",
    "pressure": "pressure",
    # Velocity components (Navier-Stokes u,v,w and coordinate axes x,y,z)
    "u": "vx",
    "v": "vy",
    "w": "vz",
    "vx": "vx",
    "vy": "vy",
    "vz": "vz",
    "ux": "vx",
    "uy": "vy",
    "uz": "vz",
    "x": "vx",
    "y": "vy",
    "z": "vz",
    # Velocity magnitude
    "|u|": "velocity_mag",
    "speed": "velocity_mag",
    # Traction canonical identifiers
    "t_tracx": "t_tracx",
    "t_tracy": "t_tracy",
    "t_tracz": "t_tracz",
    # Rotation angle
    "alphat": "alphat",
}

DEFAULT_PARAMETER_ALIASES: dict[str, str] = {
    # Flow rate and volumetric flux
    "q_in": "volumetric_flow",
    "flow_rate": "volumetric_flow",
    "volumetric_flow": "volumetric_flow",
    "q": "volumetric_flow",
    # Rotational speed and RPM
    "rot_rpm": "rotational_speed",
    "rpm": "rotational_speed",
    "rotational_speed": "rotational_speed",
    "omega": "angular_velocity",
}

# 1. Velocity components: matches "Velocity_field,_x_component", "velocity x", "u_comp1", etc.
# 2. Velocity magnitude: matches "Velocity_field", "Velocity magnitude", "|u|", "speed"
# 3. Total traction: matches "Total_traction,_exterior_boundaries,_x_component", etc.
# 4. Pressure: matches "Pressure", "p", "static_pressure"
# 5. Rotation angle: matches "Rotation_angle", "alphat"
DEFAULT_REGEX_RULES: list[tuple[re.Pattern[str], str]] = [
    # 1. Velocity components: matches "Velocity_field,_x_component", "velocity x", "u_comp1", etc.
    (
        re.compile(
            r"^(?:velocity(?:_field)?|u)[_]*(?:component_)?(?P<comp>[xyz]|comp[123])(?:_component)?$"
        ),
        "v{comp}",
    ),
    # 2. Velocity magnitude: matches "Velocity_field", "Velocity magnitude", "|u|", "speed"
    (
        re.compile(r"^(?:velocity(?:_field)?(?:_magnitude)?|speed|\|u\|)$"),
        "velocity_mag",
    ),
    # 3. Total traction components: matches "Total_traction,_exterior_boundaries,_x_component", "traction_x", etc.
    (
        re.compile(
            r"^(?:total_)?traction.*?(?:component_)?(?P<comp>[xyz]|comp[123])(?:_component)?$"
        ),
        "t_trac{comp}",
    ),
    # 4. Total traction general: matches "Total_traction", "traction"
    (
        re.compile(r"^(?:total_)?traction(?:_exterior_boundaries)?$"),
        "traction",
    ),
    # 5. Pressure: matches "Pressure", "p", "static_pressure"
    (
        re.compile(r"^(?:static_)?pressure$"),
        "pressure",
    ),
    # 6. Rotation angle: matches "Rotation_angle", "alphat"
    (
        re.compile(r"^(?:rotation_angle|alphat)$"),
        "alphat",
    ),
]


def normalize_alias_key(key: str) -> str:
    """Normalize expression string for alias lookup by stripping whitespace/underscores/commas and lowercasing."""
    # Replace whitespace, commas, and repeated underscores with a single underscore and strip edges
    return re.sub(r"[\s_,]+", "_", key.strip().lower()).strip("_")


class FieldAliasResolver:
    """Manages canonical expression alias resolution with optional user overrides."""

    def __init__(
        self,
        custom_aliases: Mapping[str, str | list[str]] | None = None,
    ) -> None:
        self.aliases: dict[str, str] = {
            normalize_alias_key(k): v for k, v in DEFAULT_FIELD_ALIASES.items()
        }
        for k, v in DEFAULT_PARAMETER_ALIASES.items():
            self.aliases[normalize_alias_key(k)] = v

        self.custom_vector_aliases: dict[str, list[str]] = {}

        if custom_aliases:
            for k, v in custom_aliases.items():
                if isinstance(v, list):
                    self.custom_vector_aliases[k] = [str(x) for x in v]
                else:
                    norm_k = normalize_alias_key(k)
                    norm_v = normalize_alias_key(str(v))
                    self.aliases[norm_k] = str(v)
                    self.aliases[norm_v] = str(k)

    def resolve(self, expr_name: str) -> str:
        """Resolve expression name to its canonical identifier."""
        clean = expr_name.strip()
        norm_key = normalize_alias_key(clean)

        if norm_key in self.aliases:
            return self.aliases[norm_key]

        for rx, template in DEFAULT_REGEX_RULES:
            m = rx.match(norm_key)
            if m:
                groups = m.groupdict()
                comp = groups.get("comp")
                if comp:
                    c = comp.lower()
                    groups["comp"] = {"comp1": "x", "comp2": "y", "comp3": "z"}.get(c, c)
                resolved = template.format(**groups)
                self.aliases[norm_key] = resolved
                return resolved

        return clean

    def matches(self, pattern: str, expr_name: str) -> bool:
        """Check if an expression name matches a target schema pattern directly, via alias, or via regex."""
        if pattern == expr_name:
            return True

        norm_p = normalize_alias_key(pattern)
        norm_e = normalize_alias_key(expr_name)
        if norm_p == norm_e:
            return True

        resolved_expr = self.resolve(expr_name)
        resolved_pattern = self.resolve(pattern)
        if resolved_expr == resolved_pattern:
            return True

        if self.aliases.get(norm_p) == norm_e or self.aliases.get(norm_e) == norm_p:
            return True

        try:
            # Matches user pattern with glob wildcard or regex against expression or canonical name
            regex_str = pattern.replace(".", r"\.").replace("*", ".*")
            rx = re.compile(f"^{regex_str}$", re.IGNORECASE)
            if rx.match(expr_name) or rx.match(resolved_expr):
                return True
        except re.error:
            pass

        return False
