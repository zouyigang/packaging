"""Incremental industrial load state shared by construction and final validation."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models.schemas import Container

EPS = 1e-6
G = 9.81
Box = tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class IndustrialLoadMetrics:
    total_mass: float = 0.0
    cog_x_ratio: float = 0.5
    cog_y_ratio: float = 0.5
    cog_z_ratio: float = 0.0
    load_distribution_margin: float = 1.0
    max_floor_load_kg_m2: float = 0.0
    required_securement_kn: float = 0.0
    tip_stability_margin: float = 1.0

    def as_dict(self) -> dict[str, float]:
        return {
            "total_mass": self.total_mass,
            "cog_x_ratio": self.cog_x_ratio,
            "cog_y_ratio": self.cog_y_ratio,
            "cog_z_ratio": self.cog_z_ratio,
            "load_distribution_margin": self.load_distribution_margin,
            "max_floor_load_kg_m2": self.max_floor_load_kg_m2,
            "required_securement_kn": self.required_securement_kn,
            "tip_stability_margin": self.tip_stability_margin,
        }


@dataclass(frozen=True)
class StackClusterMetrics:
    cluster_count: int = 0
    risky_cluster_count: int = 0
    min_tip_stability_margin: float = 1.0
    max_slenderness_ratio: float = 0.0
    required_longitudinal_restraint_kn: float = 0.0
    required_transverse_restraint_kn: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "stack_cluster_count": float(self.cluster_count),
            "risky_stack_cluster_count": float(self.risky_cluster_count),
            "stack_cluster_tip_margin": self.min_tip_stability_margin,
            "max_stack_cluster_slenderness": self.max_slenderness_ratio,
            "required_stack_longitudinal_restraint_kn": self.required_longitudinal_restraint_kn,
            "required_stack_transverse_restraint_kn": self.required_transverse_restraint_kn,
        }


@dataclass(frozen=True)
class _LoadRecord:
    box: Box
    mass: float
    ground_shares: dict[int, float]


@dataclass
class IndustrialLoadContext:
    """Maintain mass moments and transmitted floor loads as placements are added."""

    container: Container
    total_mass: float = 0.0
    moment_x: float = 0.0
    moment_y: float = 0.0
    moment_z: float = 0.0
    min_friction: float | None = None
    min_tip_margin: float = 1.0
    records: list[_LoadRecord] = field(default_factory=list)
    ground_loads: dict[int, float] = field(default_factory=dict)

    def preview(self, box: Box, mass: float, friction: float | None = None) -> IndustrialLoadMetrics:
        effective_mass = _effective_mass(box, mass)
        ground_shares = self._ground_shares(box, len(self.records))
        ground_loads = dict(self.ground_loads)
        for ground_index, fraction in ground_shares.items():
            ground_loads[ground_index] = ground_loads.get(ground_index, 0.0) + effective_mass * fraction
        return self._metrics_after(box, effective_mass, friction, ground_loads)

    def preview_batch(
        self,
        loads: list[tuple[Box, float, float | None]],
    ) -> IndustrialLoadMetrics:
        """Preview a composite placement transaction without mutating this context."""
        fork = IndustrialLoadContext(
            container=self.container,
            total_mass=self.total_mass,
            moment_x=self.moment_x,
            moment_y=self.moment_y,
            moment_z=self.moment_z,
            min_friction=self.min_friction,
            min_tip_margin=self.min_tip_margin,
            records=list(self.records),
            ground_loads=dict(self.ground_loads),
        )
        metrics = fork.metrics()
        for box, mass, friction in loads:
            metrics = fork.commit(box, mass, friction)
        return metrics

    def commit(self, box: Box, mass: float, friction: float | None = None) -> IndustrialLoadMetrics:
        effective_mass = _effective_mass(box, mass)
        index = len(self.records)
        ground_shares = self._ground_shares(box, index)
        self.records.append(_LoadRecord(box=box, mass=effective_mass, ground_shares=ground_shares))
        for ground_index, fraction in ground_shares.items():
            self.ground_loads[ground_index] = self.ground_loads.get(ground_index, 0.0) + effective_mass * fraction

        x, y, z, dx, dy, dz = box
        self.total_mass += effective_mass
        self.moment_x += effective_mass * (x + dx / 2.0)
        self.moment_y += effective_mass * (y + dy / 2.0)
        self.moment_z += effective_mass * (z + dz / 2.0)
        coefficient = friction if friction is not None else self.container.default_friction_coefficient
        if coefficient is not None:
            self.min_friction = coefficient if self.min_friction is None else min(self.min_friction, coefficient)
        self.min_tip_margin = min(self.min_tip_margin, _box_tip_margin(self.container, box))
        return self.metrics()

    def metrics(self) -> IndustrialLoadMetrics:
        if self.total_mass <= EPS:
            return IndustrialLoadMetrics()
        gx_ratio = self.moment_x / self.total_mass / self.container.inner_length
        gy_ratio = self.moment_y / self.total_mass / self.container.inner_width
        gz_ratio = self.moment_z / self.total_mass / self.container.inner_height
        allowed = interpolated_payload(self.container, gx_ratio)
        curve_margin = 1.0 if allowed is None else (
            (allowed - self.total_mass) / allowed if allowed > EPS else -self.total_mass
        )
        return IndustrialLoadMetrics(
            total_mass=self.total_mass,
            cog_x_ratio=gx_ratio,
            cog_y_ratio=gy_ratio,
            cog_z_ratio=gz_ratio,
            load_distribution_margin=curve_margin,
            max_floor_load_kg_m2=self._max_floor_pressure(self.ground_loads),
            required_securement_kn=_required_securement_kn(
                self.container, self.total_mass, self.min_friction
            ),
            tip_stability_margin=self.min_tip_margin,
        )

    def _metrics_after(
        self,
        box: Box,
        mass: float,
        friction: float | None,
        ground_loads: dict[int, float],
    ) -> IndustrialLoadMetrics:
        x, y, z, dx, dy, dz = box
        total = self.total_mass + mass
        gx_ratio = (self.moment_x + mass * (x + dx / 2.0)) / total / self.container.inner_length
        gy_ratio = (self.moment_y + mass * (y + dy / 2.0)) / total / self.container.inner_width
        gz_ratio = (self.moment_z + mass * (z + dz / 2.0)) / total / self.container.inner_height
        allowed = interpolated_payload(self.container, gx_ratio)
        curve_margin = 1.0 if allowed is None else ((allowed - total) / allowed if allowed > EPS else -total)
        coefficient = friction if friction is not None else self.container.default_friction_coefficient
        min_friction = coefficient if self.min_friction is None else (
            self.min_friction if coefficient is None else min(self.min_friction, coefficient)
        )
        return IndustrialLoadMetrics(
            total_mass=total,
            cog_x_ratio=gx_ratio,
            cog_y_ratio=gy_ratio,
            cog_z_ratio=gz_ratio,
            load_distribution_margin=curve_margin,
            max_floor_load_kg_m2=self._max_floor_pressure(ground_loads, pending=(box, len(self.records))),
            required_securement_kn=_required_securement_kn(self.container, total, min_friction),
            tip_stability_margin=min(self.min_tip_margin, _box_tip_margin(self.container, box)),
        )

    def _ground_shares(self, box: Box, pending_index: int) -> dict[int, float]:
        if box[2] <= EPS:
            return {pending_index: 1.0}
        supporters: list[tuple[_LoadRecord, float]] = []
        for record in self.records:
            area = _support_overlap(box, record.box)
            if area > EPS:
                supporters.append((record, area))
        total_area = sum(area for _record, area in supporters)
        if total_area <= EPS:
            return {}
        shares: dict[int, float] = {}
        for record, area in supporters:
            direct_fraction = area / total_area
            for ground_index, ground_fraction in record.ground_shares.items():
                shares[ground_index] = shares.get(ground_index, 0.0) + direct_fraction * ground_fraction
        return shares

    def _max_floor_pressure(
        self,
        ground_loads: dict[int, float],
        pending: tuple[Box, int] | None = None,
    ) -> float:
        pressure = 0.0
        for index, load in ground_loads.items():
            if index < len(self.records):
                box = self.records[index].box
            elif pending is not None and index == pending[1]:
                box = pending[0]
            else:
                continue
            area_m2 = box[3] * box[4] / 1_000_000.0
            if area_m2 > EPS:
                pressure = max(pressure, load / area_m2)
        return pressure


def interpolated_payload(container: Container, x_ratio: float) -> float | None:
    curve = container.load_distribution_curve
    if not curve:
        return None
    if x_ratio < curve[0].x_ratio - EPS or x_ratio > curve[-1].x_ratio + EPS:
        return 0.0
    for left, right in zip(curve, curve[1:]):
        if left.x_ratio - EPS <= x_ratio <= right.x_ratio + EPS:
            span = right.x_ratio - left.x_ratio
            if span <= EPS:
                return min(left.max_payload, right.max_payload)
            ratio = (x_ratio - left.x_ratio) / span
            return left.max_payload + ratio * (right.max_payload - left.max_payload)
    return curve[-1].max_payload


def analyze_stack_clusters(
    container: Container,
    loads: list[tuple[Box, float]],
) -> StackClusterMetrics:
    """Analyze vertically connected load clusters as free-standing assemblies."""
    profile = container.acceleration_profile
    if profile is None or len(loads) < 2:
        return StackClusterMetrics()

    adjacency: list[set[int]] = [set() for _ in loads]
    supporters: list[set[int]] = [set() for _ in loads]
    for upper_index, (upper, _upper_mass) in enumerate(loads):
        if upper[2] <= EPS:
            continue
        for lower_index, (lower, _lower_mass) in enumerate(loads):
            if upper_index == lower_index:
                continue
            if _support_overlap(upper, lower) <= EPS:
                continue
            adjacency[upper_index].add(lower_index)
            adjacency[lower_index].add(upper_index)
            supporters[upper_index].add(lower_index)

    visited: set[int] = set()
    margins: list[float] = []
    slenderness_values: list[float] = []
    required_longitudinal = 0.0
    required_transverse = 0.0
    for start in range(len(loads)):
        if start in visited or not adjacency[start]:
            continue
        component: list[int] = []
        stack = [start]
        visited.add(start)
        while stack:
            index = stack.pop()
            component.append(index)
            for neighbor in adjacency[index]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)

        component_set = set(component)
        bases = [index for index in component if supporters[index].isdisjoint(component_set)]
        if not bases:
            bases = [min(component, key=lambda index: loads[index][0][2])]
        base_z = min(loads[index][0][2] for index in bases)
        min_x = min(loads[index][0][0] for index in bases)
        min_y = min(loads[index][0][1] for index in bases)
        max_x = max(loads[index][0][0] + loads[index][0][3] for index in bases)
        max_y = max(loads[index][0][1] + loads[index][0][4] for index in bases)
        total_mass = sum(_effective_mass(loads[index][0], loads[index][1]) for index in component)
        if total_mass <= EPS:
            continue
        gx = sum(
            _effective_mass(loads[index][0], loads[index][1])
            * (loads[index][0][0] + loads[index][0][3] / 2.0)
            for index in component
        ) / total_mass
        gy = sum(
            _effective_mass(loads[index][0], loads[index][1])
            * (loads[index][0][1] + loads[index][0][4] / 2.0)
            for index in component
        ) / total_mass
        gz = sum(
            _effective_mass(loads[index][0], loads[index][1])
            * (loads[index][0][2] + loads[index][0][5] / 2.0)
            for index in component
        ) / total_mass
        cog_height = max(0.0, gz - base_z)
        distance_x = min(gx - min_x, max_x - gx)
        distance_y = min(gy - min_y, max_y - gy)
        margin_x = (distance_x - profile.longitudinal_g * cog_height) / max(distance_x, EPS)
        margin_y = (distance_y - profile.transverse_g * cog_height) / max(distance_y, EPS)
        required_longitudinal += max(
            0.0,
            total_mass * G * (profile.longitudinal_g - distance_x / max(cog_height, EPS)) / 1000.0,
        )
        required_transverse += max(
            0.0,
            total_mass * G * (profile.transverse_g - distance_y / max(cog_height, EPS)) / 1000.0,
        )
        margins.append(min(margin_x, margin_y))
        top_z = max(loads[index][0][2] + loads[index][0][5] for index in component)
        support_width = max(EPS, min(max_x - min_x, max_y - min_y))
        slenderness_values.append((top_z - base_z) / support_width)

    if not margins:
        return StackClusterMetrics()
    return StackClusterMetrics(
        cluster_count=len(margins),
        risky_cluster_count=sum(margin < -EPS for margin in margins),
        min_tip_stability_margin=min(margins),
        max_slenderness_ratio=max(slenderness_values, default=0.0),
        required_longitudinal_restraint_kn=required_longitudinal,
        required_transverse_restraint_kn=required_transverse,
    )


def stack_restraint_sufficient(
    container: Container,
    metrics: StackClusterMetrics,
) -> bool | None:
    if container.restraint_mode == "unverified":
        return None
    longitudinal_capacity = container.longitudinal_restraint_capacity_kn or 0.0
    transverse_capacity = container.transverse_restraint_capacity_kn or 0.0
    return (
        metrics.required_longitudinal_restraint_kn <= longitudinal_capacity + EPS
        and metrics.required_transverse_restraint_kn <= transverse_capacity + EPS
    )


def _effective_mass(box: Box, mass: float) -> float:
    return mass if mass > 0 else box[3] * box[4] * box[5]


def _support_overlap(box: Box, below: Box) -> float:
    if abs((below[2] + below[5]) - box[2]) > EPS:
        return 0.0
    overlap_x = max(0.0, min(box[0] + box[3], below[0] + below[3]) - max(box[0], below[0]))
    overlap_y = max(0.0, min(box[1] + box[4], below[1] + below[4]) - max(box[1], below[1]))
    return overlap_x * overlap_y


def _required_securement_kn(container: Container, mass: float, friction: float | None) -> float:
    profile = container.acceleration_profile
    if profile is None:
        return 0.0
    coefficient = friction or 0.0
    normal_factor = max(0.0, 1.0 - profile.vertical_g)
    longitudinal = max(0.0, profile.longitudinal_g * mass * G - coefficient * mass * G * normal_factor)
    transverse = max(0.0, profile.transverse_g * mass * G - coefficient * mass * G * normal_factor)
    return max(longitudinal, transverse) / 1000.0


def _box_tip_margin(container: Container, box: Box) -> float:
    profile = container.acceleration_profile
    if profile is None:
        return 1.0
    dx, dy, dz = box[3], box[4], box[5]
    half_height = dz / 2.0
    x_capacity = max(dx / 2.0, EPS)
    y_capacity = max(dy / 2.0, EPS)
    return min(
        (x_capacity - profile.longitudinal_g * half_height) / x_capacity,
        (y_capacity - profile.transverse_g * half_height) / y_capacity,
    )
