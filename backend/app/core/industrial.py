"""Industrial feasibility, cost, load-distribution and securing analysis."""
from __future__ import annotations

from collections import Counter
from ..models.schemas import (
    CogLimits,
    ConstraintViolation,
    Container,
    CostSummary,
    Diagnostics,
    Placement,
    LoadingAccess,
    Solution,
    SolveRequest,
)
from .geometry import oriented_dims
from .industrial_context import (
    IndustrialLoadContext,
    analyze_stack_clusters,
    interpolated_payload,
    stack_restraint_sufficient,
)
from .objectives import resolve_objective

EPS = 1e-6
G = 9.81


def prepare_request(request: SolveRequest) -> tuple[SolveRequest, list[ConstraintViolation]]:
    """Apply explicit equipment templates to a copy and validate required inputs."""
    prepared = request.model_copy(deep=True)
    violations: list[ConstraintViolation] = []
    canonical, _profile = resolve_objective(prepared.objective)
    if prepared.objective != canonical:
        violations.append(_info(
            "OBJECTIVE_DEPRECATED",
            f"策略名 {prepared.objective} 为兼容别名；请迁移到 {canonical}。",
        ))

    if prepared.validation_mode == "industrial":
        for item in prepared.items:
            if item.weight <= 0:
                violations.append(_error(
                    "ITEM_WEIGHT_REQUIRED",
                    f"工业模式下货品 {item.id} 必须配置大于 0 的实际重量。",
                    item_id=item.id,
                ))
        if canonical == "cost_efficiency":
            for pallet in prepared.pallets:
                if pallet.quantity > 0 and pallet.handling_cost is None:
                    violations.append(_error(
                        "PALLET_COST_REQUIRED",
                        f"成本策略要求托盘 {pallet.id} 配置处理成本。",
                        item_id=pallet.id,
                    ))

    for container in prepared.containers:
        if prepared.validation_mode == "industrial" and container.equipment_profile == "iso_container":
            if container.cog_limits is None:
                container.cog_limits = CogLimits()
                violations.append(_info(
                    "ISO_COG_TEMPLATE_APPLIED",
                    f"容器 {container.id} 使用 ISO 模板默认重心范围；投产前应由承运方确认。",
                    container.id,
                ))

        if prepared.validation_mode != "industrial":
            continue
        if container.equipment_profile == "generic" and container.cog_limits is None:
            violations.append(_error("COG_LIMITS_REQUIRED", f"工业模式下通用设备 {container.id} 必须配置重心范围。", container.id))
        if container.equipment_profile == "road_vehicle" and len(container.load_distribution_curve) < 2:
            violations.append(_error(
                "LOAD_DISTRIBUTION_CURVE_REQUIRED",
                f"道路车辆 {container.id} 必须配置至少两个载荷分布曲线点。",
                container.id,
            ))
        if container.max_floor_load_kg_m2 is None:
            violations.append(_error("FLOOR_LOAD_LIMIT_REQUIRED", f"工业模式下设备 {container.id} 必须配置地板载荷上限。", container.id))
        if container.acceleration_profile is None:
            violations.append(_error("ACCELERATION_PROFILE_REQUIRED", f"工业模式下设备 {container.id} 必须配置运输加速度。", container.id))
        if container.default_friction_coefficient is None:
            violations.append(_error("FRICTION_REQUIRED", f"工业模式下设备 {container.id} 必须配置默认摩擦系数。", container.id))
        if container.restraint_mode == "unverified":
            violations.append(_info(
                "STACK_RESTRAINT_UNVERIFIED",
                f"设备 {container.id} 未确认堆垛簇纵横向固定能力；风险簇仅作警告。",
                container.id,
            ))
        elif container.restraint_mode == "rated" and (
            container.longitudinal_restraint_capacity_kn is None
            or container.transverse_restraint_capacity_kn is None
        ):
            violations.append(_error(
                "STACK_RESTRAINT_CAPACITY_REQUIRED",
                f"设备 {container.id} 选择已评级固定模式时必须配置纵向和横向额定能力。",
                container.id,
            ))
        if canonical == "cost_efficiency" and container.use_cost is None:
            violations.append(_error("CONTAINER_COST_REQUIRED", f"成本策略要求设备 {container.id} 配置启用成本。", container.id))

    if canonical == "cost_efficiency" and prepared.validation_mode == "standard":
        missing = [container.id for container in prepared.containers if container.use_cost is None]
        if missing:
            violations.append(_info(
                "COST_DATA_MISSING",
                "部分容器未配置成本，已使用容器数量与容量代理进行比较。",
            ))
    return prepared, violations


