"""Solution evaluation and strategy-fit scoring.

The scoring contract is documented in docs/evaluation.md. Keep that document in
sync whenever strategy metrics, weights, or score semantics change.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from ..models.schemas import Container, ContainerEvaluation, Evaluation, Item, Placement, Solution, SolveRequest
from .geometry import oriented_dims
from .objectives import resolve_objective


@dataclass(frozen=True)
class _PlacementInfo:
    container_index: int
    placement: Placement
    item: Item
    container: Container
    dims: tuple[float, float, float]
    volume: float
    mass: float


_STRATEGY_WEIGHTS: dict[str, dict[str, float]] = {
    "cost_efficiency": {
        "loaded_completion": 0.40,
        "cost_efficiency_score": 0.35,
        "used_volume_utilization": 0.15,
        "weight_utilization": 0.10,
    },
    "space_utilization": {
        "loaded_completion": 0.40,
        "used_volume_utilization": 0.40,
        "container_count_score": 0.10,
        "weight_utilization": 0.10,
    },
    "safe_loading": {
        "safety_worst_score": 0.50,
        "stability_score": 0.20,
        "balance_score": 0.20,
        "loaded_completion": 0.08,
        "used_volume_utilization": 0.02,
    },
    "delivery_sequence": {
        "loading_score": 0.50,
        "loaded_completion": 0.25,
        "used_volume_utilization": 0.15,
        "balance_score": 0.10,
    },
    "transport_cost": {
        "loaded_completion": 0.40,
        "container_count_score": 0.30,
        "used_volume_utilization": 0.20,
        "weight_utilization": 0.10,
    },
    "max_utilization": {
        "loaded_completion": 0.40,
        "container_count_score": 0.30,
        "used_volume_utilization": 0.20,
        "weight_utilization": 0.10,
    },
    "min_containers": {
        "loaded_completion": 0.35,
        "container_count_score": 0.40,
        "used_volume_utilization": 0.15,
        "weight_utilization": 0.10,
    },
    "load_stability": {
        "stability_score": 0.45,
        "loaded_completion": 0.20,
        "balance_score": 0.15,
        "pallet_score": 0.10,
        "used_volume_utilization": 0.10,
    },
    "stability": {
        "stability_score": 0.45,
        "loaded_completion": 0.20,
        "balance_score": 0.15,
        "pallet_score": 0.10,
        "used_volume_utilization": 0.10,
    },
    "weight_balance": {
        "balance_score": 0.55,
        "loaded_completion": 0.25,
        "stability_score": 0.10,
        "used_volume_utilization": 0.10,
    },
    "center_of_gravity": {
        "balance_score": 0.55,
        "loaded_completion": 0.25,
        "stability_score": 0.10,
        "used_volume_utilization": 0.10,
    },
    "loading_efficiency": {
        "loading_score": 0.45,
        "loaded_completion": 0.25,
        "used_volume_utilization": 0.15,
        "balance_score": 0.10,
        "pallet_score": 0.05,
    },
    "multi_customer_delivery": {
        "loading_score": 0.45,
        "loaded_completion": 0.25,
        "used_volume_utilization": 0.15,
        "balance_score": 0.10,
        "pallet_score": 0.05,
    },
}


def evaluate_solution(request: SolveRequest, solution: Solution) -> Evaluation:
    item_map = {item.id: item for item in request.items}
    container_map = {container.id: container for container in request.containers}
    infos = _placement_infos(solution, item_map, container_map)
    metrics = _base_metrics(request, solution, infos)
    objective = request.objective
    resolved, profile_name = resolve_objective(objective)

    if objective in {"advanced_score", "balanced", "custom"}:
        weights = request.advanced_weights
        profile = {
            "cost_efficiency_score": weights.cost_efficiency if weights else 0.15,
            "used_volume_utilization": weights.space_utilization if weights else 0.35,
            "stability_score": weights.stability if weights else 0.25,
            "balance_score": weights.balance if weights else 0.15,
            "loading_score": weights.loading_position if weights else 0.10,
        }
    else:
        profile = _STRATEGY_WEIGHTS.get(objective, _STRATEGY_WEIGHTS["transport_cost"])

    score = _weighted_score(metrics, profile)
    warnings = _warnings(metrics, objective)
    return Evaluation(
        objective=objective,
        objective_requested=objective,
        objective_resolved=resolved,
        strategy_profile=profile_name,
        score=round(score, 1),
        grade=_grade(score),
        metrics={key: round(value, 4) for key, value in metrics.items()},
        warnings=warnings,
        containers=_container_evaluations(solution, infos, profile, objective),
    )


def _placement_infos(
    solution: Solution,
    item_map: dict[str, Item],
    container_map: dict[str, Container],
) -> list[_PlacementInfo]:
    infos: list[_PlacementInfo] = []
    for container_index, loaded in enumerate(solution.containers):
        container = container_map.get(loaded.id)
        if container is None:
            continue
        for placement in loaded.placements:
            item = item_map.get(placement.item_id)
            if item is None:
                continue
            dims = oriented_dims(item.length, item.width, item.height, placement.orientation)
            volume = dims[0] * dims[1] * dims[2]
            mass = item.weight if item.weight > 0 else volume
            infos.append(_PlacementInfo(container_index, placement, item, container, dims, volume, mass))
    return infos


def _base_metrics(request: SolveRequest, solution: Solution, infos: list[_PlacementInfo]) -> dict[str, float]:
    item_volume_map = {item.id: item.length * item.width * item.height for item in request.items}
    container_volume_map = {
        container.id: container.inner_length * container.inner_width * container.inner_height
        for container in request.containers
    }
    container_payload_map = {container.id: container.max_payload for container in request.containers}
    total_volume = sum(item.length * item.width * item.height * item.quantity for item in request.items)
    total_weight = sum(item.weight * item.quantity for item in request.items)
    loaded_volume = sum(info.volume for info in infos)
    loaded_weight = sum(info.item.weight for info in infos)
    unpacked_volume = sum(item_volume_map.get(item_id, 0.0) for item_id in solution.unpacked)
    available_volume = sum(c.inner_length * c.inner_width * c.inner_height * c.quantity for c in request.containers)
    available_payload = sum(c.max_payload * c.quantity for c in request.containers)
    used_volume = sum(container_volume_map.get(loaded.id, 0.0) for loaded in solution.containers)
    used_payload = sum(container_payload_map.get(loaded.id, 0.0) for loaded in solution.containers)

    loaded_completion = _ratio(loaded_volume, total_volume)
    available_fit_ratio = _ratio(loaded_volume, min_positive(total_volume, available_volume))
    used_volume_utilization = _ratio(loaded_volume, used_volume)
    weight_utilization = _ratio(loaded_weight, used_payload) if used_payload > 0 else 1.0
    unpacked_penalty = _ratio(unpacked_volume, total_volume)

    stability_score = _stability_score(infos)
    balance_score = _balance_score(solution, infos)
    return {
        "loaded_completion": loaded_completion,
        "available_fit_ratio": available_fit_ratio,
        "used_volume_utilization": used_volume_utilization,
        "weight_utilization": weight_utilization,
        "container_count_score": _container_count_score(request, solution, total_volume, total_weight),
        "cost_efficiency_score": _cost_efficiency_score(request, solution, total_volume, total_weight),
        "stability_score": stability_score,
        "balance_score": balance_score,
        "safety_worst_score": min(stability_score, balance_score),
        "loading_score": _loading_score(infos),
        "pallet_score": _pallet_score(infos),
        "unpacked_penalty": unpacked_penalty,
    }


def _container_evaluations(
    solution: Solution,
    infos: list[_PlacementInfo],
    profile: dict[str, float],
    objective: str,
) -> list[ContainerEvaluation]:
    evaluations: list[ContainerEvaluation] = []
    infos_by_container = _infos_by_container_index(infos)
    for container_index, loaded in enumerate(solution.containers):
        container_infos = infos_by_container.get(container_index, [])
        metrics = _container_metrics(container_infos)
        metrics.update(loaded.industrial_metrics)
        score = _weighted_score(metrics, profile)
        evaluations.append(ContainerEvaluation(
            index=container_index,
            id=loaded.id,
            score=round(score, 1),
            grade=_grade(score),
            metrics={key: round(value, 4) for key, value in metrics.items()},
            warnings=_warnings(metrics, objective),
        ))
    return evaluations


def _container_metrics(infos: list[_PlacementInfo]) -> dict[str, float]:
    if not infos:
        return {
            "loaded_completion": 0.0,
            "available_fit_ratio": 0.0,
            "used_volume_utilization": 0.0,
            "weight_utilization": 0.0,
            "container_count_score": 1.0,
            "cost_efficiency_score": 1.0,
            "stability_score": 1.0,
            "balance_score": 1.0,
            "safety_worst_score": 1.0,
            "loading_score": 1.0,
            "pallet_score": 1.0,
            "unpacked_penalty": 0.0,
        }
    container = infos[0].container
    loaded_volume = sum(info.volume for info in infos)
    loaded_weight = sum(info.item.weight for info in infos)
    container_volume = container.inner_length * container.inner_width * container.inner_height
    stability_score = _stability_score(infos)
    balance_score = _balance_score_from_infos(infos)
    return {
        "loaded_completion": 1.0,
        "available_fit_ratio": 1.0,
        "used_volume_utilization": _ratio(loaded_volume, container_volume),
        "weight_utilization": _ratio(loaded_weight, container.max_payload),
        "container_count_score": 1.0,
        "cost_efficiency_score": 1.0,
        "stability_score": stability_score,
        "balance_score": balance_score,
        "safety_worst_score": min(stability_score, balance_score),
        "loading_score": _loading_score(infos),
        "pallet_score": _pallet_score(infos),
        "unpacked_penalty": 0.0,
    }


def _container_count_score(
    request: SolveRequest,
    solution: Solution,
    total_volume: float,
    total_weight: float,
) -> float:
    if not request.items:
        return 1.0
    used = max(len(solution.containers), 1)
    max_volume = max((c.inner_length * c.inner_width * c.inner_height for c in request.containers), default=0.0)
    max_payload = max((c.max_payload for c in request.containers), default=0.0)
    volume_lb = ceil(total_volume / max_volume) if max_volume > 0 else used
    weight_lb = ceil(total_weight / max_payload) if max_payload > 0 and total_weight > 0 else 1
    lower_bound = max(1, volume_lb, weight_lb)
    return _clamp(lower_bound / used)


def _cost_efficiency_score(
    request: SolveRequest,
    solution: Solution,
    total_volume: float,
    total_weight: float,
) -> float:
    if not request.items:
        return 1.0
    container_map = {container.id: container for container in request.containers}
    actual = 0.0
    for loaded in solution.containers:
        container = container_map.get(loaded.id)
        actual += container.use_cost if container is not None and container.use_cost is not None else 1.0
    pallet_map = {pallet.id: pallet for pallet in request.pallets}
    seen_pallets = {
        placement.pallet_id
        for loaded in solution.containers
        for placement in loaded.placements
        if placement.pallet_id
    }
    for pallet_id in seen_pallets:
        pallet = pallet_map.get(str(pallet_id).split("#", 1)[0])
        if pallet is not None and pallet.handling_cost is not None:
            actual += pallet.handling_cost
    if actual <= 0:
        return 1.0

    lower_bounds: list[float] = []
    for container in request.containers:
        volume = container.inner_length * container.inner_width * container.inner_height
        if volume <= 0:
            continue
        volume_count = ceil(total_volume / volume) if total_volume > 0 else 1
        weight_count = ceil(total_weight / container.max_payload) if total_weight > 0 else 1
        required = max(1, volume_count, weight_count)
        if required <= container.quantity:
            cost = container.use_cost if container.use_cost is not None else 1.0
            lower_bounds.append(required * cost)
    theoretical = min(lower_bounds) if lower_bounds else min(actual, 1.0)
    return _clamp(theoretical / actual)


def _stability_score(infos: list[_PlacementInfo]) -> float:
    if not infos:
        return 1.0
    total_mass = sum(info.mass for info in infos)
    penalty = 0.0
    for info in infos:
        dx, dy, dz = info.dims
        center_height = (info.placement.z + dz / 2.0) / info.container.inner_height
        base_ratio = min((dx * dy) / (info.container.inner_length * info.container.inner_width), 1.0)
        slenderness = min(dz / max(dx, dy, 1.0), 1.0)
        penalty += info.mass * (0.55 * center_height + 0.25 * (1.0 - base_ratio) + 0.20 * slenderness)
    return _clamp(1.0 - penalty / total_mass)


def _balance_score(solution: Solution, infos: list[_PlacementInfo]) -> float:
    if not solution.containers:
        return 1.0
    penalties: list[float] = []
    infos_by_container = _infos_by_container_index(infos)
    for container_index, _loaded in enumerate(solution.containers):
        container_infos = infos_by_container.get(container_index, [])
        total_mass = sum(info.mass for info in container_infos)
        if total_mass <= 0 or not container_infos:
            continue
        container = container_infos[0].container
        gx = sum(info.mass * (info.placement.x + info.dims[0] / 2.0) for info in container_infos) / total_mass
        gy = sum(info.mass * (info.placement.y + info.dims[1] / 2.0) for info in container_infos) / total_mass
        norm_x = abs(gx - container.inner_length / 2.0) / container.inner_length
        norm_y = abs(gy - container.inner_width / 2.0) / container.inner_width
        penalties.append(min(max(norm_x, norm_y) + norm_x + norm_y, 1.0))
    return _clamp(1.0 - (sum(penalties) / len(penalties) if penalties else 0.0))


def _balance_score_from_infos(infos: list[_PlacementInfo]) -> float:
    if not infos:
        return 1.0
    penalties: list[float] = []
    infos_by_container = _infos_by_container_index(infos)
    for container_index in sorted(infos_by_container):
        container_infos = infos_by_container[container_index]
        total_mass = sum(info.mass for info in container_infos)
        if total_mass <= 0 or not container_infos:
            continue
        container = container_infos[0].container
        gx = sum(info.mass * (info.placement.x + info.dims[0] / 2.0) for info in container_infos) / total_mass
        gy = sum(info.mass * (info.placement.y + info.dims[1] / 2.0) for info in container_infos) / total_mass
        norm_x = abs(gx - container.inner_length / 2.0) / container.inner_length
        norm_y = abs(gy - container.inner_width / 2.0) / container.inner_width
        penalties.append(min(max(norm_x, norm_y) + norm_x + norm_y, 1.0))
    return _clamp(1.0 - (sum(penalties) / len(penalties) if penalties else 0.0))


def _infos_by_container_index(infos: list[_PlacementInfo]) -> dict[int, list[_PlacementInfo]]:
    grouped: dict[int, list[_PlacementInfo]] = {}
    for info in infos:
        grouped.setdefault(info.container_index, []).append(info)
    return grouped


def _loading_score(infos: list[_PlacementInfo]) -> float:
    if not infos:
        return 1.0
    stops = [max(1, int(info.placement.stop_seq or 1)) for info in infos]
    min_stop, max_stop = min(stops), max(stops)
    has_stops = max_stop > min_stop
    penalties: list[float] = []
    for info in infos:
        sides = tuple(access.side for access in info.container.loading_accesses) or ("x_max",)
        depth = min(_normalized_depth(info, side) for side in sides)
        if has_stops:
            stop_pos = (max(1, int(info.placement.stop_seq or 1)) - min_stop) / (max_stop - min_stop)
            penalties.append(abs(depth - stop_pos))
        else:
            penalties.append(1.0 - depth)
    return _clamp(1.0 - sum(penalties) / len(penalties))


def _pallet_score(infos: list[_PlacementInfo]) -> float:
    if not infos:
        return 1.0
    return sum(1 for info in infos if info.placement.pallet_id is not None) / len(infos)


def _normalized_depth(info: _PlacementInfo, side: str) -> float:
    p = info.placement
    dx, dy, dz = info.dims
    c = info.container
    if side == "x_min":
        return _ratio(p.x, c.inner_length)
    if side == "x_max":
        return _ratio(c.inner_length - (p.x + dx), c.inner_length)
    if side == "y_min":
        return _ratio(p.y, c.inner_width)
    if side == "y_max":
        return _ratio(c.inner_width - (p.y + dy), c.inner_width)
    if side == "z_max":
        return _ratio(c.inner_height - (p.z + dz), c.inner_height)
    return 0.0


def _weighted_score(metrics: dict[str, float], profile: dict[str, float]) -> float:
    total_weight = sum(profile.values()) or 1.0
    base = sum(metrics.get(metric, 0.0) * weight for metric, weight in profile.items()) / total_weight
    penalty = 0.35 * metrics.get("unpacked_penalty", 0.0)
    return 100.0 * _clamp(base - penalty)


def _warnings(metrics: dict[str, float], objective: str) -> list[str]:
    warnings: list[str] = []
    if metrics["unpacked_penalty"] > 0:
        warnings.append("存在未装货物，评分已按未装体积扣分。")
    if metrics["balance_score"] < 0.75:
        warnings.append("容器重心存在明显偏移。")
    if metrics["stability_score"] < 0.70:
        warnings.append("装载稳定性偏低，可能存在高位或细高堆放。")
    if objective in {"loading_efficiency", "multi_customer_delivery"} and metrics["loading_score"] < 0.75:
        warnings.append("卸货顺序与装货入口位置匹配度偏低。")
    if objective in {"transport_cost", "max_utilization", "min_containers"} and metrics["container_count_score"] < 0.90:
        warnings.append("使用容器数高于理论下界。")
    return warnings


def _grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 1.0
    return _clamp(numerator / denominator)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def min_positive(*values: float) -> float:
    positives = [value for value in values if value > 0]
    return min(positives) if positives else 1.0
