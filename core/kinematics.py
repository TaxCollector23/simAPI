"""URDF forward kinematics helpers for deterministic robotics validation.

The implementation supports serial joint chains containing revolute,
continuous, prismatic, and fixed joints. URDF joint origins are applied before
the joint motion, matching the URDF transform convention:

    T_parent_child = T_origin * T_joint_motion
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass

import numpy as np

SUPPORTED_JOINT_TYPES = {"fixed", "revolute", "continuous", "prismatic"}


@dataclass(frozen=True)
class URDFJoint:
    """One parsed URDF joint and its fixed origin transform."""

    name: str
    joint_type: str
    parent_link: str
    child_link: str
    origin_xyz: tuple[float, float, float]
    origin_rpy: tuple[float, float, float]
    axis: tuple[float, float, float]


@dataclass(frozen=True)
class URDFGeometry:
    """A selected base-to-tip chain from a URDF robot description."""

    robot_name: str
    base_link: str
    tip_link: str
    joints: tuple[URDFJoint, ...]

    @property
    def active_joints(self) -> tuple[URDFJoint, ...]:
        return tuple(joint for joint in self.joints if joint.joint_type != "fixed")


def _vector(text: str | None, default: tuple[float, float, float], *, field: str) -> tuple[float, float, float]:
    if text is None or not text.strip():
        return default
    try:
        parts = tuple(float(part) for part in text.split())
    except ValueError as exc:
        raise ValueError(f"URDF {field} must contain three finite numbers") from exc
    if len(parts) != 3 or not all(math.isfinite(part) for part in parts):
        raise ValueError(f"URDF {field} must contain three finite numbers")
    return parts  # type: ignore[return-value]


def parse_urdf_geometry(
    urdf_xml: str,
    *,
    base_link: str | None = None,
    tip_link: str | None = None,
) -> URDFGeometry:
    """Parse a URDF and resolve one base-to-tip chain.

    If base/tip links are omitted, the URDF must have a unique root and a
    unique leaf. Branched descriptions can select the desired path explicitly.
    """
    if not isinstance(urdf_xml, str) or not urdf_xml.strip():
        raise ValueError("urdf_xml must be a non-empty XML string")
    try:
        root = ET.fromstring(urdf_xml)
    except ET.ParseError as exc:
        raise ValueError(f"Could not parse URDF XML: {exc}") from exc
    if root.tag != "robot":
        raise ValueError("URDF root element must be <robot>")

    links = {element.get("name", "").strip() for element in root.findall("link")}
    if "" in links or not links:
        raise ValueError("URDF must declare named links")
    joints: list[URDFJoint] = []
    seen_joint_names: set[str] = set()
    for element in root.findall("joint"):
        name = (element.get("name") or "").strip()
        kind = (element.get("type") or "").strip().lower()
        parent = element.find("parent")
        child = element.find("child")
        parent_link = (parent.get("link") if parent is not None else "") or ""
        child_link = (child.get("link") if child is not None else "") or ""
        if not name or name in seen_joint_names:
            raise ValueError("URDF joints must have unique, non-empty names")
        if kind not in SUPPORTED_JOINT_TYPES:
            raise ValueError(f"URDF joint '{name}' has unsupported type '{kind}'")
        if parent_link not in links or child_link not in links:
            raise ValueError(f"URDF joint '{name}' references an undeclared parent or child link")
        seen_joint_names.add(name)
        origin = element.find("origin")
        xyz = _vector(origin.get("xyz") if origin is not None else None, (0.0, 0.0, 0.0), field=f"{name}.origin.xyz")
        rpy = _vector(origin.get("rpy") if origin is not None else None, (0.0, 0.0, 0.0), field=f"{name}.origin.rpy")
        axis_element = element.find("axis")
        axis = _vector(axis_element.get("xyz") if axis_element is not None else None, (1.0, 0.0, 0.0), field=f"{name}.axis")
        if kind != "fixed":
            norm = math.sqrt(sum(component * component for component in axis))
            if norm <= 0:
                raise ValueError(f"URDF joint '{name}' has a zero-length axis")
            axis = tuple(component / norm for component in axis)  # type: ignore[assignment]
        joints.append(URDFJoint(name, kind, parent_link, child_link, xyz, rpy, axis))

    children = {joint.child_link for joint in joints}
    parents = {joint.parent_link for joint in joints}
    roots = sorted(links - children)
    leaves = sorted(links - parents)
    if base_link is None:
        if len(roots) != 1:
            raise ValueError("URDF must have one root link or specify base_link")
        base_link = roots[0]
    if tip_link is None:
        if len(leaves) != 1:
            raise ValueError("URDF must have one tip link or specify tip_link")
        tip_link = leaves[0]
    if base_link not in links or tip_link not in links:
        raise ValueError("Selected URDF base_link or tip_link is not declared")

    adjacency: dict[str, list[URDFJoint]] = {}
    for joint in joints:
        adjacency.setdefault(joint.parent_link, []).append(joint)
    queue = deque([(base_link, tuple(), frozenset({base_link}))])
    paths: list[tuple[URDFJoint, ...]] = []
    while queue:
        link, path, visited_on_path = queue.popleft()
        if link == tip_link:
            paths.append(path)
            continue
        for joint in adjacency.get(link, []):
            if joint.child_link in visited_on_path:
                continue
            queue.append((joint.child_link, path + (joint,), visited_on_path | {joint.child_link}))
    if not paths:
        raise ValueError(f"No URDF joint chain connects '{base_link}' to '{tip_link}'")
    if len(paths) != 1:
        raise ValueError(f"More than one URDF joint chain connects '{base_link}' to '{tip_link}'")
    return URDFGeometry(root.get("name", "robot"), base_link, tip_link, paths[0])


def joint_signal_name(joint_name: str) -> str:
    """Map a URDF joint name using SimAPI's stable joint signal convention."""
    stem = re.sub(r"[^a-z0-9_]+", "_", joint_name.strip().lower()).strip("_")
    stem = re.sub(r"_+", "_", stem)
    if not stem:
        raise ValueError("URDF joint name cannot be normalized to a signal")
    if not stem.startswith("joint"):
        stem = f"joint_{stem}"
    return f"{stem}_position"


