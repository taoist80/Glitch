"""Owner bootstrap system via pairing codes.

Manages bot ownership claiming through a one-time pairing code.
The first user to provide the correct code becomes the owner.
"""

import logging
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional, Union

from glitch.channels.types import BootstrapState
from glitch.channels.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class OwnerBootstrap:
    """Manages bot ownership claiming via pairing code.
    
    On first startup (unclaimed bot), generates a pairing code that expires
    in 1 hour. The first user to provide this code becomes the owner.
    
    States:
    - UNCLAIMED: No owner, waiting for pairing code
    - CLAIMED: Owner set, normal operation
    - LOCKED: Owner has locked configuration
    
    Supports both local ConfigManager and DynamoDBConfigManager backends.
    """
    
    def __init__(self, config_manager: Union[ConfigManager, "DynamoDBConfigManager"]):
        """Initialize bootstrap system.
        
        Args:
            config_manager: ConfigManager or DynamoDBConfigManager instance
        """
        self.config_manager = config_manager
        self._uses_dynamodb = hasattr(config_manager, "get_pairing_code") and hasattr(config_manager, "validate_pairing_code")
        self.state = self._determine_state()
        
        # Generate pairing code if unclaimed
        if self.state.status == "unclaimed":
            if self._uses_dynamodb:
                # DynamoDB mode: get code from shared storage
                code = self.config_manager.get_pairing_code()
                self.state.pairing_code = code
                self.state.code_expires_at = datetime.utcnow() + timedelta(hours=1)
            else:
                # Local mode: generate code locally
                self._generate_new_code()
            
            logger.warning(
                f"╔══════════════════════════════════════════╗\n"
                f"║ Bot is UNCLAIMED                         ║\n"
                f"║ Send this code to your bot to claim it:  ║\n"
                f"║                                          ║\n"
                f"║        {self.state.pairing_code}                       ║\n"
                f"║                                          ║\n"
                f"║ Code expires in 1 hour                   ║\n"
                f"╚══════════════════════════════════════════╝"
            )
    
    def _determine_state(self) -> BootstrapState:
        """Determine current bootstrap state from config.
        
        Returns:
            BootstrapState instance
        """
        config = self.config_manager.config
        if config is None:
            return BootstrapState(status="unclaimed")
        
        if config.locked:
            return BootstrapState(
                status="locked",
                owner_id=config.owner.telegram_id if config.owner else None,
                claimed_at=datetime.fromisoformat(config.owner.claimed_at.rstrip("Z")) if config.owner and config.owner.claimed_at else None,
            )
        
        if config.owner and config.owner.telegram_id:
            return BootstrapState(
                status="claimed",
                owner_id=config.owner.telegram_id,
                claimed_at=datetime.fromisoformat(config.owner.claimed_at.rstrip("Z")) if config.owner.claimed_at else None,
            )
        
        return BootstrapState(status="unclaimed")
    
    def _generate_new_code(self) -> None:
        """Generate a new pairing code.
        
        Code is 8 uppercase alphanumeric characters, valid for 1 hour.
        """
        # Generate 8-character alphanumeric code
        alphabet = string.ascii_uppercase + string.digits
        code = ''.join(secrets.choice(alphabet) for _ in range(8))
        
        self.state.pairing_code = code
        self.state.code_expires_at = datetime.utcnow() + timedelta(hours=1)
        
        logger.info(f"Generated pairing code (expires in 1 hour)")
    
    def generate_pairing_code(self) -> str:
        """Generate and return a new pairing code.
        
        Returns:
            8-character pairing code
            
        Raises:
            ValueError: If bot is already claimed or locked
        """
        if self.state.status != "unclaimed":
            raise ValueError(f"Cannot generate pairing code: bot is {self.state.status}")
        
        self._generate_new_code()
        return self.state.pairing_code
    
    def validate_code(self, code: str, user_id: int) -> bool:
        """Validate pairing code and claim ownership if correct.
        
        Args:
            code: Pairing code provided by user
            user_id: Telegram user ID attempting to claim
            
        Returns:
            True if code is valid and ownership claimed, False otherwise
        """
        code_clean = (code or "").strip().upper()
        logger.info(
            "Pairing validate_code entry",
            extra={
                "user_id": user_id,
                "code_len": len(code_clean),
                "status": self.state.status,
                "has_pairing_code": bool(self.state.pairing_code),
                "uses_dynamodb": self._uses_dynamodb,
            },
        )
        
        if self.state.status != "unclaimed":
            logger.warning(
                "Pairing reject: status",
                extra={"reason": "not_unclaimed", "status": self.state.status},
            )
            return False

        # DynamoDB mode: delegate to config manager for atomic validation
        if self._uses_dynamodb:
            if self.config_manager.validate_pairing_code(code_clean, user_id):
                self.state = BootstrapState(
                    status="claimed",
                    owner_id=user_id,
                    claimed_at=datetime.utcnow(),
                )
                logger.info(f"Ownership claimed by Telegram user {user_id} (DynamoDB)")
                return True
            return False

        # Local mode: validate locally
        if not self.state.pairing_code:
            logger.warning("Pairing reject: no pairing code on this instance", extra={"reason": "no_code"})
            return False

        # Check expiration
        if self.state.code_expires_at and datetime.utcnow() > self.state.code_expires_at:
            logger.warning("Pairing reject: code expired", extra={"reason": "expired"})
            self._generate_new_code()
            return False

        # Validate code (case-insensitive)
        if code_clean != self.state.pairing_code:
            logger.warning(
                "Pairing reject: code mismatch",
                extra={"reason": "mismatch", "user_id": user_id},
            )
            return False
        
        # Claim ownership
        try:
            self.config_manager.set_owner(user_id)
            self.state = BootstrapState(
                status="claimed",
                owner_id=user_id,
                claimed_at=datetime.utcnow(),
            )
            logger.info(f"Ownership claimed by Telegram user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to claim ownership: {e}")
            return False
    
    def is_owner(self, user_id: int) -> bool:
        """Check if user is the owner.
        
        Args:
            user_id: Telegram user ID to check
            
        Returns:
            True if user is the owner, False otherwise
        """
        return self.state.owner_id == user_id
    
    def is_claimed(self) -> bool:
        """Check if bot has been claimed.
        
        Returns:
            True if bot is claimed or locked, False if unclaimed
        """
        # For DynamoDB mode, refresh state from shared storage
        if self._uses_dynamodb and hasattr(self.config_manager, "is_claimed"):
            if self.config_manager.is_claimed():
                if self.state.status == "unclaimed":
                    # Refresh state from DynamoDB
                    self.state = self._determine_state()
                return True
            return False
        
        return self.state.status in ("claimed", "locked")
    
    def get_pairing_code(self) -> Optional[str]:
        """Get the current pairing code if available.
        
        Returns:
            Pairing code if unclaimed, None otherwise
        """
        if self.state.status == "unclaimed":
            # DynamoDB mode: get from shared storage
            if self._uses_dynamodb:
                return self.config_manager.get_pairing_code()
            
            # Local mode: check expiration
            if self.state.code_expires_at and datetime.utcnow() > self.state.code_expires_at:
                self._generate_new_code()
            return self.state.pairing_code
        return None
    
    def lock(self) -> None:
        """Lock the bot configuration.
        
        Raises:
            ValueError: If bot is not claimed
        """
        if self.state.status != "claimed":
            raise ValueError(f"Cannot lock: bot is {self.state.status}")
        
        self.config_manager.lock()
        self.state.status = "locked"
        logger.info("Bot configuration locked")
    
    def unlock(self) -> None:
        """Unlock the bot configuration.
        
        Raises:
            ValueError: If bot is not locked
        """
        if self.state.status != "locked":
            raise ValueError(f"Cannot unlock: bot is {self.state.status}")
        
        self.config_manager.unlock()
        self.state.status = "claimed"
        logger.info("Bot configuration unlocked")
    
    def transfer_ownership(self, new_owner_id: int) -> None:
        """Transfer ownership to another user.
        
        Args:
            new_owner_id: Telegram user ID of new owner
            
        Raises:
            ValueError: If bot is not claimed or is locked
        """
        if self.state.status == "unclaimed":
            raise ValueError("Cannot transfer: bot is unclaimed")
        
        if self.state.status == "locked":
            raise ValueError("Cannot transfer: bot is locked")
        
        old_owner = self.state.owner_id
        self.config_manager.set_owner(new_owner_id)
        self.state.owner_id = new_owner_id
        self.state.claimed_at = datetime.utcnow()
        
        logger.info(f"Ownership transferred from {old_owner} to {new_owner_id}")
