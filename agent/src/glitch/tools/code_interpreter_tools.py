"""AgentCore Code Interpreter tool integration.

Provides secure Python code execution in an isolated sandbox environment
via Amazon Bedrock AgentCore Code Interpreter.
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_code_interpreter_tool = None


def get_code_interpreter_tool():
    """Get the AgentCore Code Interpreter tool instance.
    
    Lazily initializes the tool on first call. Returns None if the
    strands_tools package is not installed or initialization fails.
    
    Returns:
        The code_interpreter tool function, or None if unavailable.
    """
    global _code_interpreter_tool
    
    if _code_interpreter_tool is not None:
        return _code_interpreter_tool
    
    try:
        from strands_tools.code_interpreter import AgentCoreCodeInterpreter
        
        region = os.getenv("AWS_REGION", "us-west-2")
        interpreter = AgentCoreCodeInterpreter(region=region)
        _code_interpreter_tool = interpreter.code_interpreter
        logger.info(f"Initialized AgentCore Code Interpreter for region {region}")
        return _code_interpreter_tool
        
    except ImportError:
        logger.warning(
            "strands_tools.code_interpreter not available. "
            "Install with: pip install 'strands-agents-tools[agent_core_code_interpreter]'"
        )
        return None
    except Exception as e:
        logger.warning(f"Failed to initialize Code Interpreter: {e}")
        return None


def is_code_interpreter_available() -> bool:
    """Check if Code Interpreter is available.
    
    Returns:
        True if the Code Interpreter tool can be initialized.
    """
    return get_code_interpreter_tool() is not None
