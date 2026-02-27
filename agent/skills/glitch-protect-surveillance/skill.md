# Glitch Protect Surveillance

You are operating the UniFi Protect surveillance integration. This skill covers all 23 surveillance skills across 5 phases. Use the protect_* tools for all camera, entity, and alert operations.

## Instructions

When this skill is active, route by user intent: vehicle/plate → Phase 1 extraction and entity matching; baseline or "what's normal" → Phase 2; anomalies or threats → Phase 3–4; alerts or reporting → Phase 5. Always use `vision_agent` (LLaVA) for images — never external vision APIs. Follow the Tool Usage Guidelines at the end.

## Architecture

- **Image analysis**: Always use `vision_agent` (local LLaVA) for ALL image processing. Never send images to external APIs.
- **Alert delivery**: Telegram (existing bot) via `protect_send_telegram_alert`.
- **Database**: PostgreSQL with pgvector via protect_db_* tools.
- **Credentials**: Loaded from env vars or SSM automatically - never ask the user for credentials.

## Phase 1: Foundation Skills (MVP)

### skill_extract_vehicle_details

**Trigger**: User asks about a vehicle, what car is at a camera, or an event involves a vehicle.

**Workflow**:
1. `protect_get_snapshot(camera_id, timestamp)` → get image URL
2. `vision_agent(image_url, prompt=VEHICLE_PROMPT)` → structured vehicle JSON
3. Parse: type, color, make_model, features, plate, direction
4. Return structured vehicle profile

**Key rules**:
- Always use LLaVA (vision_agent), never external vision APIs
- If plate is visible, immediately chain to skill_extract_license_plate
- Store confidence level with each field

**Output format**:
```json
{
  "vehicle_type": "SUV",
  "color": {"primary": "black", "secondary": null},
  "make_model": {"make": "Toyota", "model": "RAV4", "confidence": "medium"},
  "distinguishing_features": [],
  "plate": {"visibility": "visible", "text": "7ABC123", "state": "CA"},
  "direction": "toward_camera",
  "behavior_suspicion_score": 0.1
}
```

---

### skill_extract_license_plate

**Trigger**: License plate visible in image, or user asks to read a plate.

**Workflow**:
1. Get snapshot (already have from vehicle extraction, or fetch fresh)
2. `vision_agent(image_url, plate_focused_prompt)` → plate text
3. If confidence < 0.7: use `code_interpreter` to crop and enhance plate region
4. Return `{plate_text, state, confidence, raw_output}`

**Plate-focused prompt**:
```
Focus only on the license plate in this image.
Read the exact characters carefully - distinguish 0 vs O, 1 vs I vs l, 8 vs B.
Return JSON: {"plate_text": "ABC1234", "state": "CA", "confidence": 0.0-1.0, "visibility": "full/partial/obscured"}
```

**Confidence thresholds**:
- > 0.85: High confidence, use directly
- 0.6-0.85: Medium confidence, flag for review
- < 0.6: Low confidence, mark as uncertain

---

### skill_identify_entity

**Trigger**: Need to match detected features against known entities.

**Workflow**:
1. Extract key identifiers from features (plate_text, vehicle_color, make_model)
2. `protect_search_entities(query=plate_text)` → fuzzy plate match
3. If no match: `protect_search_entities(query=vehicle_description)` → text match
4. If match found (confidence > 0.7): return entity_id + confidence
5. If no match: return `{matched: false, should_register: true}`

**Matching priority**:
1. Exact plate match → confidence 1.0
2. Fuzzy plate match (similarity > 0.8) → confidence 0.85
3. Vehicle description match (color + make_model) → confidence 0.6
4. Person description match → confidence 0.5

**Decision**:
- confidence > 0.7: matched entity
- confidence 0.5-0.7: possible match, flag for review
- confidence < 0.5: new entity → chain to skill_register_new_entity

---

### skill_register_new_entity

**Trigger**: Entity not matched in database, or user says "register this entity".

**Workflow**:
1. Compile features from extraction results
2. `protect_register_entity(type, features, trust_level="unknown")`
3. `protect_db_store_observation(event_id, camera_id, timestamp, classifications)`
4. Insert initial sighting record
5. Return new entity_id