def finalize_solution(
    request: SolveRequest,
    solution: Solution,
    initial_violations: list[ConstraintViolation] | None = None,
) -> dict[str, float]:
    violations = [*(initial_violations or []), *solution.violations]
    metrics: dict[str, float] = {}
    item_map = {item.id: item for item in request.items}
    container_map = {container.id: container for container in request.containers}

    must_ids = {item.id for item in request.items if item.must_load}
    missing_counts = Counter(solution.unpacked)
    for item_id in sorted(must_ids):
        if missing_counts[item_id] > 0:
            violations.append(_error(
                "MUST_LOAD_UNPACKED",
                f"必装货品 {item_id} 有 {missing_counts[item_id]} 件未装载。",
                item_id=item_id,
            ))

    canonical, _profile = resolve_objective(request.objective)
    if canonical == "delivery_sequence":
        violations.extend(_delivery_violations(request, solution, item_map))

    if request.pallet_policy == "required":
        for loaded in solution.containers:
            for placement in loaded.placements:
                if placement.pallet_id is None:
                    violations.append(_error(
                        "PALLET_REQUIRED_NOT_USED",
                        f"货品 {placement.item_id} 未按 required 托盘策略组托。",
                        loaded.id,
                        placement.item_id,
                    ))

    for loaded in solution.containers:
        pallet_instances = {pallet.id: pallet for pallet in loaded.pallet_instances}
        for placement in loaded.placements:
            if not placement.pallet_id or placement.pallet_id not in pallet_instances:
                continue
            pallet = pallet_instances[placement.pallet_id]
            item = item_map.get(placement.item_id)
            if item is None:
                continue
            dx, dy, _dz = oriented_dims(item.length, item.width, item.height, placement.orientation)
            if (
                placement.x < pallet.x - EPS
                or placement.y < pallet.y - EPS
                or placement.x + dx > pallet.x + pallet.length + EPS
                or placement.y + dy > pallet.y + pallet.width + EPS
            ):
                violations.append(_error(
                    "PALLET_OVERHANG",
                    f"货品 {placement.item_id} 超出托盘 {pallet.id} 的有效承载边界。",
                    loaded.id,
                    placement.item_id,
                ))

    container_cost = 0.0
    estimated = False
    for loaded in solution.containers:
        container = container_map.get(loaded.id)
        if container is None or container.use_cost is None:
            container_cost += 1.0
            estimated = True
        else:
            container_cost += container.use_cost

    pallet_map = {pallet.id: pallet for pallet in request.pallets}
    pallet_ids = {
        placement.pallet_id
        for loaded in solution.containers
        for placement in loaded.placements
        if placement.pallet_id
    }
    pallet_cost = 0.0
    for pallet_id in pallet_ids:
        base_id = str(pallet_id).split("#", 1)[0]
        pallet = pallet_map.get(base_id)
        if pallet is None or pallet.handling_cost is None:
            estimated = True
        else:
            pallet_cost += pallet.handling_cost
    solution.cost_summary = CostSummary(
        currency=request.cost_currency,
        container_cost=round(container_cost, 4),
        pallet_handling_cost=round(pallet_cost, 4),
        total_cost=round(container_cost + pallet_cost, 4),
        estimated=estimated,
    )
    metrics["total_cost"] = container_cost + pallet_cost

    max_floor_pressure = 0.0
    max_required_securement = 0.0
    min_tip_margin = 1.0
    min_curve_margin = 1.0
    min_cluster_tip_margin = 1.0
    risky_cluster_count = 0
    max_cluster_slenderness = 0.0
    required_stack_longitudinal = 0.0
    required_stack_transverse = 0.0
    for container_index, loaded in enumerate(solution.containers):
        container = container_map.get(loaded.id)
        if container is None:
            continue
        infos = _placement_infos(loaded.placements, item_map)
        if not infos and not loaded.pallet_instances:
            continue
        # 本轮新产生的告警都属于这一只容器实例，末尾统一打下标。
        violations_before = len(violations)
        load_context = IndustrialLoadContext(container)
        cluster_loads: list[tuple[tuple[float, float, float, float, float, float], float]] = []
        for pallet_instance in loaded.pallet_instances:
            pallet_box = (
                pallet_instance.x,
                pallet_instance.y,
                pallet_instance.z,
                pallet_instance.length,
                pallet_instance.width,
                pallet_instance.deck_height,
            )
            load_context.commit(pallet_box, pallet_instance.tare_weight)
            cluster_loads.append((pallet_box, pallet_instance.tare_weight))
        for _placement, box, mass, item in infos:
            load_context.commit(box, mass, item.friction_coefficient)
            cluster_loads.append((box, mass))
        load_metrics = load_context.metrics()
        cluster_metrics = analyze_stack_clusters(container, cluster_loads)
        metrics["cog_x_ratio"] = load_metrics.cog_x_ratio
        metrics["cog_y_ratio"] = load_metrics.cog_y_ratio
        metrics["cog_z_ratio"] = load_metrics.cog_z_ratio

        limits = container.cog_limits
        if limits is not None and not (
            limits.x_min_ratio - EPS <= metrics["cog_x_ratio"] <= limits.x_max_ratio + EPS
            and limits.y_min_ratio - EPS <= metrics["cog_y_ratio"] <= limits.y_max_ratio + EPS
            and metrics["cog_z_ratio"] <= limits.z_max_ratio + EPS
        ):
            violations.append(_error("COG_OUT_OF_RANGE", f"容器 {container.id} 的最终重心超出允许范围。", container.id))

        total_mass = load_metrics.total_mass
        allowed_payload = interpolated_payload(container, metrics["cog_x_ratio"])
        curve_margin = load_metrics.load_distribution_margin
        if allowed_payload is not None:
            min_curve_margin = min(min_curve_margin, curve_margin)
            if total_mass > allowed_payload + EPS:
                violations.append(_error(
                    "LOAD_DISTRIBUTION_EXCEEDED",
                    f"容器 {container.id} 在当前纵向重心处允许载荷 {allowed_payload:.2f}kg，实际 {total_mass:.2f}kg。",
                    container.id,
                ))

        floor_pressure = load_metrics.max_floor_load_kg_m2
        max_floor_pressure = max(max_floor_pressure, floor_pressure)
        if container.max_floor_load_kg_m2 is not None and floor_pressure > container.max_floor_load_kg_m2 + EPS:
            violations.append(_error(
                "FLOOR_LOAD_EXCEEDED",
                f"容器 {container.id} 最大地板载荷 {floor_pressure:.2f}kg/m² 超过限制 {container.max_floor_load_kg_m2:.2f}kg/m²。",
                container.id,
            ))

        required = load_metrics.required_securement_kn
        max_required_securement = max(max_required_securement, required)
        if required > EPS:
            violations.append(_warning(
                "SECURING_CAPACITY_REQUIRED",
                f"容器 {container.id} 估算至少需要 {required:.2f}kN 的方向固定能力；本系统不生成绑扎施工设计。",
                container.id,
            ))
        tip_margin = load_metrics.tip_stability_margin
        min_tip_margin = min(min_tip_margin, tip_margin)
        if tip_margin < 0:
            violations.append(_warning(
                "TIPPING_RISK",
                f"容器 {container.id} 存在加速度工况下的倾覆风险，需要支挡或绑扎。",
                container.id,
            ))
        loaded.industrial_metrics = {
            **loaded.industrial_metrics,
            "total_mass": load_metrics.total_mass,
            "cog_x_ratio": metrics["cog_x_ratio"],
            "cog_y_ratio": metrics["cog_y_ratio"],
            "cog_z_ratio": metrics["cog_z_ratio"],
            "load_distribution_margin": curve_margin,
            "max_floor_load_kg_m2": floor_pressure,
            "required_securement_kn": required,
            "tip_stability_margin": tip_margin,
            **cluster_metrics.as_dict(),
        }
        min_cluster_tip_margin = min(
            min_cluster_tip_margin, cluster_metrics.min_tip_stability_margin
        )
        risky_cluster_count += cluster_metrics.risky_cluster_count
        max_cluster_slenderness = max(
            max_cluster_slenderness, cluster_metrics.max_slenderness_ratio
        )
        required_stack_longitudinal += cluster_metrics.required_longitudinal_restraint_kn
        required_stack_transverse += cluster_metrics.required_transverse_restraint_kn
        if cluster_metrics.risky_cluster_count:
            restraint_ok = stack_restraint_sufficient(container, cluster_metrics)
            if restraint_ok is None:
                violations.append(_warning(
                    "STACK_CLUSTER_TIPPING_RISK",
                    f"容器 {container.id} 有 {cluster_metrics.risky_cluster_count} 个堆垛簇在运输加速度下存在整体倾覆风险。",
                    container.id,
                ))
            elif not restraint_ok:
                violations.append(_error(
                    "STACK_CLUSTER_RESTRAINT_INSUFFICIENT",
                    (
                        f"容器 {container.id} 的堆垛簇至少需要纵向 "
                        f"{cluster_metrics.required_longitudinal_restraint_kn:.2f}kN、横向 "
                        f"{cluster_metrics.required_transverse_restraint_kn:.2f}kN 固定能力，当前配置不足。"
                    ),
                    container.id,
                ))
        if canonical == "delivery_sequence" and request.validation_mode == "industrial":
            violations.extend(_post_drop_violations(container, infos, loaded.pallet_instances))
        for violation in violations[violations_before:]:
            violation.container_index = container_index

    metrics["max_floor_load_kg_m2"] = max_floor_pressure
    metrics["load_distribution_margin"] = min_curve_margin
    metrics["required_securement_kn"] = max_required_securement
    metrics["tip_stability_margin"] = min_tip_margin
    metrics["stack_cluster_tip_margin"] = min_cluster_tip_margin
    metrics["risky_stack_cluster_count"] = float(risky_cluster_count)
    metrics["max_stack_cluster_slenderness"] = max_cluster_slenderness
    metrics["required_stack_longitudinal_restraint_kn"] = required_stack_longitudinal
    metrics["required_stack_transverse_restraint_kn"] = required_stack_transverse

    solution.violations = _dedupe_violations(violations)
    solution.diagnostics = _summarize_diagnostics(solution)
    solution.status = _resolve_status(solution)
    return metrics


