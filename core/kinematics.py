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
MAX_URDF_XML_BYTES = 2 * 1024 * 1024
MAX_URDF_LINKS = 10_000
MAX_URDF_JOINTS = 10_000


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
    if len(urdf_xml.encode("utf-8")) > MAX_URDF_XML_BYTES:
        raise ValueError(f"urdf_xml exceeds the {MAX_URDF_XML_BYTES}-byte parser limit")
    if "<!DOCTYPE" in urdf_xml.upper() or "<!ENTITY" in urdf_xml.upper():
        raise ValueError("URDF DTD and entity declarations are not supported")
    try:
        root = ET.fromstring(urdf_xml)
    except ET.ParseError as exc:
        raise ValueError(f"Could not parse URDF XML: {exc}") from exc
    if root.tag != "robot":
        raise ValueError("URDF root element must be <robot>")

    link_names = [element.get("name", "").strip() for element in root.findall("link")]
    links = set(link_names)
    if "" in links or not links:
        raise ValueError("URDF must declare named links")
    if len(link_names) != len(links):
        raise ValueError("URDF link names must be unique")
    if len(links) > MAX_URDF_LINKS:
        raise ValueError(f"URDF exceeds the {MAX_URDF_LINKS}-link parser limit")
    joints: list[URDFJoint] = []
    seen_joint_names: set[str] = set()
    seen_child_links: set[str] = set()
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
        if child_link in seen_child_links:
            raise ValueError(
                f"URDF link '{child_link}' has more than one parent joint; links must form a tree"
            )
        if len(joints) >= MAX_URDF_JOINTS:
            raise ValueError(f"URDF exceeds the {MAX_URDF_JOINTS}-joint parser limit")
        seen_joint_names.add(name)
        seen_child_links.add(child_link)
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
            if len(paths) > 1:
                raise ValueError(f"More than one URDF joint chain connects '{base_link}' to '{tip_link}'")
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


def normalize_joint_name(joint_name: str) -> str:
    """Return the canonical signal stem for a ROS or URDF joint name."""
    stem = re.sub(r"[^a-z0-9_]+", "_", joint_name.strip().lower()).strip("_")
    stem = re.sub(r"_+", "_", stem)
    if not stem:
        raise ValueError("Joint name cannot be normalized to a signal")

    # ROS commonly calls numbered joints ``joint1`` while other sources use
    # ``joint_1`` or ``joint-1``. Give these equivalent spellings one signal
    # name so imported JointState rows can be matched to URDF joints.
    numeric = re.fullmatch(r"(?:joint_?)?(\d+)", stem)
    if numeric:
        return f"joint_{int(numeric.group(1))}"
    return stem if stem.startswith("joint") else f"joint_{stem}"


def joint_signal_name(joint_name: str) -> str:
    """Map a URDF joint name using SimAPI's stable joint signal convention."""
    return f"{normalize_joint_name(joint_name)}_position"


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
    position = forward_kinematics_frames(geometry, joint_values, joint_signal_map)[geometry.tip_link][:3, 3]
    return float(position[0]), float(position[1]), float(position[2])


def forward_kinematics_frames(
    geometry: URDFGeometry,
    joint_values: dict[str, float],
    joint_signal_map: dict[str, str] | None = None,
) -> dict[str, np.ndarray]:
    """Return a 4x4 base-frame transform for every link in the chain.

    The tip position used by :func:`forward_kinematics` is simply
    ``frames[geometry.tip_link]``; exposing every link frame also enables
    geometry checks (workspace floor, capsule self-collision) that need to
    know where each link actually is.
    """
    signal_map = joint_signal_map or {}
    transform = np.eye(4, dtype=float)
    frames = {geometry.base_link: transform.copy()}
    for joint in geometry.joints:
        transform = transform @ _origin_transform(joint)
        if joint.joint_type == "fixed":
            frames[joint.child_link] = transform.copy()
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
        frames[joint.child_link] = transform.copy()
    return frames