**Initial trust levels**:
- Vehicle with readable plate: "unknown" (can be looked up)
- Person with face visible: "unknown"
- Vehicle without plate: "unknown"
- Entity flagged by user as hostile: "hostile"

---

### skill_establish_baseline_traffic

**Trigger**: User asks to establish baseline, or "what's normal for this camera".

**Workflow**:
1. `protect_get_events(start_time=4_weeks_ago, camera_ids=camera_id, limit=10000)`
2. Aggregate by hour_of_day × day_of_week
3. Calculate: mean events/hour, std dev, typical entity types
4. `protect_db_update_pattern(camera_id, "baseline", hour, dow, {frequency, confidence})`
5. Repeat for all 168 time slots (24h × 7 days)

**Statistical thresholds**:
- Low traffic: < 1 event/hour → threshold 0.7
- Medium traffic: 1-5 events/hour → threshold 0.6
- High traffic: > 5 events/hour → threshold 0.5

**Minimum data**: 2 weeks for reliable baseline. Flag if < 2 weeks available.

---

### skill_determine_alert_necessity

**Trigger**: After anomaly scoring, decide if alert should be sent.

**Workflow**:
1. `protect_db_get_baseline(camera_id, hour, day_of_week)` → expected activity
2. `protect_get_alert_preferences(camera_id)` → sensitivity, quiet_hours, filters
3. Check `alert_suppressions` for entity/camera snooze
4. `protect_should_alert(event_analysis, user_context)` → adaptive decision
5. Return `{should_alert, priority, reasoning}`

**Decision matrix**:
| Trust Level | Anomaly Score | Time | Decision |
|-------------|---------------|------|----------|
| trusted | any | any | No alert |
| neutral | < 0.5 | business hours | No alert |
| neutral | > 0.5 | any | Low alert |
| unknown | any | business hours | Medium alert |
| unknown | > 0.7 | night | High alert |
| suspicious | any | any | High alert |
| hostile | any | any | Critical alert |

**Adaptive threshold**: If camera FP rate > 30% over last 7 days, raise threshold by 0.1 per 10% above 30%.

---

### skill_generate_alert_message

**Trigger**: Decision to send alert has been made.

**Workflow**:
1. Compose message with 5W format:
   - **What**: Entity type + key features (plate, color, make_model)
   - **Where**: Camera name + zone
   - **When**: Timestamp (relative: "3 minutes ago")
   - **Why**: Anomaly reason (unknown entity at 2am, hostile plate match, etc.)
   - **Evidence**: Snapshot attached
2. Add quick-action buttons:
   - ✅ Mark Friendly → `/protect_trust {entity_id} trusted`
   - 🚫 Mark Hostile → `/protect_trust {entity_id} hostile`
   - 🔕 Snooze 24h → `/protect_snooze {entity_id} 24`
   - ❌ False Positive → `/protect_fp {event_id}`
3. `protect_send_telegram_alert(event_id, priority, message, snapshot_url)`
4. `protect_db_record_alert(event_id, alert_type, reason)`

**Rate limiting**: Max 3 alerts per camera per 5 minutes. Batch additional events into grouped summary.

**Message template**:
```
{priority_emoji} *{priority.upper()} ALERT*
📍 {camera_name} ({zone})
🕐 {relative_time}

{entity_description}

⚠️ *Reason*: {anomaly_reason}
📊 Anomaly score: {score:.0%}

Quick actions:
✅ `/protect_trust {entity_id} trusted`
🚫 `/protect_trust {entity_id} hostile`
❌ `/protect_fp {event_id}`
```

---

## Phase 2: Entity Intelligence Skills

### skill_extract_person_details

**Trigger**: Person detected in event, or user asks about a person.

**Workflow**:
1. `protect_get_snapshot(camera_id, timestamp)`
2. `vision_agent(image_url, PERSON_PROMPT)` → structured person JSON
3. Compute behavior suspicion score from behavior indicators
4. Return person profile with suspicion_score

**Key fields**: build, clothing (upper/lower/footwear/headwear), accessories, distinguishing_features, behavior, face_visibility

---

### skill_extract_face_features

**Trigger**: Person with visible face detected, or face recognition requested.

**Phase 1 (LLaVA text description)**:
1. `vision_agent(image_url, FACE_PROMPT)` → face description JSON
2. Generate text signature: `{gender}|{age_range}|{skin_tone}|{hair_color}|{hair_style}|{facial_hair}`
3. Store in entity.metadata.face_description