def _resolve_status(solution: Solution) -> str:
    """三层语义（与 ConstraintViolation 的 severity 对应）：

    - `infeasible`：存在 error —— 方案按现有输入无法执行，必须先解决。
    - `partial`：没有 error，但有余货 —— 装上的部分可以执行，只是没装完。
    - `feasible`：没有 error 且全部装完 —— 可以执行；仍可能带 warning（需绑扎/支挡）
      或 info（配置口径提示），由 diagnostics 与分层告警呈现，不改变可执行结论。
    """
    if any(violation.severity == "error" for violation in solution.violations):
        return "infeasible"
    if solution.unpacked:
        return "partial"
    return "feasible"


def _summarize_diagnostics(solution: Solution) -> Diagnostics:
    counts = Counter(violation.severity for violation in solution.violations)
    errors = counts.get("error", 0)
    warnings = counts.get("warning", 0)
    infos = counts.get("info", 0)
    unpacked = len(solution.unpacked)

    if errors:
        reason = f"{errors} 项硬约束未满足，方案不可执行。"
        if unpacked:
            reason += f"另有 {unpacked} 件余货未装载。"
    elif unpacked:
        reason = f"已装载部分可执行，但有 {unpacked} 件余货未装下。"
    elif warnings:
        reason = f"方案可执行，但有 {warnings} 项风险需要绑扎或支挡等措施。"
    else:
        reason = "方案可执行，无风险项。"

    return Diagnostics(
        error_count=errors,
        warning_count=warnings,
        info_count=infos,
        unpacked_count=unpacked,
        status_reason=reason,
    )


