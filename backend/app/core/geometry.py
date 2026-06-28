"""底层几何运算：朝向 → 实际占用尺寸、轴对齐包围盒(AABB)的越界 / 重叠判定。

纯函数，无任何框架依赖，便于单元测试。
约定坐标系见 CLAUDE.md 第 5 节：x=长, y=宽, z=高(向上)。

Box 用一个 6 元组表示：(x, y, z, dx, dy, dz)
  其中 (x,y,z) 为最小角坐标，(dx,dy,dz) 为沿三个坐标轴的实际边长。
  占用区间为 [x, x+dx] × [y, y+dy] × [z, z+dz]。
"""
from __future__ import annotations

Box = tuple[float, float, float, float, float, float]

# 每种朝向把原始 (length, width, height) 重排成 (沿x, 沿y, 沿z) 的边长。
_ORIENTATION_MAP: dict[str, tuple[int, int, int]] = {
    # 三元组是 (length,width,height) 的下标，0=length 1=width 2=height
    "LWH": (0, 1, 2),
    "WLH": (1, 0, 2),
    "LHW": (0, 2, 1),
    "HWL": (2, 1, 0),
    "WHL": (1, 2, 0),
    "HLW": (2, 0, 1),
}


def oriented_dims(
    length: float, width: float, height: float, orientation: str
) -> tuple[float, float, float]:
    """把原始尺寸按朝向重排为 (dx, dy, dz)。"""
    try:
        ix, iy, iz = _ORIENTATION_MAP[orientation]
    except KeyError as exc:  # pragma: no cover - 防御性
        raise ValueError(f"未知朝向: {orientation!r}") from exc
    dims = (length, width, height)
    return dims[ix], dims[iy], dims[iz]


def boxes_overlap(a: Box, b: Box, eps: float = 1e-6) -> bool:
    """两个 AABB 是否在三个轴上都有正重叠（仅接触面不算重叠）。"""
    ax, ay, az, adx, ady, adz = a
    bx, by, bz, bdx, bdy, bdz = b
    # 任一轴上分离即不重叠。用 eps 容忍浮点误差，使共面接触判为不重叠。
    if ax + adx <= bx + eps or bx + bdx <= ax + eps:
        return False
    if ay + ady <= by + eps or by + bdy <= ay + eps:
        return False
    if az + adz <= bz + eps or bz + bdz <= az + eps:
        return False
    return True


def box_within(box: Box, inner_length: float, inner_width: float, inner_height: float,
               eps: float = 1e-6) -> bool:
    """box 是否完整落在容器内部尺寸之内（且坐标非负）。"""
    x, y, z, dx, dy, dz = box
    if x < -eps or y < -eps or z < -eps:
        return False
    return (
        x + dx <= inner_length + eps
        and y + dy <= inner_width + eps
        and z + dz <= inner_height + eps
    )


def box_volume(box: Box) -> float:
    _, _, _, dx, dy, dz = box
    return dx * dy * dz