# ---------------------------------------------------------------------------
# SO(3) quaternion helpers
# ---------------------------------------------------------------------------
# Quaternion layout throughout this module is the ROS convention (x, y, z, w).
# q and -q encode the same rotation, so before any numerical comparison of
# consecutive orientations the series must live in one hemisphere.


def _as_quaternion_array(quaternions) -> np.ndarray:
    array = np.asarray(quaternions, dtype=float)
    if array.ndim != 2 or array.shape[1] != 4:
        raise ValueError("quaternions must be an (N, 4) array in (x, y, z, w) order")
    if not np.isfinite(array).all():
        raise ValueError("quaternion components must be finite")
    norms = np.linalg.norm(array, axis=1)
    if np.any(norms <= 0.0) or not np.isfinite(norms).all():
        raise ValueError("quaternion components must form non-zero finite quaternions")
    return array


def align_quaternion_hemisphere(quaternions) -> np.ndarray:
    """Flip quaternion signs so consecutive orientations share one hemisphere.

    For every t > 0 with ``dot(q_t, q_{t-1}) < 0`` the sample is negated
    (``q -> -q``), which leaves the encoded rotation unchanged. This must
    happen before differentiating orientations, otherwise a harmless sign
    flip in a log file masquerades as an instantaneous 180-degree turn.
    """
    array = _as_quaternion_array(quaternions)
    aligned = array.copy()
    for index in range(1, len(aligned)):
        if float(aligned[index] @ aligned[index - 1]) < 0.0:
            aligned[index] = -aligned[index]
    return aligned


def _quaternion_multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product of two (4,) quaternions in (x, y, z, w) order."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array(
        [
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz,
        ],
        dtype=float,
    )


def _quaternion_conjugate(q: np.ndarray) -> np.ndarray:
    return np.array([-q[0], -q[1], -q[2], q[3]], dtype=float)


def quaternion_relative_rotation(q: np.ndarray, q_prev: np.ndarray) -> np.ndarray:
    """Relative rotation q * conj(q_prev) taking q_prev's frame to q's frame."""
    return _quaternion_multiply(q, _quaternion_conjugate(q_prev))


def geodesic_angular_velocity(quaternions, times) -> np.ndarray:
    """Angular speed (rad/s) between consecutive orientations, sign-flip safe.

    Hemisphere alignment is applied first, then the geodesic angle
    ``2 * atan2(||vec||, |w|)`` of each relative rotation is divided by the
    elapsed time. The first sample has no predecessor and is reported as 0.
    """
    aligned = align_quaternion_hemisphere(quaternions)
    stamps = np.asarray(times, dtype=float)
    if stamps.ndim != 1 or len(stamps) != len(aligned):
        raise ValueError("times must be a 1-D array with one timestamp per quaternion")
    if not np.isfinite(stamps).all():
        raise ValueError("timestamps must be finite")
    speeds = np.zeros(len(aligned), dtype=float)
    for index in range(1, len(aligned)):
        dt = stamps[index] - stamps[index - 1]
        if dt <= 0:
            raise ValueError("timestamps must be strictly increasing")
        relative = quaternion_relative_rotation(aligned[index], aligned[index - 1])
        angle = 2.0 * math.atan2(float(np.linalg.norm(relative[:3])), abs(float(relative[3])))
        speeds[index] = angle / dt
    return speeds


# ---------------------------------------------------------------------------
# Link geometry: workspace floor and capsule self-collision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LinkCapsule:
    """A capsule approximation of one link's collision geometry.

    URDF expresses collision primitives as cylinders; treating the cylinder
    as a capsule (half-spheres capping the tube) is the standard conservative
    approximation for clearance checking and is what MuJoCo-style pipelines
    import. ``length`` is the cylinder height along the link-frame z axis,
    ``origin_xyz``/``origin_rpy`` place the capsule in the link frame.
    """

    link_name: str
    radius: float
    length: float
    origin_xyz: tuple[float, float, float]
    origin_rpy: tuple[float, float, float]


