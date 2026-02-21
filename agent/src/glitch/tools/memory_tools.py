"""Memory management tools for updating structured memory state.

These tools allow the agent to maintain structured memory during conversations:
- Session goal tracking
- Fact accumulation
- Constraint recording
- Decision logging
- Open question tracking
"""

import logging
from typing import Optional

from strands import tool

logger = logging.getLogger(__name__)

# Reference to the agent's memory manager (set by agent initialization)
_memory_manager = None


def set_memory_manager(manager) -> None:
    """Set the memory manager reference for tools to use."""
    global _memory_manager
    _memory_manager = manager


def get_memory_manager():
    """Get the current memory manager."""
    return _memory_manager


@tool
def set_session_goal(goal: str) -> str:
    """Set or update the current session goal.
    
    Use this when the user states what they want to accomplish, or when you
    identify the main objective of the conversation.
    
    Args:
        goal: A clear, concise description of what the user wants to achieve.
        
    Returns:
        Confirmation message.
    """
    if not _memory_manager:
        return "Memory manager not available."
    
    if not goal or not goal.strip():
        return "Error: goal cannot be empty."
    
    _memory_manager.update_structured_state({"session_goal": goal.strip()})
    if getattr(_memory_manager, "create_structured_event", None):
        _memory_manager.create_structured_event("session_goal", goal.strip())
    logger.info("Session goal set: %s", goal[:50])
    return f"Session goal updated: {goal}"


@tool
def add_fact(fact: str) -> str:
    """Record an important fact learned during the conversation.
    
    Use this to remember key information the user shares, such as:
    - User preferences
    - Technical details about their environment
    - Business context
    - Requirements or specifications
    
    Args:
        fact: A concise statement of the fact to remember.
        
    Returns:
        Confirmation message.
    """
    if not _memory_manager:
        return "Memory manager not available."
    
    if not fact or not fact.strip():
        return "Error: fact cannot be empty."
    
    sm = _memory_manager.get_structured_state()
    facts = list(sm.facts) if sm.facts else []
    fact_text = fact.strip()
    
    if fact_text not in facts:
        facts.append(fact_text)
        _memory_manager.update_structured_state({"facts": facts})
        if getattr(_memory_manager, "create_structured_event", None):
            _memory_manager.create_structured_event("fact", fact_text)
        logger.info("Fact added: %s", fact_text[:50])
        return f"Fact recorded: {fact_text}"
    
    return f"Fact already recorded: {fact_text}"


@tool
def add_constraint(constraint: str) -> str:
    """Record a constraint or limitation for the current task.
    
    Use this to remember restrictions such as:
    - Budget limits
    - Time constraints
    - Technical limitations
    - Policy requirements
    - User preferences that limit options
    
    Args:
        constraint: A concise description of the constraint.
        
    Returns:
        Confirmation message.
    """
    if not _memory_manager:
        return "Memory manager not available."
    
    if not constraint or not constraint.strip():
        return "Error: constraint cannot be empty."
    
    sm = _memory_manager.get_structured_state()
    constraints = list(sm.constraints) if sm.constraints else []
    constraint_text = constraint.strip()
    
    if constraint_text not in constraints:
        constraints.append(constraint_text)
        _memory_manager.update_structured_state({"constraints": constraints})
        if getattr(_memory_manager, "create_structured_event", None):
            _memory_manager.create_structured_event("constraint", constraint_text)
        logger.info("Constraint added: %s", constraint_text[:50])
        return f"Constraint recorded: {constraint_text}"
    
    return f"Constraint already recorded: {constraint_text}"


@tool
def record_decision(decision: str) -> str:
    """Record a decision made during the conversation.
    
    Use this to track important decisions such as:
    - Architecture choices
    - Tool selections
    - Approach decisions
    - Trade-off resolutions
    
    Args:
        decision: A concise description of the decision and rationale.
        
    Returns:
        Confirmation message.
    """
    if not _memory_manager:
        return "Memory manager not available."
    
    if not decision or not decision.strip():
        return "Error: decision cannot be empty."
    
    sm = _memory_manager.get_structured_state()
    decisions = list(sm.decisions) if sm.decisions else []
    decision_text = decision.strip()
    
    decisions.append(decision_text)
    _memory_manager.update_structured_state({"decisions": decisions})
    if getattr(_memory_manager, "create_structured_event", None):
        _memory_manager.create_structured_event("decision", decision_text)
    logger.info("Decision recorded: %s", decision_text[:50])
    return f"Decision recorded: {decision_text}"


