"""Session-scoped conversation memory for the assistant."""
from __future__ import annotations

MAX_TURNS = 20  # max user+assistant pairs to keep (older turns are dropped)


class ConversationMemory:
    """Stores the dialogue history for a single active session.

    The assistant calls `add()` after every exchange so that the LLM
    always has full context — even when the previous turn was handled
    by a non-LLM skill (e.g. weather or schedule).

    Memory is cleared when the session expires or the user says goodbye,
    so the next session starts fresh.
    """

    def __init__(self) -> None:
        self._messages: list[dict[str, str]] = []

    def add(self, role: str, content: str) -> None:
        """Append a message and drop the oldest turn if over the limit."""
        self._messages.append({"role": role, "content": content})
        max_messages = MAX_TURNS * 2
        if len(self._messages) > max_messages:
            # Drop the oldest turn (2 messages: user + assistant)
            self._messages = self._messages[2:]

    def add_user(self, text: str) -> None:
        self.add("user", text)

    def add_assistant(self, text: str) -> None:
        self.add("assistant", text)

    def get_messages(self) -> list[dict[str, str]]:
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()

    def __len__(self) -> int:
        return len(self._messages)
