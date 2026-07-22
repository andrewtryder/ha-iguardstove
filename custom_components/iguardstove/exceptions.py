"""Exceptions for iGuardStove integration."""


class IGuardStoveException(Exception):
    """Base exception for iGuardStove integration."""


class CannotConnect(IGuardStoveException):
    """Exception to indicate connection error."""


class InvalidAuth(IGuardStoveException):
    """Exception to indicate authentication error."""


class EventParseError(IGuardStoveException):
    """Exception to indicate failure parsing portal activity events."""
