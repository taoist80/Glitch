"""Cross-camera entity tracking.

Reconstructs entity movement paths across cameras using temporal correlation
and camera topology (adjacency graph with typical transition times).
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default camera topology - can be overridden via protect_configure_camera_topology tool
_camera_topology: Dict[str, Dict] = {}


def set_topology(topology: Dict[str, Dict]) -> None:
    """Set camera adjacency topology."""
    global _camera_topology
    _camera_topology = topology
    logger.info(f"Camera topology updated: {len(topology)} cameras configured")


def get_topology() -> Dict[str, Dict]:
    """Get current camera topology."""
    return _camera_topology.copy()


def are_cameras_adjacent(camera_a: str, camera_b: str) -> bool:
    """Check if two cameras are adjacent in the topology."""
    if camera_a in _camera_topology:
        return camera_b in _camera_topology[camera_a].get("adjacent", [])
    return False


def get_expected_transition_seconds(camera_a: str, camera_b: str) -> Optional[float]:
    """Get expected transition time between two cameras in seconds."""
    if camera_a in _camera_topology:
        return _camera_topology[camera_a].get("typical_transition_seconds", {}).get(camera_b)
    return None


def get_camera_zone(camera_id: str) -> Dict[str, Any]:
    """Get zone information for a camera."""
    if camera_id in _camera_topology:
        return {
            "name": _camera_topology[camera_id].get("zone", camera_id),
            "restricted_hours": _camera_topology[camera_id].get("restricted_hours"),
        }
    return {"name": camera_id, "restricted_hours": None}


async def build_movement_path(
    sightings: List[Dict],
) -> Dict[str, Any]:
    """Build a movement path from a list of entity sightings."""
    if not sightings:
        return {"path": [], "total_waypoints": 0, "tracking_quality": "no_data"}

    sorted_sightings = sorted(sightings, key=lambda s: s["timestamp"])

    path = []
    gaps = []
    dwell_times: Dict[str, Dict] = {}

    for i, sighting in enumerate(sorted_sightings):
        cam = sighting["camera_id"]
        ts = sighting["timestamp"]

        if cam not in dwell_times:
            dwell_times[cam] = {
                "first_seen": ts,
                "last_seen": ts,
                "visits": 0,
            }
        dwell_times[cam]["last_seen"] = ts
        dwell_times[cam]["visits"] += 1

        waypoint: Dict[str, Any] = {
            "sequence": i + 1,
            "camera_id": cam,
            "timestamp": ts.isoformat() if isinstance(ts, datetime) else str(ts),
            "direction": sighting.get("features_snapshot", {}).get("direction"),
            "posture": sighting.get("features_snapshot", {}).get("posture"),
            "anomaly_score": sighting.get("anomaly_score", 0),
            "duration_at_location": None,
            "transition_from_previous": None,
        }

        if i > 0:
            prev = sorted_sightings[i - 1]
            prev_ts = prev["timestamp"]
            curr_ts = ts

            if isinstance(prev_ts, datetime) and isinstance(curr_ts, datetime):
                transition_seconds = (curr_ts - prev_ts).total_seconds()
            else:
                transition_seconds = 0

            expected = get_expected_transition_seconds(prev["camera_id"], cam)
            is_adjacent = are_cameras_adjacent(prev["camera_id"], cam)

            waypoint["transition_from_previous"] = {
                "seconds": transition_seconds,
                "from_camera": prev["camera_id"],
                "expected_seconds": expected,
                "is_adjacent": is_adjacent,
            }

            # Detect gaps
            if expected and transition_seconds > expected * 5:
                gaps.append({
                    "after_waypoint": i,
                    "gap_seconds": transition_seconds,
                    "from_camera": prev["camera_id"],
                    "to_camera": cam,
                    "possible_explanations": _infer_gap_explanation(
                        prev["camera_id"], cam, transition_seconds
                    ),
                })

        path.append(waypoint)

    # Calculate dwell times
    for cam, dt in dwell_times.items():
        first = dt["first_seen"]
        last = dt["last_seen"]
        if isinstance(first, datetime) and isinstance(last, datetime):
            dt["total_dwell_seconds"] = (last - first).total_seconds()
        else:
            dt["total_dwell_seconds"] = 0

    # Total duration
    first_ts = sorted_sightings[0]["timestamp"]
    last_ts = sorted_sightings[-1]["timestamp"]
    if isinstance(first_ts, datetime) and isinstance(last_ts, datetime):
        total_duration = (last_ts - first_ts).total_seconds()
    else:
        total_duration = 0

    cameras_visited = list(dict.fromkeys(s["camera_id"] for s in sorted_sightings))

    return {
        "path": path,
        "total_waypoints": len(path),
        "gaps": gaps,
        "dwell_times": dwell_times,
        "tracking_quality": _assess_tracking_quality(path, gaps),
        "total_tracking_duration": total_duration,
        "cameras_visited": cameras_visited,
        "entry_point": cameras_visited[0] if cameras_visited else None,
        "exit_point": cameras_visited[-1] if cameras_visited else None,
    }


def _infer_gap_explanation(
    from_cam: str,
    to_cam: str,
    gap_seconds: float,
) -> List[str]:
    explanations = []

    if not are_cameras_adjacent(from_cam, to_cam):
        explanations.append("Cameras not adjacent - entity may have used unmonitored path")

    if gap_seconds > 600:
        explanations.append("Long gap suggests entity stopped in unmonitored area")

    if gap_seconds > 3600:
        explanations.append("Very long gap - entity may have left and returned")

    if not explanations:
        explanations.append("Transition time longer than expected")

    return explanations


def _assess_tracking_quality(path: List[Dict], gaps: List[Dict]) -> str:
    if not path:
        return "no_data"
    if not gaps and len(path) >= 3:
        return "good"
    if len(gaps) <= 1 and len(path) >= 2:
        return "moderate"
    return "poor"


def format_path_summary(movement_path: Dict) -> str:
    """Format movement path as human-readable text."""
    lines = []
    lines.append(
        f"Entity Movement Path ({movement_path['total_waypoints']} waypoints)"
    )
    duration = movement_path.get("total_tracking_duration", 0)
    lines.append(f"Duration: {duration/60:.1f} minutes")
    cameras = ", ".join(movement_path.get("cameras_visited", []))
    lines.append(f"Cameras: {cameras}")
    lines.append(f"Quality: {movement_path['tracking_quality']}")
    lines.append("")

    for wp in movement_path.get("path", []):
        ts = wp["timestamp"]
        cam = wp["camera_id"]
        direction = wp.get("direction", "")

        transition = wp.get("transition_from_previous")
        if transition:
            gap = transition["seconds"]
            adj = "adjacent" if transition.get("is_adjacent") else "NON-ADJACENT"
            lines.append(f"  | ({gap:.0f}s, {adj})")

        anomaly = wp.get("anomaly_score", 0)
        anomaly_flag = " [!]" if anomaly > 0.5 else ""
        dir_str = f" -> {direction}" if direction else ""
        lines.append(f"  [{ts}] {cam}{dir_str}{anomaly_flag}")

    if movement_path.get("gaps"):
        lines.append("\nTracking Gaps:")
        for gap in movement_path["gaps"]:
            lines.append(
                f"  - {gap['from_camera']} -> {gap['to_camera']}: "
                f"{gap['gap_seconds']/60:.1f} min gap"
            )
            for exp in gap["possible_explanations"]:
                lines.append(f"    Possible: {exp}")

    return "\n".join(lines)