**Phase 2 (InsightFace embeddings - optional)**:
1. Run InsightFace via `code_interpreter` to generate 512-d embedding
2. Store in entity.face_embedding (pgvector)
3. Use cosine similarity for matching: threshold 0.6

**Quality assessment**: Only process faces with image_quality >= "fair" and face_angle != "back_of_head"

---

### skill_classify_entity_role

**Trigger**: Entity has 5+ sightings, or user asks to classify an entity.

**Workflow**:
1. `protect_get_entity_dossier(entity_id)` → full history
2. Analyze sighting patterns:
   - Frequency: how often per week
   - Time patterns: consistent schedule?
   - Cameras: always same entry point?
   - Duration: quick pass vs. lingering?
3. Apply classification rules:
   - Daily + consistent time + same cameras → "resident"
   - Weekly + daytime + delivery vehicles → "delivery"
   - Irregular + multiple cameras → "visitor"
   - Repeated slow passes + no entry → "suspicious"
4. `protect_classify_entity(entity_id, role)`

**Classification thresholds**:
- resident: ≥ 5 visits/week, consistent ±2h window, same entry camera
- neighbor: 2-5 visits/week, consistent time, adjacent cameras only
- delivery: vehicle + weekday daytime + < 10 min dwell
- service: vehicle + scheduled intervals + known service hours
- passerby: < 5 min dwell, no property approach, consistent direction

---

### skill_detect_anomalous_behavior

**Trigger**: After entity identification, score the anomaly level.

**6-factor scoring**:

1. **Temporal factor** (0-0.3): Time vs. baseline
   - Night hours for residential: +0.3
   - Outside entity's typical schedule: +0.2
   - First-ever sighting: +0.1

2. **Trust factor** (0-0.4): Entity trust level
   - hostile: +0.4
   - suspicious: +0.3
   - unknown: +0.2
   - neutral: +0.05
   - trusted: -0.1

3. **Time-of-day factor** (0-0.2): Hour-specific risk
   - 11pm-5am: +0.2
   - 5am-7am or 9pm-11pm: +0.1
   - Business hours: 0.0

4. **Spatial factor** (0-0.2): Camera zone risk
   - Restricted zone: +0.2
   - Rear/side entry: +0.15
   - Front/main entry: 0.0

5. **Behavioral factor** (0-0.3): Behavior indicators
   - From `compute_behavior_suspicion_score(behavior)`

6. **Frequency factor** (0-0.2): Unusual frequency
   - 3+ visits in 1 hour: +0.2
   - 2 visits in 30 min: +0.1

**Final score**: Weighted sum, clamped to [0.0, 1.0]

---

### skill_update_entity_trust_level

**Trigger**: User explicitly changes trust, or auto-classification triggers trust change.

**Workflow**:
1. Validate transition (hostile → trusted requires explicit user confirmation)
2. `protect_db.update_entity_trust(entity_id, new_level, actor, reason)`
3. Cascade effects:
   - trusted: remove suppressions, lower alert threshold
   - hostile: immediate alert for next sighting, add to hostile list
   - suspicious: raise alert threshold for this entity
4. Log to entity_audit_log

**Valid transitions**:
- unknown → trusted, neutral, suspicious, hostile (any actor)
- neutral → trusted, suspicious, hostile (any actor)
- suspicious → hostile, neutral (any actor)
- hostile → unknown (user only, requires reason)
- trusted → neutral, suspicious (any actor)

---

## Phase 3: Threat Assessment Skills

### skill_assess_threat_level

**Trigger**: Anomaly score > 0.5, or user asks for threat assessment.

**4-dimension analysis**:

1. **Intent** (0-1.0): Evidence of purposeful threat
   - Hostile list match: 0.9
   - Repeated reconnaissance pattern: 0.7
   - Suspicious behavior: 0.5
   - Unknown entity: 0.3

2. **Capability** (0-1.0): Ability to cause harm
   - Tools/weapons visible: 0.9
   - Multiple persons coordinating: 0.7
   - Vehicle with tinted windows: 0.4
   - Single unknown person: 0.3