def _placement_infos(placements: list[Placement], item_map: dict):
    infos = []
    for placement in placements:
        item = item_map.get(placement.item_id)
        if item is None:
            continue
        dims = oriented_dims(item.length, item.width, item.height, placement.orientation)
        mass = item.weight if item.weight > 0 else dims[0] * dims[1] * dims[2]
        infos.append((placement, (placement.x, placement.y, placement.z, *dims), mass, item))
    return infos


def _interpolated_payload(container: Container, x_ratio: float) -> float | None:
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
            t = (x_ratio - left.x_ratio) / span
            return left.max_payload + t * (right.max_payload - left.max_payload)
    return curve[-1].max_payload


def _max_floor_pressure(infos) -> float:
    if not infos:
        return 0.0
    transmitted = [info[2] for info in infos]
    order = sorted(range(len(infos)), key=lambda i: infos[i][1][2], reverse=True)
    for index in order:
        box = infos[index][1]
        if box[2] <= EPS:
            continue
        supporters: list[tuple[int, float]] = []
        for below_index, below in enumerate(infos):
            b = below[1]
            if abs((b[2] + b[5]) - box[2]) > EPS:
                continue
            ox = max(0.0, min(box[0] + box[3], b[0] + b[3]) - max(box[0], b[0]))
            oy = max(0.0, min(box[1] + box[4], b[1] + b[4]) - max(box[1], b[1]))
            if ox * oy > EPS:
                supporters.append((below_index, ox * oy))
        total_area = sum(area for _i, area in supporters)
        for below_index, area in supporters:
            transmitted[below_index] += transmitted[index] * area / total_area

    pressure = 0.0
    for index, info in enumerate(infos):
        box = info[1]
        if box[2] > EPS:
            continue
        area_m2 = box[3] * box[4] / 1_000_000.0
        if area_m2 > EPS:
            pressure = max(pressure, transmitted[index] / area_m2)
    return pressure


