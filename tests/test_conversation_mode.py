"""Modo conversa (cassandra/conversation_mode.py)."""
from cassandra import conversation_mode as cm
from skills.general_chat.skill import GeneralChatSkill


def test_voice_phrases_turn_it_on_and_off():
    assert cm.is_start("Cassandra, vamos conversar") and cm.is_start("liga o modo conversa")
    assert cm.is_stop("chega de conversa") and cm.is_stop("desliga o modo conversa")
    assert not cm.is_start("desliga o modo conversa")
    assert not cm.is_stop("para, que conversa boa") and not cm.is_start("que horas são")


def test_chat_prompt_gets_the_conversation_style_only_when_on():
    chat = GeneralChatSkill(llm=None, memory=None)
    try:
        cm.set_active(False)
        assert "MODO CONVERSA" not in chat._build_system_prompt()
        assert cm.set_active(True) and not cm.set_active(True)
        assert "MODO CONVERSA" in chat._build_system_prompt()
    finally:
        cm.set_active(False)
