from __future__ import annotations

from abc import ABC, abstractmethod


class Skill(ABC):
    name: str

    @abstractmethod
    def can_handle(self, text: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def handle(self, text: str) -> str:
        raise NotImplementedError
