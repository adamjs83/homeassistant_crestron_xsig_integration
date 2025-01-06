"""Exceptions for the Crestron integration."""
from typing import Optional


class CrestronException(Exception):
    """Base exception for Crestron integration."""

    def __init__(self, message: str, details: Optional[str] = None):
        """Initialize the exception."""
        super().__init__(message)
        self.message = message
        self.details = details


class ConnectionError(CrestronException):
    """Connection-related errors."""

    def __init__(self, message: str, details: Optional[str] = None):
        """Initialize connection error."""
        super().__init__(f"Connection error: {message}", details)


class ProtocolError(CrestronException):
    """Protocol-related errors."""

    def __init__(self, message: str, details: Optional[str] = None):
        """Initialize protocol error."""
        super().__init__(f"Protocol error: {message}", details)


class JoinError(CrestronException):
    """Join-related errors."""

    def __init__(self, message: str, details: Optional[str] = None):
        """Initialize join error."""
        super().__init__(f"Join error: {message}", details)


class ConfigError(CrestronException):
    """Configuration-related errors."""

    def __init__(self, message: str, details: Optional[str] = None):
        """Initialize config error."""
        super().__init__(f"Configuration error: {message}", details)


class StateError(CrestronException):
    """State-related errors."""

    def __init__(self, message: str, details: Optional[str] = None):
        """Initialize state error."""
        super().__init__(f"State error: {message}", details)


class EntityError(CrestronException):
    """Entity-related errors."""

    def __init__(self, message: str, details: Optional[str] = None):
        """Initialize entity error."""
        super().__init__(f"Entity error: {message}", details)


class ServiceError(CrestronException):
    """Service-related errors."""

    def __init__(self, message: str, details: Optional[str] = None):
        """Initialize service error."""
        super().__init__(f"Service error: {message}", details)


class ValidationError(CrestronException):
    """Validation-related errors."""

    def __init__(self, message: str, details: Optional[str] = None):
        """Initialize validation error."""
        super().__init__(f"Validation error: {message}", details)


class TimeoutError(CrestronException):
    """Timeout-related errors."""

    def __init__(self, message: str, details: Optional[str] = None):
        """Initialize timeout error."""
        super().__init__(f"Timeout error: {message}", details)