3. **Opportunity** (0-1.0): Favorable conditions
   - Night + no witnesses: 0.9
   - Vulnerable entry point: 0.7
   - Unmonitored gap: 0.6
   - Daytime + visible: 0.2

4. **History** (0-1.0): Prior incidents
   - Prior hostile events: 0.8
   - Prior suspicious events: 0.5
   - No prior history: 0.2

**Threat score** = max(intent, capability) * 0.5 + opportunity * 0.3 + history * 0.2

**Threat levels**:
- 0.0-0.2: none
- 0.2-0.4: low
- 0.4-0.6: moderate
- 0.6-0.8: high
- 0.8-1.0: critical

**Actions by level**:
- moderate: medium alert
- high: high alert + entity flagged suspicious
- critical: immediate critical alert + all evidence + `protect_mark_entity_hostile`

---

### skill_detect_coordinated_activity

**Trigger**: Multiple events within 15-minute window, or threat score > 0.6.

**Patterns to detect** (sliding 15-min window):

1. **Vehicle + Person**: Vehicle parks → person approaches property within 5 min
2. **Camera sweep**: Same entity on 3+ cameras in sequence within 10 min
3. **Multiple unknowns**: 3+ unknown entities within 15 min
4. **Loiter + approach**: Entity loiters 10+ min then approaches entry

**Scoring**:
- Each pattern detected: +0.3
- Multiple patterns: multiply by 1.5
- Known hostile entity involved: +0.4

**Output**: coordination_score (0-1.0), patterns detected, entities involved

---

### skill_detect_hostile_entity

**Trigger**: Hostile entity detected, or extreme behavior indicators.

**Immediate triggers** (score = 1.0):
- Entity in hostile list appears on camera
- Weapon visible in image
- Forced entry attempt detected
- Property damage in progress

**Escalated triggers** (score = 0.8):
- Hostile entity from coordination event
- Multiple hostile indicators simultaneously

**Auto-response**:
1. Critical alert immediately (no rate limiting)
2. Capture high-quality snapshot
3. `protect_mark_entity_hostile(entity_id, reason, [event_id])`
4. Record in hostile_events table
5. Optionally: trigger deterrent (camera light/speaker if supported)

---

## Phase 4: Investigation Skills

### skill_track_entity_across_cameras

**Trigger**: User asks where an entity went, or post-incident investigation.

**Workflow**:
1. `protect_db.query_sightings(entity_id, start_time, end_time)`
2. Sort by timestamp
3. For each consecutive pair: check camera topology for adjacency
4. Calculate expected transition time (walk: 1.4m/s, vehicle: 8m/s)
5. Flag gaps > 5× expected time
6. Build movement path with dwell times
7. `protect_track_entity(entity_id, origin_camera, origin_time)`

**Output**: trajectory [(camera_id, timestamp, confidence)], dwell_times, gaps, tracking_quality

---

### skill_generate_entity_dossier

**Trigger**: User asks for full profile on an entity, or investigation requested.

**Workflow**:
1. `protect_get_entity_dossier(entity_id)` → full DB record
2. Compile:
   - Identity: type, label, trust_level, role, plate/features
   - Activity: first_seen, last_seen, total_sightings, cameras_visited
   - Patterns: typical visit times, frequency, usual entry point
   - Threat history: anomaly scores, threat assessments, hostile events
   - Associations: other entities seen simultaneously
   - Movement: typical path through property
3. Format as structured report

---

### skill_forensic_timeline_search

**Trigger**: User asks what happened in a time window, or post-incident review.

**Workflow**:
1. `protect_get_events(start_time, end_time, camera_ids)` → all events
2. For each event: fetch entity sightings, anomaly scores, alert records
3. Sort chronologically
4. Group by entity and camera
5. Identify key moments: first appearance, peak activity, departures
6. Generate timeline with evidence links

**Output**: Chronological event list with entity context, anomaly scores, and evidence

---

## Phase 5: Learning and Reporting Skills

### skill_optimize_alert_thresholds

**Trigger**: Weekly scheduled task, or user asks to optimize thresholds.

**Workflow**:
1. Query last 30 days of alerts with user responses
2. For each camera: calculate FP rate, miss rate
3. ROC-like analysis: find threshold that minimizes FP + miss rate
4. `protect_update_alert_preferences(camera_id, min_anomaly_score=optimal_threshold)`
5. Record in optimization_runs table

