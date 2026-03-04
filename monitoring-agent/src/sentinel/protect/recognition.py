"""Entity recognition using LLaVA (vision_agent).

Phase 1: Structured prompts to vision_agent for feature extraction.
Phase 2 hooks: InsightFace face embeddings, VehicleNet ReID, PaddleOCR plates.
"""

import base64
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================
# LLaVA Prompts
# ============================================================

VEHICLE_PROMPT = """Analyze this security camera image for vehicles.

For each vehicle visible, provide:
1. Vehicle type: car, truck, van, SUV, motorcycle, bicycle, or other
2. Color: primary color, secondary color if two-tone
3. Make and model: if identifiable, with confidence (high/medium/low/unknown)
4. Approximate year range: if identifiable (e.g., "2015-2020")
5. Distinguishing features:
   - Bumper stickers (describe text/images)
   - Body damage (dents, scratches, rust - location and severity)
   - Custom modifications (roof rack, spoiler, tinted windows, custom wheels)
   - Aftermarket accessories (bike rack, cargo carrier, trailer hitch)
6. License plate:
   - Visibility: visible, partially_visible, not_visible
   - Text: exact characters if readable
   - State/region: if identifiable
7. Direction of travel: toward_camera, away_from_camera, left, right, stationary
8. Number of occupants visible through windows
9. Any unusual items on or around the vehicle

Camera location: {camera_location}
Time: {timestamp}

Return ONLY valid JSON in this exact format:
{
  "vehicles": [
    {
      "vehicle_type": "car",
      "color": {"primary": "silver", "secondary": null},
      "make_model": {"make": "Honda", "model": "Accord", "confidence": "medium", "year_range": "2018-2022"},
      "distinguishing_features": [
        {"type": "damage", "location": "rear_bumper", "description": "minor dent"},
        {"type": "sticker", "description": "university parking permit"}
      ],
      "plate": {"visibility": "visible", "text": "ABC1234", "state": "CA"},
      "direction": "toward_camera",
      "occupants": 1,
      "unusual_items": []
    }
  ],
  "image_quality": "good",
  "lighting": "daylight"
}"""

PERSON_PROMPT = """Analyze this security camera image for persons.

For each person visible, provide:
1. Build:
   - Height estimate: short, average, tall
   - Body type: slim, average, heavy
   - Apparent age range: e.g., "20s", "30-40", "50s"
   - Gender presentation: male, female, ambiguous
2. Clothing:
   - Upper body: type (jacket/shirt/hoodie/coat), color, patterns, visible logos
   - Lower body: type (jeans/shorts/skirt/pants), color
   - Footwear: type (sneakers/boots/sandals/dress_shoes), color
   - Headwear: type (baseball_cap/beanie/hood/none), color
3. Accessories:
   - Bag: backpack, messenger, handbag, shopping_bag, none
   - Glasses: prescription, sunglasses, none
   - Visible electronics: phone, earbuds, camera
4. Distinguishing features:
   - Visible tattoos: location and brief description
   - Hair: color, style (short/medium/long/bald/ponytail/etc)
   - Facial hair: none, stubble, goatee, full_beard, mustache
   - Scars or notable marks
5. Behavior:
   - Posture: standing, walking, running, crouching, sitting
   - Direction: toward_property, away_from_property, along_street, stationary
   - Attention focus: looking_at_door, looking_at_windows, looking_at_camera, looking_away
   - Carrying: package, tools, nothing, other (describe)
   - Behavior notes: any unusual activity
6. Face visibility: visible, partially_visible, not_visible
7. Face angle: frontal, three_quarter, profile, back_of_head

Camera location: {camera_location}
Time: {timestamp}

Return ONLY valid JSON in this exact format:
{
  "persons": [
    {
      "build": {"height": "average", "body_type": "slim", "age_range": "30s", "gender": "male"},
      "clothing": {
        "upper": {"type": "hoodie", "color": "black", "patterns": null, "logos": null},
        "lower": {"type": "jeans", "color": "blue"},
        "footwear": {"type": "sneakers", "color": "white"},
        "headwear": {"type": "hood_up", "color": "black"}
      },
      "accessories": {"bag": "backpack", "glasses": "none", "electronics": []},
      "distinguishing_features": [
        {"type": "tattoo", "location": "left_forearm", "description": "sleeve tattoo"},
        {"type": "hair", "description": "short brown hair"},
        {"type": "facial_hair", "description": "full beard"}
      ],
      "behavior": {
        "posture": "walking",
        "direction": "toward_property",
        "attention_focus": "looking_at_door",
        "carrying": "package",
        "suspicion_indicators": [],
        "notes": ""
      },
      "face": {"visibility": "partially_visible", "angle": "three_quarter"}
    }
  ],
  "image_quality": "good",
  "lighting": "daylight"
}"""