def _rotation_rpy(roll: float, pitch: float, yaw: float) -> np.ndarray:
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    # URDF fixed-axis roll, pitch, yaw: Rz(yaw) @ Ry(pitch) @ Rx(roll).
    return np.array(
        [
            [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp * sr, cp * cr],
        ],
        dtype=float,
    )


def _origin_transform(joint: URDFJoint) -> np.ndarray:
    transform = np.eye(4, dtype=float)
    transform[:3, :3] = _rotation_rpy(*joint.origin_rpy)
    transform[:3, 3] = joint.origin_xyz
    return transform


def _axis_rotation(axis: tuple[float, float, float], angle: float) -> np.ndarray:
    x, y, z = axis
    c, s, one_minus_c = math.cos(angle), math.sin(angle), 1.0 - math.cos(angle)
    return np.array(
        [
            [c + x * x * one_minus_c, x * y * one_minus_c - z * s, x * z * one_minus_c + y * s],
            [y * x * one_minus_c + z * s, c + y * y * one_minus_c, y * z * one_minus_c - x * s],
            [z * x * one_minus_c - y * s, z * y * one_minus_c + x * s, c + z * z * one_minus_c],
        ],
        dtype=float,
    )


def forward_kinematics(
    geometry: URDFGeometry,
    joint_values: dict[str, float],
    joint_signal_map: dict[str, str] | None = None,
) -> tuple[float, float, float]:
    """Return the URDF tip position in the base frame for one sample."""
    signal_map = joint_signal_map or {}
    transform = np.eye(4, dtype=float)
    for joint in geometry.joints:
        transform = transform @ _origin_transform(joint)
        if joint.joint_type == "fixed":
            continue
        signal = signal_map.get(joint.name, joint_signal_name(joint.name))
        if signal not in joint_values:
            raise ValueError(f"Missing position for URDF joint '{joint.name}' (signal '{signal}')")
        value = float(joint_values[signal])
        if not math.isfinite(value):
            raise ValueError(f"Position for URDF joint '{joint.name}' must be finite")
        motion = np.eye(4, dtype=float)
        if joint.joint_type in {"revolute", "continuous"}:
            motion[:3, :3] = _axis_rotation(joint.axis, value)
        else:  # prismatic
            motion[:3, 3] = np.asarray(joint.axis, dtype=float) * value
        transform = transform @ motion
    position = transform[:3, 3]
    return float(position[0]), float(position[1]), float(position[2])