def _required_securement_kn(container: Container, mass: float, infos) -> float:
    profile = container.acceleration_profile
    if profile is None:
        return 0.0
    coefficients = [
        info[3].friction_coefficient
        for info in infos
        if info[3].friction_coefficient is not None
    ]
    mu = min(coefficients) if coefficients else (container.default_friction_coefficient or 0.0)
    normal_factor = max(0.0, 1.0 - profile.vertical_g)
    longitudinal = max(0.0, profile.longitudinal_g * mass * G - mu * mass * G * normal_factor)
    transverse = max(0.0, profile.transverse_g * mass * G - mu * mass * G * normal_factor)
    return max(longitudinal, transverse) / 1000.0


def _tip_stability_margin(container: Container, infos) -> float:
    profile = container.acceleration_profile
    if profile is None or not infos:
        return 1.0
    margins: list[float] = []
    for _placement, box, _mass, _item in infos:
        dx, dy, dz = box[3], box[4], box[5]
        half_height = dz / 2.0
        x_capacity = max(dx / 2.0, EPS)
        y_capacity = max(dy / 2.0, EPS)
        margins.append((x_capacity - profile.longitudinal_g * half_height) / x_capacity)
        margins.append((y_capacity - profile.transverse_g * half_height) / y_capacity)
    return min(margins)