FACE_PROMPT = """Analyze the face in this security camera image.

Describe:
1. Approximate age range (e.g., "20-25", "30-35", "40-50")
2. Gender presentation: male, female, ambiguous
3. Skin tone: light, medium, dark
4. Face shape: oval, round, square, heart, oblong
5. Hair:
   - Color: black, brown, blonde, red, gray, white, or dyed-{color}
   - Style: short, medium, long, bald, receding, ponytail, bun
   - Facial hair: none, stubble, goatee, full_beard, mustache
6. Distinctive facial features:
   - Scars, moles, birthmarks (location + description)
   - Glasses: none, prescription, sunglasses (frame style if visible)
   - Piercings: location
7. Expression: neutral, smiling, alert, agitated, fearful
8. Face angle: frontal, three_quarter, profile, back_of_head
9. Image quality for face recognition: excellent, good, fair, poor

Return ONLY valid JSON:
{
  "age_range": "30-35",
  "gender": "male",
  "skin_tone": "medium",
  "face_shape": "oval",
  "hair": {"color": "brown", "style": "short", "facial_hair": "stubble"},
  "distinctive_features": [
    {"type": "scar", "location": "left_cheek", "description": "small horizontal scar"}
  ],
  "glasses": "none",
  "piercings": [],
  "expression": "neutral",
  "face_angle": "three_quarter",
  "image_quality": "good"
}"""

GENERAL_PROMPT = """Analyze this security camera image from {camera_location} at {timestamp}.

Identify all entities and activity:
1. People: count, general description, activity
2. Vehicles: count, types, colors
3. Animals: species, count
4. Packages: count, size
5. Anomalies: anything unusual (unexpected objects, unusual positions, changes from normal)
6. Overall scene description

Return ONLY valid JSON:
{
  "people": [{"description": "...", "activity": "..."}],
  "vehicles": [{"type": "...", "color": "...", "plate": "..."}],
  "animals": [{"species": "...", "count": 1}],
  "packages": [{"size": "small", "location": "front_door"}],
  "anomalies": [{"description": "...", "severity": "low"}],
  "scene_summary": "...",
  "image_quality": "good"
}"""


def _parse_vision_json(raw_output: str) -> Optional[Dict]:
    """Extract and parse JSON from vision_agent output."""
    if not raw_output:
        return None

    # Try direct parse first
    try:
        return json.loads(raw_output.strip())
    except json.JSONDecodeError:
        pass

    # Extract JSON block from markdown code fences
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_output, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Find first { ... } block
    brace_match = re.search(r"\{.*\}", raw_output, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning(f"Could not parse vision output as JSON: {raw_output[:200]}")
    return None


def format_vehicle_prompt(camera_location: str, timestamp: str) -> str:
    return VEHICLE_PROMPT.format(camera_location=camera_location, timestamp=timestamp)


def format_person_prompt(camera_location: str, timestamp: str) -> str:
    return PERSON_PROMPT.format(camera_location=camera_location, timestamp=timestamp)


def format_face_prompt() -> str:
    return FACE_PROMPT


def format_general_prompt(camera_location: str, timestamp: str) -> str:
    return GENERAL_PROMPT.format(camera_location=camera_location, timestamp=timestamp)


def extract_vehicle_features(vision_output: str) -> List[Dict]:
    """Parse vehicle features from vision_agent output."""
    data = _parse_vision_json(vision_output)
    if not data:
        return []
    return data.get("vehicles", [])


def extract_person_features(vision_output: str) -> List[Dict]:
    """Parse person features from vision_agent output."""
    data = _parse_vision_json(vision_output)
    if not data:
        return []
    return data.get("persons", [])


def extract_face_features(vision_output: str) -> Optional[Dict]:
    """Parse face features from vision_agent output."""
    return _parse_vision_json(vision_output)


def extract_general_classifications(vision_output: str) -> Dict:
    """Parse general scene classifications from vision_agent output."""
    data = _parse_vision_json(vision_output)
    if not data:
        return {"people": [], "vehicles": [], "animals": [], "packages": [], "anomalies": []}
    return data


def compute_behavior_suspicion_score(behavior: Dict) -> float:
    """Score suspicious behavior indicators (0.0-1.0)."""
    score = 0.0

    suspicious = {
        "crouching": 0.3,
        "running": 0.2,
        "looking_at_windows": 0.4,
        "looking_at_doors": 0.3,
        "looking_at_locks": 0.4,
        "face_covered": 0.4,
        "pacing": 0.2,
        "lingering": 0.3,
        "toward_rear": 0.3,
        "testing_handle": 0.7,
        "forcing_door": 0.9,
        "breaking_window": 0.9,
    }

    normal = {
        "walking_past": -0.2,
        "delivering_package": -0.3,
        "walking_dog": -0.3,
        "jogging": -0.2,
        "pushing_stroller": -0.3,
    }

    attention = behavior.get("attention_focus", "")
    posture = behavior.get("posture", "")
    direction = behavior.get("direction", "")
    carrying = behavior.get("carrying", "")
    notes = behavior.get("notes", "")

    combined = f"{attention} {posture} {direction} {carrying} {notes}".lower()

    for indicator, weight in suspicious.items():
        if indicator in combined:
            score += weight

    for indicator, weight in normal.items():
        if indicator in combined:
            score += weight

    return max(0.0, min(1.0, score))


def generate_text_signature(face_desc: Dict) -> str:
    """Create a text signature for loose face matching (Phase 1)."""
    parts = [
        face_desc.get("gender", "unknown"),
        face_desc.get("age_range", "unknown"),
        face_desc.get("skin_tone", "unknown"),
        face_desc.get("face_shape", "unknown"),
        face_desc.get("hair", {}).get("color", "unknown"),
        face_desc.get("hair", {}).get("style", "unknown"),
        face_desc.get("hair", {}).get("facial_hair", "none"),
        face_desc.get("glasses", "none"),
    ]
    return "|".join(str(p).lower() for p in parts)


def image_to_base64(image_bytes: bytes) -> str:
    """Convert image bytes to base64 data URL."""
    return base64.b64encode(image_bytes).decode("utf-8")
