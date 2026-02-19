"""Base class for communication channel adapters.

Provides the abstract interface that all channel adapters must implement.
"""

from abc import ABC, abstractmethod
from typing import Any
import logging

logger = logging.getLogger(__name__)


class ChannelAdapter(ABC):
    """Base class for communication channel adapters.
    
    Channel adapters provide a unified interface for different communication
    channels (Telegram, HTTP, Discord, etc.) to interact with the Glitch agent.
    
    Each adapter is responsible for:
    - Receiving messages from the channel
    - Routing them to the agent
    - Sending responses back to the channel
    - Managing session isolation
    - Enforcing access controls
    """
    
    @abstractmethod
    async def start(self) -> None:
        """Start receiving messages from the channel.
        
        This method should:
        - Initialize the connection to the channel
        - Register message handlers
        - Begin processing incoming messages
        
        Raises:
            Exception: If the channel fails to start
        """
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel adapter gracefully.
        
        This method should:
        - Stop receiving new messages
        - Complete processing of any in-flight messages
        - Clean up resources
        - Close connections
        """
        pass
    
    @abstractmethod
    async def send_message(self, session_id: str, message: str) -> None:
        """Send a message to the channel.
        
        Args:
            session_id: Unique identifier for the session (e.g., "telegram:dm:123456")
            message: Message content to send
            
        Raises:
            Exception: If the message fails to send
        """
        pass
    
    @abstractmethod
    def get_session_id(self, event: Any) -> str:
        """Generate a unique session ID from a channel event.
        
        Session IDs should be deterministic and uniquely identify a conversation
        context. Examples:
        - Telegram DM: "telegram:dm:{user_id}"
        - Telegram Group: "telegram:group:{chat_id}"
        - Telegram Forum: "telegram:group:{chat_id}:topic:{thread_id}"
        
        Args:
            event: The channel-specific event object
            
        Returns:
            A unique session identifier string
        """
        pass
    
    def __repr__(self) -> str:
        """String representation of the adapter."""
        return f"<{self.__class__.__name__}>"