def _post_drop_violations(container: Container, infos, pallet_instances=()) -> list[ConstraintViolation]:
    violations: list[ConstraintViolation] = []
    stops = sorted({info[0].stop_seq for info in infos})
    for stop in stops[:-1]:
        remaining = [info for info in infos if info[0].stop_seq > stop]
        if not remaining:
            continue
        context = IndustrialLoadContext(container)
        remaining_cluster_loads = []
        for pallet in pallet_instances:
            if pallet.stop_seq <= stop:
                continue
            pallet_box = (pallet.x, pallet.y, pallet.z, pallet.length, pallet.width, pallet.deck_height)
            context.commit(pallet_box, pallet.tare_weight)
            remaining_cluster_loads.append((pallet_box, pallet.tare_weight))
        for _placement, box, mass, item in remaining:
            context.commit(box, mass, item.friction_coefficient)
            remaining_cluster_loads.append((box, mass))
        remaining_metrics = context.metrics()
        remaining_cluster_metrics = analyze_stack_clusters(container, remaining_cluster_loads)
        mass = remaining_metrics.total_mass
        gx_ratio = remaining_metrics.cog_x_ratio
        gy_ratio = remaining_metrics.cog_y_ratio
        gz_ratio = remaining_metrics.cog_z_ratio
        limits = container.cog_limits
        if limits is not None and not (
            limits.x_min_ratio - EPS <= gx_ratio <= limits.x_max_ratio + EPS
            and limits.y_min_ratio - EPS <= gy_ratio <= limits.y_max_ratio + EPS
            and gz_ratio <= limits.z_max_ratio + EPS
        ):
            violations.append(ConstraintViolation(
                code="POST_DROP_COG_OUT_OF_RANGE",
                severity="error",
                message=f"容器 {container.id} 在站点 {stop} 卸货后剩余载荷重心超限。",
                container_id=container.id,
                stop_seq=stop,
            ))
        allowed = _interpolated_payload(container, gx_ratio)
        if allowed is not None and mass > allowed + EPS:
            violations.append(ConstraintViolation(
                code="POST_DROP_DISTRIBUTION_EXCEEDED",
                severity="error",
                message=f"容器 {container.id} 在站点 {stop} 卸货后剩余载荷超过载荷分布曲线。",
                container_id=container.id,
                stop_seq=stop,
            ))
        pressure = remaining_metrics.max_floor_load_kg_m2
        if container.max_floor_load_kg_m2 is not None and pressure > container.max_floor_load_kg_m2 + EPS:
            violations.append(ConstraintViolation(
                code="POST_DROP_FLOOR_LOAD_EXCEEDED",
                severity="error",
                message=f"容器 {container.id} 在站点 {stop} 卸货后地板载荷超限。",
                container_id=container.id,
                stop_seq=stop,
            ))
        if remaining_cluster_metrics.risky_cluster_count:
            restraint_ok = stack_restraint_sufficient(container, remaining_cluster_metrics)
            if restraint_ok is None:
                violations.append(ConstraintViolation(
                    code="POST_DROP_STACK_CLUSTER_TIPPING_RISK",
                    severity="warning",
                    message=(
                        f"容器 {container.id} 在站点 {stop} 卸货后有 "
                        f"{remaining_cluster_metrics.risky_cluster_count} 个堆垛簇存在整体倾覆风险。"
                    ),
                    container_id=container.id,
                    stop_seq=stop,
                ))
            elif not restraint_ok:
                violations.append(ConstraintViolation(
                    code="POST_DROP_STACK_CLUSTER_RESTRAINT_INSUFFICIENT",
                    severity="error",
                    message=f"容器 {container.id} 在站点 {stop} 卸货后的堆垛簇固定能力不足。",
                    container_id=container.id,
                    stop_seq=stop,
                ))
    return violations


