"""Exceptions for iGuardStove integration."""


class IGuardStoveException(Exception):
    """Base exception for iGuardStove integration."""


class CannotConnect(IGuardStoveException):
    """Exception to indicate connection error."""


class InvalidAuth(IGuardStoveException):
    """Exception to indicate authentication error."""


class EventParseError(IGuardStoveException):
    """Exception to indicate failure parsing portal activity events."""


class DevicePageParseError(IGuardStoveException):
    """Exception to indicate failure validating core device page invariants."""


class DashboardParseError(IGuardStoveException):
    """Exception to indicate failure parsing account dashboard devices."""
