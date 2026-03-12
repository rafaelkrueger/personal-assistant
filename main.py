import os

from cassandra.assistant import CassandraAssistant
from web_server import start_web_server


def main() -> None:
    assistant = CassandraAssistant()
    web_enabled = os.getenv("WEB_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    if web_enabled:
        start_web_server(assistant)
    assistant.run()


if __name__ == "__main__":
    main()