def _delivery_violations(request: SolveRequest, solution: Solution, item_map: dict) -> list[ConstraintViolation]:
    container_map = {container.id: container for container in request.containers}
    violations: list[ConstraintViolation] = []
    for loaded in solution.containers:
        container = container_map.get(loaded.id)
        if container is None:
            continue
        infos = _placement_infos(loaded.placements, item_map)
        count = len(infos)
        support_blockers: list[set[int]] = [set() for _ in range(count)]
        # An earlier-stop supporter would have to be removed before its later-stop load.
        for bottom_index, bottom in enumerate(infos):
            b = bottom[1]
            for top_index, top in enumerate(infos):
                if bottom_index == top_index:
                    continue
                t = top[1]
                if abs((b[2] + b[5]) - t[2]) > EPS:
                    continue
                if _overlap_2d(b[0], b[0] + b[3], t[0], t[0] + t[3]) <= EPS:
                    continue
                if _overlap_2d(b[1], b[1] + b[4], t[1], t[1] + t[4]) <= EPS:
                    continue
                support_blockers[bottom_index].add(top_index)
                if bottom[0].stop_seq < top[0].stop_seq:
                    violations.append(ConstraintViolation(
                        code="DELIVERY_SUPPORT_ORDER",
                        severity="error",
                        message=f"早卸货 {bottom[0].item_id} 支撑了晚卸货 {top[0].item_id}。",
                        container_id=container.id,
                        item_id=bottom[0].item_id,
                        stop_seq=bottom[0].stop_seq,
                    ))

        accesses = container.loading_accesses or [
            LoadingAccess(side="x_max", door_width=container.door_width, door_height=container.door_height)
        ]
        path_options: list[list[set[int]]] = [[] for _ in range(count)]
        for index, info in enumerate(infos):
            box = info[1]
            for access in accesses:
                if not _aligned_with_opening(box, access, container):
                    continue
                blockers = {
                    other_index
                    for other_index, other in enumerate(infos)
                    if other_index != index and _blocks_corridor(box, other[1], access.side)
                }
                path_options[index].append(blockers)

        active = set(range(count))
        for stop in sorted({info[0].stop_seq for info in infos}):
            targets = {index for index in active if infos[index][0].stop_seq == stop}
            while targets:
                removable = [
                    index for index in targets
                    if support_blockers[index].isdisjoint(active)
                    and any(blockers.isdisjoint(active) for blockers in path_options[index])
                ]
                if not removable:
                    for index in sorted(targets):
                        placement = infos[index][0]
                        violations.append(ConstraintViolation(
                            code="DELIVERY_PATH_BLOCKED",
                            severity="error",
                            message=f"货品 {placement.item_id} 在站点 {stop} 无无需倒货的直线卸货路径。",
                            container_id=container.id,
                            item_id=placement.item_id,
                            stop_seq=stop,
                        ))
                    break
                active.difference_update(removable)
                targets.difference_update(removable)
    return violations


def _can_remove(index: int, active: set[int], infos, container: Container) -> bool:
    box = infos[index][1]
    # Anything resting on the target must leave first, including same-stop cargo.
    for other_index in active:
        if other_index == index:
            continue
        other = infos[other_index][1]
        if abs((box[2] + box[5]) - other[2]) <= EPS and _xy_overlap(box, other):
            return False
    accesses = container.loading_accesses or [LoadingAccess(side="x_max", door_width=container.door_width, door_height=container.door_height)]
    return any(
        _aligned_with_opening(box, access, container)
        and not any(
            other_index != index and _blocks_corridor(box, infos[other_index][1], access.side)
            for other_index in active
        )
        for access in accesses
    )


