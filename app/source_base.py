from abc import ABC, abstractmethod
from pydantic import BaseModel
from .schemas import SearchParams

class RawJob(BaseModel):
    source: str
    payload: dict

class SourceHealth(BaseModel):
    name: str
    configured: bool
    status: str

class BaseJobSource(ABC):
    name: str
    total_estimated: int = 0

    @abstractmethod
    def search(self, params: SearchParams) -> list[RawJob]: ...

    @abstractmethod
    def health(self) -> SourceHealth: ...
