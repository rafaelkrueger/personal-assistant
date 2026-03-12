from __future__ import annotations

from skills.base import Skill


class SkillRouter:
    def __init__(self, skills: list[Skill]) -> None:
        self.skills = skills

    def route(self, text: str) -> Skill:
        for skill in self.skills:
            if skill.can_handle(text):
                return skill
        return self.skills[-1]
