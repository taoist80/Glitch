"""Task planner: produces TaskSpec from user message.

Dataflow:
    user_message -> TaskPlanner.plan() -> TaskSpec
    
The planner analyzes the user message to determine:
- Intent classification (code_modification, debugging, etc.)
- Risk level (low, medium, high)
- Required tools
- Recommended model
- Skill tags to match

This implementation uses heuristic-based planning. For production,
this could be replaced with a lightweight model call.
"""

import logging
import re
from typing import List, Optional, Set

from glitch.skills.types import TaskSpec, DEFAULT_MODEL_ROUTING

logger = logging.getLogger(__name__)

# Intent detection patterns
INTENT_PATTERNS = {
    "code_modification": [
        r"\b(add|create|implement|write|build|make)\b.*\b(function|class|method|feature|code)\b",
        r"\b(modify|change|update|edit|refactor)\b.*\b(code|function|class|file)\b",
        r"\b(fix|patch|correct)\b.*\b(bug|issue|error|problem)\b",
    ],
    "code_review": [
        r"\b(review|check|audit|analyze)\b.*\b(code|pr|pull request|changes)\b",
        r"\b(what do you think|feedback|suggestions)\b.*\b(code|implementation)\b",
    ],
    "debugging": [
        r"\b(debug|troubleshoot|diagnose|investigate)\b",
        r"\b(why|what causes)\b.*\b(errors?|fail|crash|bug|issues?)\b",
        r"\b(not working|broken|fails|crashes|failing)\b",
        r"\bis not working\b",
    ],
    "documentation": [
        r"\b(document|write docs|add comments|explain)\b",
        r"\b(readme|docstring|jsdoc|documentation)\b",
    ],
    "query": [
        r"\b(what is|how does|where is|show me|find|search)\b",
        r"\b(explain|describe|tell me about)\b",
    ],
    "analysis": [
        r"\b(analyze|assess|evaluate|compare)\b",
        r"\b(performance|security|architecture|design)\b.*\b(review|analysis)\b",
    ],
    "configuration": [
        r"\b(configure|setup|config|settings)\b",
        r"\b(environment|env|yaml|json|toml)\b.*\b(file|config)\b",
    ],
    "deployment": [
        r"\b(deploy|release|publish|ship)\b",
        r"\b(ci|cd|pipeline|github actions|cloudformation|cdk)\b",
    ],
    "testing": [
        r"\b(test|spec|unittest|pytest|jest)\b",
        r"\b(write tests|add tests|test coverage)\b",
    ],
}

# Risk indicators
HIGH_RISK_PATTERNS = [
    r"\b(delete|remove|drop|destroy)\b.*\b(database|table|production|prod)\b",
    r"\b(force push|hard reset|rm -rf)\b",
    r"\b(credentials|secrets|api key|password)\b",
    r"\b(production|prod)\b.*\b(deploy|change|modify)\b",
]

MEDIUM_RISK_PATTERNS = [
    r"\b(refactor|rewrite|restructure)\b",
    r"\b(migration|schema change)\b",
    r"\b(breaking change|api change)\b",
]

# Tag extraction patterns
TAG_PATTERNS = {
    "telemetry": [r"\b(telemetry|metrics|observability|monitoring|cloudwatch)\b"],
    "memory": [r"\b(memory|context|conversation|history)\b"],
    "routing": [r"\b(routing|model|tier|escalation)\b"],
    "tools": [r"\b(tool|function|capability)\b"],
    "infrastructure": [r"\b(infrastructure|cdk|cloudformation|terraform|aws)\b"],
    "testing": [r"\b(test|spec|coverage|pytest|jest)\b"],
    "security": [r"\b(security|auth|permission|iam|policy)\b"],
}