def _aligned_with_opening(box, access: LoadingAccess, container: Container) -> bool:
    x, y, z, dx, dy, dz = box
    if access.side in {"x_min", "x_max"}:
        low, high = _opening_span(access, container.inner_width)
        height = access.door_height if access.door_height is not None else container.inner_height
        return y >= low - EPS and y + dy <= high + EPS and z + dz <= height + EPS
    if access.side in {"y_min", "y_max"}:
        low, high = _opening_span(access, container.inner_length)
        height = access.door_height if access.door_height is not None else container.inner_height
        return x >= low - EPS and x + dx <= high + EPS and z + dz <= height + EPS
    low, high = _opening_span(access, container.inner_length)
    y_span = access.door_height if access.door_height is not None else container.inner_width
    y_low = (container.inner_width - y_span) / 2.0
    return x >= low - EPS and x + dx <= high + EPS and y >= y_low - EPS and y + dy <= y_low + y_span + EPS


def _opening_span(access: LoadingAccess, full: float) -> tuple[float, float]:
    if access.opening_start is not None and access.opening_end is not None:
        return access.opening_start, access.opening_end
    width = access.door_width if access.door_width is not None else full
    low = max(0.0, (full - width) / 2.0)
    return low, min(full, low + width)


def _blocks_corridor(box, other, side: str) -> bool:
    x, y, z, dx, dy, dz = box
    ox, oy, oz, odx, ody, odz = other
    if side in {"x_min", "x_max"}:
        cross = _overlap_2d(y, y + dy, oy, oy + ody) > EPS and _overlap_2d(z, z + dz, oz, oz + odz) > EPS
        return cross and ((side == "x_min" and ox < x - EPS) or (side == "x_max" and ox + odx > x + dx + EPS))
    if side in {"y_min", "y_max"}:
        cross = _overlap_2d(x, x + dx, ox, ox + odx) > EPS and _overlap_2d(z, z + dz, oz, oz + odz) > EPS
        return cross and ((side == "y_min" and oy < y - EPS) or (side == "y_max" and oy + ody > y + dy + EPS))
    cross = _overlap_2d(x, x + dx, ox, ox + odx) > EPS and _overlap_2d(y, y + dy, oy, oy + ody) > EPS
    return cross and oz + odz > z + dz + EPS


def _xy_overlap(a, b) -> bool:
    return (
        _overlap_2d(a[0], a[0] + a[3], b[0], b[0] + b[3]) > EPS
        and _overlap_2d(a[1], a[1] + a[4], b[1], b[1] + b[4]) > EPS
    )


def _overlap_2d(a1: float, a2: float, b1: float, b2: float) -> float:
    return max(0.0, min(a2, b2) - max(a1, b1))


def _info(code: str, message: str, container_id: str = "", item_id: str = "") -> ConstraintViolation:
    """配置口径 / 兼容性提示：不要求改动布局。"""
    return ConstraintViolation(code=code, severity="info", message=message, container_id=container_id, item_id=item_id)


def _warning(code: str, message: str, container_id: str = "", item_id: str = "") -> ConstraintViolation:
    """布局存在物理风险：要绑扎、支挡才能上路。"""
    return ConstraintViolation(code=code, severity="warning", message=message, container_id=container_id, item_id=item_id)


def _error(code: str, message: str, container_id: str = "", item_id: str = "") -> ConstraintViolation:
    """方案不可执行或必填输入缺失：必须解决。"""
    return ConstraintViolation(code=code, severity="error", message=message, container_id=container_id, item_id=item_id)


def _dedupe_violations(violations: list[ConstraintViolation]) -> list[ConstraintViolation]:
    seen: set[tuple] = set()
    result: list[ConstraintViolation] = []
    for violation in violations:
        # container_index 必须入键：多只容器共用同一个类型 id，两只箱子给出字面相同的
        # 告警时，不带下标去重会把其中一只悄悄吞掉。
        key = (
            violation.code, violation.severity, violation.message,
            violation.container_id, violation.container_index,
            violation.item_id, violation.stop_seq,
        )
        if key not in seen:
            seen.add(key)
            result.append(violation)
    return result
