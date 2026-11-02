from dataclasses import dataclass

import httpx

from .config import Settings
from .llm.router import LLMRouter


@dataclass
class AppContext:
    settings: Settings
    http: httpx.AsyncClient
    llm: LLMRouter