**Target**: FP rate < 20%, miss rate < 5%

---

### skill_identify_regular_visitors

**Trigger**: Weekly scheduled task, or user asks to identify regulars.

**Workflow**:
1. Query entities with trust_level = "unknown" and sightings_count >= 5
2. For each: analyze visit frequency, time patterns, consistency
3. If pattern matches "regular" criteria: suggest trust upgrade
4. Present to user for confirmation
5. `protect_classify_entity(entity_id, role)` on confirmation

---

### skill_daily_security_briefing

**Trigger**: Morning scheduled task (7am), or user asks for daily briefing.

**Workflow**:
1. Query overnight events (10pm - 7am)
2. Count: total events, unknown entities, alerts, FPs
3. Highlight: new entities, high-anomaly events, hostile sightings
4. System health: queue depth, processing rate, DB size
5. `protect_send_telegram_alert(priority="low", message=briefing)`
6. Store in security_briefings table

---

### skill_generate_security_report

**Trigger**: Weekly/monthly scheduled task, or user requests report.

**Workflow**:
1. `protect_generate_report(start_date, end_date)` → event stats
2. Compile trends: entity activity, alert accuracy, new entities
3. Recommendations: threshold adjustments, entities to classify
4. Format as structured report
5. Store in security_reports table

---

### skill_learn_from_false_positives

**Trigger**: User marks event as false positive, or weekly FP analysis.

**Workflow**:
1. Query recent false positives
2. For each FP: identify root cause
   - Known entity not yet classified → suggest trust upgrade
   - Normal activity at unusual time → suggest time-based exception
   - Camera sensitivity too high → suggest threshold raise
3. Apply corrections automatically where confidence > 0.8
4. Present uncertain corrections to user
5. Store analysis in fp_analysis table

---

## Tool Usage Guidelines

### Always use these tools in order for new events:
1. `protect_get_snapshot` → get image
2. `vision_agent` → analyze image (LLaVA, local only)
3. `protect_search_entities` → check if known
4. `protect_register_entity` (if new) OR `protect_db_store_observation` (if known)
5. `protect_db_get_baseline` → get expected activity
6. `protect_should_alert` → adaptive alert decision
7. `protect_send_telegram_alert` (if alerting)
8. `protect_db_record_alert` → always log

### Entity trust levels (in order of trust):
`trusted` > `neutral` > `unknown` > `suspicious` > `hostile`

### Alert priorities:
`critical` (hostile/weapon) > `high` (suspicious/night/unknown) > `medium` (anomalous) > `low` (informational)

### Never:
- Send images to external APIs (use vision_agent/LLaVA only)
- Alert for trusted entities (unless explicitly requested)
- Skip logging even when not alerting
- Expose raw credentials or DB connection strings

### Always:
- Check alert suppressions before sending
- Apply adaptive thresholds (adjust for camera FP rate)
- Log every observation to DB for learning
- Include snapshot with alerts when available

## Examples

**User says:** "What car is at the driveway?"
**Actions:** Get recent events for that camera, fetch snapshot, run `vision_agent` with vehicle prompt, extract plate if visible, optionally `protect_search_entities` by plate. Return vehicle profile and entity match if known.

**User says:** "Set up a daily security briefing"
**Actions:** Use Phase 5 briefing workflow: aggregate events, summarize by camera, highlight anomalies or alerts, format for Telegram or reply.

**User says:** "Register this person as hostile"
**Actions:** Extract features from snapshot, `protect_register_entity(type="person", features=..., trust_level="hostile")`, store observation. Confirm and explain alert behavior.

## Troubleshooting

**Error:** MCP or protect_* tool fails (connection, auth)
**Cause:** Protect MCP server not connected or credentials not loaded.
**Solution:** Ask user to check MCP connection and env/SSM for credentials. Do not invent credentials.

**Error:** vision_agent unreachable or times out
**Cause:** LLaVA host (on-prem) may be off or runtime not on Tailscale.
**Solution:** Report that local vision is unavailable; suggest user check Ollama/LLaVA host and network. Do not substitute external vision APIs.

**Symptom:** Too many false positive alerts
**Solution:** Use baseline (Phase 2) to establish normal traffic; use `protect_should_alert` and adaptive thresholds; consider raising alert bar for that camera.
