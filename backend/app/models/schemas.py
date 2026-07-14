"""Pydantic 数据模型（对外契约）。

单位约定：尺寸 mm，重量 kg。
坐标系：原点在容器内部一个底角，x=长(length)，y=宽(width)，z=高(height, 向上)。
详见 CLAUDE.md 第 5 节。
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

# 六种轴对齐朝向：三个字母依次表示原始的 (长,宽,高) 中哪一维分别落在 x / y / z 轴。
# 例：'LWH' 表示 x=长、y=宽、z=高（默认朝向）；'LHW' 表示把货品侧放，原本的高朝向 y。
Orientation = Literal["LWH", "WLH", "LHW", "HWL", "WHL", "HLW"]
ALL_ORIENTATIONS: tuple[Orientation, ...] = ("LWH", "WLH", "LHW", "HWL", "WHL", "HLW")

Objective = Literal[
    "cost_efficiency", "space_utilization", "safe_loading", "delivery_sequence", "custom",
    "transport_cost", "load_stability", "weight_balance", "loading_efficiency",
    "advanced_score",
    "max_utilization", "min_containers", "stability", "balanced", "center_of_gravity",
    "multi_customer_delivery",
]
GASpeed = Literal["fast", "standard", "fine"]
ValidationMode = Literal["standard", "industrial"]
PalletPolicy = Literal["auto", "prefer", "avoid", "required"]
EquipmentProfile = Literal["generic", "iso_container", "road_vehicle"]
RestraintMode = Literal["unverified", "none", "rated"]
SolutionStatus = Literal["feasible", "partial", "infeasible"]
StackingType = Literal[
    "not_stackable", "same_item_only", "stackable", "support_only", "top_only"
]
LoadingAccessSide = Literal["x_min", "x_max", "y_min", "y_max", "z_max"]


class Item(BaseModel):
    id: str
    name: str = ""
    length: float = Field(gt=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    weight: float = Field(ge=0, default=0.0)
    quantity: int = Field(ge=1, default=1)
    allowed_rotations: list[Orientation] = Field(default_factory=lambda: list(ALL_ORIENTATIONS))
    stackable: bool = True
    stacking_type: StackingType = "stackable"
    # 顶部可承重 kg：None=未指定(无限制)，0=易碎不可压，>0=承重上限。
    max_load_top: Optional[float] = Field(ge=0, default=None)
    category: str = ""
    customer_id: str = ""
    order_id: str = ""
    destination_id: str = ""
    stop_seq: int = Field(ge=1, default=1)
    must_load: bool = False
    priority: int = Field(ge=0, le=100, default=0)
    pallet_group: str = ""
    friction_coefficient: Optional[float] = Field(default=None, ge=0, le=2)

    @model_validator(mode="after")
    def normalize_top_load_for_stacking_type(self):
        if self.stacking_type in {"not_stackable", "top_only"}:
            self.max_load_top = 0
        if not self.stackable and self.stacking_type == "stackable":
            self.max_load_top = 0
        return self


class Pallet(BaseModel):
    id: str
    name: str = ""
    length: float = Field(gt=0)
    width: float = Field(gt=0)
    tare_weight: float = Field(ge=0, default=0.0)
    deck_height: float = Field(ge=0, default=0.0)
    max_stack_height: float = Field(gt=0)
    max_load: float = Field(gt=0)
    quantity: int = Field(ge=0, default=0)
    handling_cost: Optional[float] = Field(default=None, ge=0)
    friction_coefficient: Optional[float] = Field(default=None, ge=0, le=2)

class LoadingAccess(BaseModel):
    side: LoadingAccessSide = "x_max"
    door_width: Optional[float] = Field(default=None, ge=0)
    door_height: Optional[float] = Field(default=None, ge=0)
    opening_start: Optional[float] = Field(default=None, ge=0)
    opening_end: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_opening_range(self):
        if (
            self.opening_start is not None
            and self.opening_end is not None
            and self.opening_end < self.opening_start
        ):
            raise ValueError("opening_end must be greater than or equal to opening_start")
        return self


class CogLimits(BaseModel):
    x_min_ratio: float = Field(ge=0, le=1, default=0.45)
    x_max_ratio: float = Field(ge=0, le=1, default=0.55)
    y_min_ratio: float = Field(ge=0, le=1, default=0.45)
    y_max_ratio: float = Field(ge=0, le=1, default=0.55)
    z_max_ratio: float = Field(gt=0, le=1, default=0.50)

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.x_max_ratio < self.x_min_ratio or self.y_max_ratio < self.y_min_ratio:
            raise ValueError("COG maximum ratios must be greater than or equal to minimum ratios")
        return self


class LoadDistributionPoint(BaseModel):
    x_ratio: float = Field(ge=0, le=1)
    max_payload: float = Field(gt=0)


class AccelerationProfile(BaseModel):
    longitudinal_g: float = Field(ge=0, default=0.8)
    transverse_g: float = Field(ge=0, default=0.5)
    vertical_g: float = Field(ge=0, le=1, default=0.2)

class Container(BaseModel):
    id: str
    name: str = ""
    inner_length: float = Field(gt=0)
    inner_width: float = Field(gt=0)
    inner_height: float = Field(gt=0)
    max_payload: float = Field(gt=0)
    door_width: Optional[float] = None
    door_height: Optional[float] = None
    loading_accesses: list[LoadingAccess] = Field(default_factory=list)
    quantity: int = Field(ge=1, default=1)
    equipment_profile: EquipmentProfile = "generic"
    use_cost: Optional[float] = Field(default=None, ge=0)
    cog_limits: Optional[CogLimits] = None
    load_distribution_curve: list[LoadDistributionPoint] = Field(default_factory=list)
    max_floor_load_kg_m2: Optional[float] = Field(default=None, gt=0)
    acceleration_profile: Optional[AccelerationProfile] = None
    default_friction_coefficient: Optional[float] = Field(default=None, ge=0, le=2)
    restraint_mode: RestraintMode = "unverified"
    longitudinal_restraint_capacity_kn: Optional[float] = Field(default=None, ge=0)
    transverse_restraint_capacity_kn: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_distribution_curve(self):
        ratios = [point.x_ratio for point in self.load_distribution_curve]
        if ratios != sorted(ratios) or len(set(ratios)) != len(ratios):
            raise ValueError("load_distribution_curve must have unique ascending x_ratio values")
        return self


class Placement(BaseModel):
    item_id: str
    pallet_id: Optional[str] = None
    customer_id: str = ""
    order_id: str = ""
    destination_id: str = ""
    stop_seq: int = 1
    x: float
    y: float
    z: float
    orientation: Orientation
    seq: int


class PalletInstance(BaseModel):
    id: str
    pallet_type_id: str
    x: float
    y: float
    z: float
    length: float
    width: float
    deck_height: float
    tare_weight: float
    stop_seq: int = Field(default=1, ge=1)
    orientation: Literal["LWH", "WLH"] = "LWH"


class LoadedContainer(BaseModel):
    id: str
    placements: list[Placement] = Field(default_factory=list)
    pallet_instances: list[PalletInstance] = Field(default_factory=list)
    volume_utilization: float = 0.0
    weight_utilization: float = 0.0
    industrial_metrics: dict[str, float] = Field(default_factory=dict)
    industrial_rejection_codes: list[str] = Field(default_factory=list)


class ContainerEvaluation(BaseModel):
    index: int
    id: str
    score: float = Field(ge=0, le=100)
    grade: str
    metrics: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class Evaluation(BaseModel):
    objective: str
    objective_requested: str = ""
    objective_resolved: str = ""
    strategy_profile: str = ""
    score: float = Field(ge=0, le=100)
    grade: str
    metrics: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    containers: list[ContainerEvaluation] = Field(default_factory=list)


class PerformanceMetrics(BaseModel):
    runtime_ms: float = Field(ge=0, default=0.0)
    stages_ms: dict[str, float] = Field(default_factory=dict)
    counters: dict[str, int] = Field(default_factory=dict)


class ConstraintViolation(BaseModel):
    code: str
    severity: Literal["warning", "error"] = "warning"
    message: str
    container_id: str = ""
    item_id: str = ""
    stop_seq: Optional[int] = None


class CostSummary(BaseModel):
    currency: str = "CNY"
    container_cost: float = 0.0
    pallet_handling_cost: float = 0.0
    total_cost: float = 0.0
    estimated: bool = False


class Solution(BaseModel):
    status: SolutionStatus = "feasible"
    containers: list[LoadedContainer] = Field(default_factory=list)
    unpacked: list[str] = Field(default_factory=list)
    evaluation: Optional[Evaluation] = None
    performance: Optional[PerformanceMetrics] = None
    alternatives: list["SolutionAlternative"] = Field(default_factory=list)
    violations: list[ConstraintViolation] = Field(default_factory=list)
    cost_summary: Optional[CostSummary] = None


class SolutionAlternative(BaseModel):
    rank: int = Field(ge=1)
    seed: int
    score: float = Field(ge=0, le=100)
    grade: str
    containers: list[LoadedContainer] = Field(default_factory=list)
    unpacked: list[str] = Field(default_factory=list)
    evaluation: Optional[Evaluation] = None
    status: SolutionStatus = "feasible"
    violations: list[ConstraintViolation] = Field(default_factory=list)
    cost_summary: Optional[CostSummary] = None



class AdvancedWeights(BaseModel):
    cost_efficiency: float = Field(ge=0, default=0.15)
    space_utilization: float = Field(ge=0, default=0.35)
    stability: float = Field(ge=0, default=0.25)
    palletization: float = Field(ge=0, default=0.0)
    balance: float = Field(ge=0, default=0.15)
    loading_position: float = Field(ge=0, default=0.10)

    @model_validator(mode="after")
    def require_some_weight(self):
        effective_cost = self.cost_efficiency if "cost_efficiency" in self.model_fields_set else 0.0
        if (
            effective_cost
            + self.space_utilization
            + self.stability
            + self.palletization
            + self.balance
            + self.loading_position
        ) <= 0:
            raise ValueError("at least one advanced weight must be positive")
        return self


class SolveRequest(BaseModel):
    items: list[Item] = Field(default_factory=list)
    pallets: list[Pallet] = Field(default_factory=list)
    containers: list[Container] = Field(default_factory=list)
    objective: Objective = "cost_efficiency"
    advanced_weights: Optional[AdvancedWeights] = None
    use_ga: bool = False  # True 时用遗传算法对放置顺序做全局优化（更慢，更优）
    ga_speed: GASpeed = "standard"
    candidate_count: int = Field(ge=1, le=8, default=3)
    validation_mode: ValidationMode = "standard"
    pallet_policy: PalletPolicy = "auto"
    cost_currency: str = Field(default="CNY", min_length=1, max_length=8)