@tool
def add_open_question(question: str) -> str:
    """Record an open question that needs to be resolved.
    
    Use this to track questions that:
    - Need user clarification
    - Require further investigation
    - Are blocking progress
    - Should be addressed later
    
    Args:
        question: The question that needs to be answered.
        
    Returns:
        Confirmation message.
    """
    if not _memory_manager:
        return "Memory manager not available."
    
    if not question or not question.strip():
        return "Error: question cannot be empty."
    
    sm = _memory_manager.get_structured_state()
    questions = list(sm.open_questions) if sm.open_questions else []
    question_text = question.strip()
    
    if question_text not in questions:
        questions.append(question_text)
        _memory_manager.update_structured_state({"open_questions": questions})
        if getattr(_memory_manager, "create_structured_event", None):
            _memory_manager.create_structured_event("open_question", question_text)
        logger.info("Open question added: %s", question_text[:50])
        return f"Open question recorded: {question_text}"
    
    return f"Question already recorded: {question_text}"


@tool
def resolve_question(question: str) -> str:
    """Mark an open question as resolved.
    
    Use this when a previously recorded open question has been answered.
    
    Args:
        question: The question that has been resolved (must match exactly).
        
    Returns:
        Confirmation message.
    """
    if not _memory_manager:
        return "Memory manager not available."
    
    if not question or not question.strip():
        return "Error: question cannot be empty."
    
    sm = _memory_manager.get_structured_state()
    questions = list(sm.open_questions) if sm.open_questions else []
    question_text = question.strip()
    
    if question_text in questions:
        questions.remove(question_text)
        _memory_manager.update_structured_state({"open_questions": questions})
        logger.info("Question resolved: %s", question_text[:50])
        return f"Question resolved: {question_text}"
    
    return f"Question not found in open questions: {question_text}"


@tool
def update_tool_results_summary(summary: str) -> str:
    """Update the summary of tool results from this session.
    
    Use this to maintain a running summary of important tool outputs,
    especially when tools return large amounts of data that should be
    remembered for context.
    
    Args:
        summary: A concise summary of relevant tool results.
        
    Returns:
        Confirmation message.
    """
    if not _memory_manager:
        return "Memory manager not available."
    
    if not summary or not summary.strip():
        return "Error: summary cannot be empty."
    
    _memory_manager.update_structured_state({"tool_results_summary": summary.strip()})
    logger.info("Tool results summary updated")
    return "Tool results summary updated."


@tool
def get_memory_state() -> str:
    """Get the current structured memory state.
    
    Returns a summary of all tracked information:
    - Session goal
    - Facts
    - Constraints
    - Decisions
    - Open questions
    - Tool results summary
    
    Returns:
        Formatted summary of the current memory state.
    """
    if not _memory_manager:
        return "Memory manager not available."
    
    sm = _memory_manager.get_structured_state()
    
    parts = []
    
    if sm.session_goal:
        parts.append(f"**Session Goal:** {sm.session_goal}")
    
    if sm.facts:
        parts.append(f"**Facts ({len(sm.facts)}):**")
        for i, fact in enumerate(sm.facts, 1):
            parts.append(f"  {i}. {fact}")
    
    if sm.constraints:
        parts.append(f"**Constraints ({len(sm.constraints)}):**")
        for i, c in enumerate(sm.constraints, 1):
            parts.append(f"  {i}. {c}")
    
    if sm.decisions:
        parts.append(f"**Decisions ({len(sm.decisions)}):**")
        for i, d in enumerate(sm.decisions[-5:], 1):  # Last 5 decisions
            parts.append(f"  {i}. {d}")
        if len(sm.decisions) > 5:
            parts.append(f"  ... and {len(sm.decisions) - 5} earlier decisions")
    
    if sm.open_questions:
        parts.append(f"**Open Questions ({len(sm.open_questions)}):**")
        for i, q in enumerate(sm.open_questions, 1):
            parts.append(f"  {i}. {q}")
    
    if sm.tool_results_summary:
        parts.append(f"**Tool Results Summary:** {sm.tool_results_summary}")
    
    if not parts:
        return "No structured memory recorded yet."
    
    return "\n".join(parts)