def parse_link_capsules(urdf_xml: str) -> dict[str, LinkCapsule]:
    """Extract one collision capsule per link from a URDF string.

    Only ``<collision>`` elements with a ``<cylinder>`` (or ``<capsule>``)
    geometry are used; links without collision geometry are omitted. When a
    link declares several collision elements the first one wins, matching how
    single-collision exporters write manipulation-arm descriptions.
    """
    if not isinstance(urdf_xml, str) or not urdf_xml.strip():
        raise ValueError("urdf_xml must be a non-empty XML string")
    if len(urdf_xml.encode("utf-8")) > MAX_URDF_XML_BYTES:
        raise ValueError(f"urdf_xml exceeds the {MAX_URDF_XML_BYTES}-byte parser limit")
    if "<!DOCTYPE" in urdf_xml.upper() or "<!ENTITY" in urdf_xml.upper():
        raise ValueError("URDF DTD and entity declarations are not supported")
    try:
        root = ET.fromstring(urdf_xml)
    except ET.ParseError as exc:
        raise ValueError(f"Could not parse URDF XML: {exc}") from exc
    if root.tag != "robot":
        raise ValueError("URDF root element must be <robot>")

    capsules: dict[str, LinkCapsule] = {}
    for link in root.findall("link"):
        link_name = (link.get("name") or "").strip()
        if not link_name or link_name in capsules:
            continue
        for collision in link.findall("collision"):
            geometry = collision.find("geometry")
            if geometry is None:
                continue
            shape = geometry.find("cylinder")
            if shape is None:
                shape = geometry.find("capsule")
            if shape is None:
                continue
            try:
                radius = float(shape.get("radius", "nan"))
                length = float(shape.get("length", "nan"))
            except ValueError as exc:
                raise ValueError(
                    f"URDF collision for link '{link_name}' must declare numeric radius and length"
                ) from exc
            if not (math.isfinite(radius) and radius > 0) or not (math.isfinite(length) and length >= 0):
                raise ValueError(
                    f"URDF collision for link '{link_name}' needs a positive radius and a non-negative length"
                )
            origin = collision.find("origin")
            xyz = _vector(origin.get("xyz") if origin is not None else None, (0.0, 0.0, 0.0), field=f"{link_name}.collision.origin.xyz")
            rpy = _vector(origin.get("rpy") if origin is not None else None, (0.0, 0.0, 0.0), field=f"{link_name}.collision.origin.rpy")
            capsules[link_name] = LinkCapsule(link_name, radius, length, xyz, rpy)
            break
    return capsules


