"""Portal adapters. Register new portals in ADAPTERS (one line each)."""
from __future__ import annotations

from typing import Dict, Type

from .base import Adapter
from .indeed import IndeedAdapter
from .instahyre import InstahyreAdapter
from .linkedin import LinkedInAdapter
from .naukri import NaukriAdapter
from .wellfound import WellfoundAdapter

ADAPTERS: Dict[str, Type[Adapter]] = {
    "naukri": NaukriAdapter,
    "instahyre": InstahyreAdapter,
    "linkedin": LinkedInAdapter,
    "wellfound": WellfoundAdapter,
    "indeed": IndeedAdapter,
}
