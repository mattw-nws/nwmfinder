"""nwmfinder: discover, check availability of, and download National Water Model (NWM) data files.

Standard-library only. Requires Python >= 3.10.
"""
from .exceptions import (
    NwmFinderError,
    DataNotFoundError,
    UnexpectedResponseError,
    DownloadError,
    IncompleteDownloadError,
)
from .model_registry import ModelVariant, SourceTemplate, MODEL_REGISTRY, PRODUCT_CHANNEL_RT, PRODUCT_TERRAIN_RT, PRODUCT_LAND, PRODUCTS
from .finder import NwmFinder, Cycle, FileReference
from .downloader import Downloader, DownloadResult
from ._http import head as http_head, HeadResult

__all__ = [
    "NwmFinderError",
    "DataNotFoundError",
    "UnexpectedResponseError",
    "DownloadError",
    "IncompleteDownloadError",
    "ModelVariant",
    "SourceTemplate",
    "MODEL_REGISTRY",
    "PRODUCT_CHANNEL_RT",
    "PRODUCT_TERRAIN_RT",
    "PRODUCT_LAND",
    "PRODUCTS",
    "NwmFinder",
    "Cycle",
    "FileReference",
    "Downloader",
    "DownloadResult",
    "http_head",
    "HeadResult",
]
