"""Beam statics, diagrams, deflection, and section checks for Beam Designer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np


STEEL_SECTIONS = [
    {"name": "W8x10", "ix": 30.8, "sx": 7.81, "weight": 10.0},
    {"name": "W10x12", "ix": 53.8, "sx": 10.9, "weight": 12.0},
    {"name": "W12x26", "ix": 204.0, "sx": 33.4, "weight": 26.0},
    {"name": "W14x22", "ix": 199.0, "sx": 29.0, "weight": 22.0},
    {"name": "W16x26", "ix": 301.0, "sx": 38.4, "weight": 26.0},
    {"name": "W18x35", "ix": 510.0, "sx": 57.6, "weight": 35.0},
    {"name": "W21x44", "ix": 843.0, "sx": 81.6, "weight": 44.0},
    {"name": "W24x55", "ix": 1350.0, "sx": 114.0, "weight": 55.0},
]

WOOD_SECTIONS = [
    {"name": "2x8", "ix": 47.63, "sx": 13.14, "weight": None},
    {"name": "2x10", "ix": 98.93, "sx": 21.39, "weight": None},
    {"name": "2x12", "ix": 177.98, "sx": 31.64, "weight": None},
]

MATERIALS = {
    "Steel": {"e": 29000.0, "fb": 30.0, "sections": STEEL_SECTIONS},
    "Douglas Fir-Larch No. 2": {
        "e": 1600.0,
        "fb": 0.900,
        "sections": WOOD_SECTIONS,
    },
}


@dataclass
class Load:
    kind: str
    magnitude: float
    position: float = 0.0
    start: float = 0.0
    end: float = 0.0


@dataclass
class Analysis:
    x: np.ndarray
    shear: np.ndarray
    moment: np.ndarray
    deflection: np.ndarray
    reaction_left: float
    reaction_right: float
    fixed_end_moment: float
    max_shear: int
    max_moment: int
    max_deflection: int
    bending_stress: float
    allowable_bending: float
    deflection_limit: float
    bending_ratio: float
    deflection_ratio: float
    recommendation: str | None
    recommendation_details: dict | None


def normalized_loads(loads: Iterable[Load], span: float) -> list[Load]:
    """Return copied, nonnegative loads clipped to the current span."""
    result = []
    for load in loads:
        magnitude = max(0.0, float(load.magnitude))
        if load.kind == "point":
            result.append(
                Load("point", magnitude, position=min(span, max(0.0, float(load.position))))
            )
        else:
            a = min(span, max(0.0, float(load.start)))
            b = min(span, max(0.0, float(load.end)))
            a, b = min(a, b), max(a, b)
            result.append(Load("uniform", magnitude, start=a, end=b))
    return result


def _load_resultants(loads: list[Load], span: float) -> tuple[float, float]:
    total = 0.0
    moment = 0.0
    for load in loads:
        if load.kind == "point":
            total += load.magnitude
            moment += load.magnitude * load.position
        else:
            a, b = load.start, min(span, load.end)
            resultant = load.magnitude * max(0.0, b - a)
            total += resultant
            moment += resultant * (a + b) / 2.0
    return total, moment


def analyze(
    span: float,
    support: str,
    loads: Iterable[Load],
    material: str,
    section_name: str,
    deflection_divisor: int,
) -> Analysis:
    """Analyze a beam. Distances are ft, loads kip or kip/ft, and y is inches."""
    span = float(span)
    material_data = MATERIALS[material]
    section = next(
        item for item in material_data["sections"] if item["name"] == section_name
    )
    loads = normalized_loads(loads, span)
    total, applied_moment = _load_resultants(loads, span)

    if support == "simply_supported":
        reaction_right = applied_moment / span
        reaction_left = total - reaction_right
        fixed_end_moment = 0.0
    else:
        reaction_left = total
        reaction_right = 0.0
        fixed_end_moment = applied_moment

    # Keep the integration step below 0.05 ft for accurate deflection, then
    # insert exact load boundaries and both sides of each point-load jump.
    step = min(0.05, span / 400.0)
    xs = list(np.arange(0.0, span, step)) + [span]
    for load in loads:
        if load.kind == "point":
            xs.append(load.position)
            if load.position > 0:
                xs.append(max(0.0, load.position - min(1e-6, step * 1e-4)))
        else:
            xs.extend((load.start, load.end))
    x = np.unique(np.round(np.clip(xs, 0.0, span), 9))

    shear = np.empty_like(x)
    moment = np.empty_like(x)
    for i, at in enumerate(x):
        if support == "simply_supported":
            v = reaction_left
            m = reaction_left * at
            for load in loads:
                if load.kind == "point" and at >= load.position:
                    v -= load.magnitude
                    m -= load.magnitude * (at - load.position)
                elif load.kind == "uniform":
                    a, b = load.start, load.end
                    loaded_end = min(at, b)
                    length = max(0.0, loaded_end - a)
                    v -= load.magnitude * length
                    m -= load.magnitude * length * (at - (a + loaded_end) / 2.0)
        else:
            v = 0.0
            m = 0.0
            for load in loads:
                if load.kind == "point" and load.position >= at:
                    v -= load.magnitude
                    m -= load.magnitude * (load.position - at)
                elif load.kind == "uniform":
                    a, b = max(at, load.start), min(span, load.end)
                    length = max(0.0, b - a)
                    v -= load.magnitude * length
                    m -= load.magnitude * length * ((a + b) / 2.0 - at)
        shear[i], moment[i] = v, m

    # Integrate curvature with x in inches and M in kip-inches. For a simple
    # span, add the linear rigid-body term needed to make both end deflections 0.
    ei = material_data["e"] * section["ix"]
    x_inches = x * 12.0
    curvature = moment * 12.0 / ei
    slope = np.zeros_like(x)
    deflection = np.zeros_like(x)
    for i in range(1, len(x)):
        dx = x_inches[i] - x_inches[i - 1]
        slope[i] = slope[i - 1] + (curvature[i - 1] + curvature[i]) * dx / 2.0
        deflection[i] = deflection[i - 1] + (slope[i - 1] + slope[i]) * dx / 2.0
    if support == "simply_supported":
        deflection -= deflection[-1] * x / span
    deflection = -deflection

    max_shear = int(np.argmax(np.abs(shear)))
    max_moment = int(np.argmax(np.abs(moment)))
    max_deflection = int(np.argmax(np.abs(deflection)))
    allowable_bending = material_data["fb"]
    bending_stress = abs(moment[max_moment]) * 12.0 / section["sx"]
    deflection_limit = span * 12.0 / deflection_divisor
    bending_ratio = bending_stress / allowable_bending
    deflection_ratio = abs(deflection[max_deflection]) / deflection_limit

    passing = []
    for candidate in material_data["sections"]:
        candidate_bending = abs(moment[max_moment]) * 12.0 / candidate["sx"]
        candidate_deflection = abs(
            deflection[max_deflection]
            * section["ix"]
            / candidate["ix"]
        )
        if candidate_bending <= allowable_bending and candidate_deflection <= deflection_limit:
            passing.append(candidate)
    if material == "Steel":
        passing.sort(key=lambda item: (item["weight"], -item["ix"]))
    recommendation_details = passing[0] if passing else None

    return Analysis(
        x=x,
        shear=shear,
        moment=moment,
        deflection=deflection,
        reaction_left=reaction_left,
        reaction_right=reaction_right,
        fixed_end_moment=fixed_end_moment,
        max_shear=max_shear,
        max_moment=max_moment,
        max_deflection=max_deflection,
        bending_stress=bending_stress,
        allowable_bending=allowable_bending,
        deflection_limit=deflection_limit,
        bending_ratio=bending_ratio,
        deflection_ratio=deflection_ratio,
        recommendation=(recommendation_details["name"] if recommendation_details else None),
        recommendation_details=recommendation_details,
    )