class TaskPlanner:
    """Analyzes user messages to produce TaskSpec for skill selection.
    
    This is a heuristic-based planner. For more sophisticated planning,
    replace with a lightweight model call.
    
    Attributes:
        model_routing: Map of intent -> default model
        custom_triggers: Additional trigger patterns to extract
    """
    
    def __init__(
        self,
        model_routing: Optional[dict] = None,
        custom_triggers: Optional[List[str]] = None,
    ):
        """Initialize TaskPlanner.
        
        Args:
            model_routing: Custom intent -> model mapping (uses defaults if None)
            custom_triggers: Additional trigger patterns to extract
        """
        self.model_routing = model_routing or DEFAULT_MODEL_ROUTING
        self.custom_triggers = custom_triggers or []
        
    def plan(self, user_message: str, context: Optional[dict] = None) -> TaskSpec:
        """Analyze user message and produce a TaskSpec.
        
        Args:
            user_message: The user's input message
            context: Optional context (e.g., current file, recent history)
            
        Returns:
            TaskSpec with intent, risk, model, and skill tags
        """
        message_lower = user_message.lower()
        
        # Detect intent
        intent = self._detect_intent(message_lower)
        
        # Assess risk
        risk = self._assess_risk(message_lower)
        
        # Extract skill tags
        skill_tags = self._extract_tags(message_lower)
        
        # Extract raw triggers (phrases that might match skill triggers)
        raw_triggers = self._extract_triggers(message_lower)
        
        # Determine recommended model
        recommended_model = self._recommend_model(intent, risk, context)
        
        # Detect required tools (basic heuristic)
        required_tools = self._detect_required_tools(message_lower)
        
        # Calculate confidence
        confidence = self._calculate_confidence(intent, skill_tags, raw_triggers)
        
        task_spec = TaskSpec(
            intent=intent,
            risk=risk,
            required_tools=required_tools,
            recommended_model=recommended_model,
            skill_tags=skill_tags,
            raw_triggers=raw_triggers,
            confidence=confidence,
        )
        
        logger.debug(
            f"Planned task: intent={intent}, risk={risk}, "
            f"model={recommended_model}, tags={skill_tags}"
        )
        
        return task_spec
    
    def _detect_intent(self, message: str) -> str:
        """Detect the primary intent from the message.
        
        Args:
            message: Lowercase message text
            
        Returns:
            Intent category string
        """
        scores = {}
        
        for intent, patterns in INTENT_PATTERNS.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, message, re.IGNORECASE):
                    score += 1
            if score > 0:
                scores[intent] = score
                
        if not scores:
            return "general"
            
        return max(scores, key=scores.get)
    
    def _assess_risk(self, message: str) -> str:
        """Assess the risk level of the task.
        
        Args:
            message: Lowercase message text
            
        Returns:
            Risk level: "low", "medium", or "high"
        """
        for pattern in HIGH_RISK_PATTERNS:
            if re.search(pattern, message, re.IGNORECASE):
                return "high"
                
        for pattern in MEDIUM_RISK_PATTERNS:
            if re.search(pattern, message, re.IGNORECASE):
                return "medium"
                
        return "low"
    
    def _extract_tags(self, message: str) -> List[str]:
        """Extract skill tags from the message.
        
        Args:
            message: Lowercase message text
            
        Returns:
            List of matched tags
        """
        tags: Set[str] = set()
        
        for tag, patterns in TAG_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, message, re.IGNORECASE):
                    tags.add(tag)
                    break
                    
        return sorted(tags)
    
    def _extract_triggers(self, message: str) -> List[str]:
        """Extract potential trigger phrases from the message.
        
        This extracts key phrases that might match skill triggers.
        
        Args:
            message: Lowercase message text
            
        Returns:
            List of potential trigger phrases
        """
        triggers: List[str] = []
        
        # Extract noun phrases (simplified)
        # Look for patterns like "telemetry system", "memory management", etc.
        noun_phrase_pattern = r"\b(\w+(?:\s+\w+)?(?:\s+(?:system|management|tools?|module|feature|code)))\b"
        matches = re.findall(noun_phrase_pattern, message, re.IGNORECASE)
        triggers.extend(matches)

        # Also include all significant words and 2-word phrases from the message so
        # skill triggers like "nginx", "ui not loading", "glitch ui" can match directly.
        words = re.findall(r'\b[a-z][\w./-]*\b', message)
        triggers.extend(words)
        # 2-word phrases
        for i in range(len(words) - 1):
            triggers.append(f"{words[i]} {words[i+1]}")
        # 3-word phrases
        for i in range(len(words) - 2):
            triggers.append(f"{words[i]} {words[i+1]} {words[i+2]}")

        # Add custom triggers
        for trigger in self.custom_triggers:
            if trigger.lower() in message:
                triggers.append(trigger)
                
        return list(set(triggers))
    
    def _recommend_model(
        self,
        intent: str,
        risk: str,
        context: Optional[dict],
    ) -> str:
        """Recommend a model based on intent and risk.
        
        Args:
            intent: Detected intent
            risk: Risk level
            context: Optional context
            
        Returns:
            Recommended model name
        """
        base_model = self.model_routing.get(intent, "glitch")
        
        # Escalate for high-risk tasks
        if risk == "high":
            if base_model == "glitch":
                return "sonnet-4.5"
            elif base_model == "sonnet-4.5":
                return "opus-4"
                
        return base_model
    
    def _detect_required_tools(self, message: str) -> List[str]:
        """Detect tools that might be required for this task.
        
        Args:
            message: Lowercase message text
            
        Returns:
            List of tool names
        """
        tools: List[str] = []
        
        tool_patterns = {
            "telemetry": r"\b(telemetry|metrics|usage)\b",
            "vision_agent": r"\b(image|picture|screenshot|visual)\b",
            "local_chat": r"\b(ollama|local model|llama)\b",
            "update_soul": r"\b(personality|soul|behavior|remember)\b",
        }
        
        for tool, pattern in tool_patterns.items():
            if re.search(pattern, message, re.IGNORECASE):
                tools.append(tool)
                
        return tools
    
    def _calculate_confidence(
        self,
        intent: str,
        skill_tags: List[str],
        raw_triggers: List[str],
    ) -> float:
        """Calculate confidence in the task classification.
        
        Args:
            intent: Detected intent
            skill_tags: Extracted tags
            raw_triggers: Extracted triggers
            
        Returns:
            Confidence score 0.0 to 1.0
        """
        confidence = 0.5  # Base confidence
        
        # Higher confidence if we detected a specific intent
        if intent != "general":
            confidence += 0.2
            
        # Higher confidence if we found skill tags
        if skill_tags:
            confidence += min(0.2, len(skill_tags) * 0.1)
            
        # Higher confidence if we found triggers
        if raw_triggers:
            confidence += min(0.1, len(raw_triggers) * 0.05)
            
        return min(1.0, confidence)
