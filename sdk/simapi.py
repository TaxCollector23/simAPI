"""Deprecated import path; install the canonical package with pip install simapi."""
import warnings

from simapi import SimAPI, SimAPIError, validate

warnings.warn("Use 'from simapi import SimAPI'; sdk.simapi is deprecated.",
              DeprecationWarning, stacklevel=2)
__all__ = ["SimAPI", "SimAPIError", "validate"]