def _capsule_segment(capsule: LinkCapsule, link_transform: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """World-frame segment endpoints and radius for one link capsule."""
    local = np.eye(4, dtype=float)
    local[:3, :3] = _rotation_rpy(*capsule.origin_rpy)
    local[:3, 3] = capsule.origin_xyz
    frame = link_transform @ local
    half = 0.5 * capsule.length
    # The cylinder axis is the link-frame (post-origin) z axis.
    top = frame[:3, 3] + frame[:3, 2] * half
    bottom = frame[:3, 3] - frame[:3, 2] * half
    return top, bottom, capsule.radius


def _segment_distance(p1: np.ndarray, q1: np.ndarray, p2: np.ndarray, q2: np.ndarray) -> float:
    """Shortest distance between two 3-D segments (clamped endpoint cases)."""
    d1 = q1 - p1
    d2 = q2 - p2
    r = p1 - p2
    a = float(d1 @ d1)
    e = float(d2 @ d2)
    f = float(d2 @ r)
    if a <= 1e-12 and e <= 1e-12:
        return float(np.linalg.norm(p1 - p2))
    if a <= 1e-12:
        s = 0.0
        t = min(max(f / e, 0.0), 1.0)
    else:
        c = float(d1 @ r)
        if e <= 1e-12:
            t = 0.0
            s = min(max(-c / a, 0.0), 1.0)
        else:
            b = float(d1 @ d2)
            denominator = a * e - b * b
            s = min(max((b * f - c * e) / denominator, 0.0), 1.0) if denominator > 1e-12 else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t = 0.0
                s = min(max(-c / a, 0.0), 1.0)
            elif t > 1.0:
                t = 1.0
                s = min(max((b - c) / a, 0.0), 1.0)
    closest1 = p1 + d1 * s
    closest2 = p2 + d2 * t
    return float(np.linalg.norm(closest1 - closest2))


def check_workspace_floor(
    geometry: URDFGeometry,
    samples: list[dict[str, float]],
    min_workspace_z: float,
    joint_signal_map: dict[str, str] | None = None,
) -> dict:
    """Flag samples whose FK tip drops below the workspace floor.

    Returns ``{"violations": [...], "min_tip_z": float}`` where violations
    list the offending sample indices. A geometry that obeys every joint
    limit can still clip through the floor (or the robot's own torso) —
    joint limits alone are not a reachability guarantee.
    """
    if not math.isfinite(min_workspace_z):
        raise ValueError("min_workspace_z must be a finite height in meters")
    violations: list[int] = []
    min_tip_z = math.inf
    for index, sample in enumerate(samples):
        x, y, z = forward_kinematics(geometry, sample, joint_signal_map)
        min_tip_z = min(min_tip_z, z)
        if z < min_workspace_z:
            violations.append(index)
    return {"violations": violations, "min_tip_z": (math.inf if not samples else min_tip_z)}


def check_self_collision(
    geometry: URDFGeometry,
    capsules: dict[str, LinkCapsule],
    samples: list[dict[str, float]],
    min_self_collision_clearance_m: float,
    joint_signal_map: dict[str, str] | None = None,
) -> dict:
    """Flag samples where two non-adjacent link capsules come too close.

    Adjacent links (connected by a joint) always touch by construction and
    are excluded; every other capsule pair must keep at least
    ``min_self_collision_clearance_m`` of surface-to-surface distance.
    Returns ``{"violations": {index: [pair strings]}, "min_clearance_m": float}``.
    """
    if not math.isfinite(min_self_collision_clearance_m) or min_self_collision_clearance_m < 0:
        raise ValueError("min_self_collision_clearance_m must be finite and non-negative")
    usable = {name: capsule for name, capsule in capsules.items() if name in set(
        [geometry.base_link] + [joint.child_link for joint in geometry.joints]
    )}
    if len(usable) < 2:
        return {"violations": {}, "min_clearance_m": math.inf, "evaluated_pairs": 0}
    adjacent = {(joint.parent_link, joint.child_link) for joint in geometry.joints}
    names = sorted(usable)
    pairs = [
        (names[i], names[j])
        for i in range(len(names))
        for j in range(i + 1, len(names))
        if {names[i], names[j]} not in [set(pair) for pair in adjacent]
    ]
    violations: dict[int, list[str]] = {}
    min_clearance = math.inf
    for index, sample in enumerate(samples):
        frames = forward_kinematics_frames(geometry, sample, joint_signal_map)
        for first, second in pairs:
            top1, bottom1, radius1 = _capsule_segment(usable[first], frames[first])
            top2, bottom2, radius2 = _capsule_segment(usable[second], frames[second])
            gap = _segment_distance(top1, bottom1, top2, bottom2) - radius1 - radius2
            min_clearance = min(min_clearance, gap)
            if gap < min_self_collision_clearance_m:
                violations.setdefault(index, []).append(f"{first}|{second}")
    return {
        "violations": violations,
        "min_clearance_m": (math.inf if not samples else min_clearance),
        "evaluated_pairs": len(pairs),
    }
