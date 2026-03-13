"""Serviço de agenda via CalDAV: Google Calendar, iCloud, Nextcloud, etc."""
from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from uuid import uuid4

_CREDS_PATH = Path("data/calendar_credentials.json")
_CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)

# URLs CalDAV pré-configuradas por provedor (para facilitar o usuário)
PROVIDER_URLS: dict[str, str] = {
    "google": "https://apidata.google.com/caldav/v2/{email}/user",
    "icloud": "https://caldav.icloud.com",
    "nextcloud": "",  # usuário preenche manualmente
}


def _dt_to_str(dt) -> str:
    """Converte datetime/date para string ISO formatada."""
    if isinstance(dt, datetime):
        return dt.strftime("%d/%m/%Y %H:%M")
    if isinstance(dt, date):
        return dt.strftime("%d/%m/%Y")
    return str(dt)


class CalendarService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._creds: dict = self._load_creds()
        self._client = None
        self._calendar = None

    # ── Configuração ──────────────────────────────────────────────────────────

    def configure(self, url: str, username: str, password: str) -> tuple[bool, str]:
        """Salva credenciais e testa a conexão. Retorna (sucesso, mensagem)."""
        ok, msg = self._test(url, username, password)
        if ok:
            self._save_creds({"url": url, "username": username, "password": password})
            with self._lock:
                self._creds = {"url": url, "username": username, "password": password}
                self._client = None
                self._calendar = None
        return ok, msg

    def is_configured(self) -> bool:
        return bool(self._creds.get("username") and self._creds.get("password"))

    def get_status(self) -> dict:
        return {
            "configured": self.is_configured(),
            "username": self._creds.get("username", ""),
            "url": self._creds.get("url", ""),
        }

    def disconnect(self) -> None:
        self._save_creds({})
        with self._lock:
            self._creds = {}
            self._client = None
            self._calendar = None

    # ── Operações de calendário ───────────────────────────────────────────────

    def list_events(self, start: datetime | None = None, end: datetime | None = None) -> list[dict]:
        """Lista eventos no período. Padrão: hoje até 7 dias."""
        if not self.is_configured():
            return []
        if start is None:
            start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if end is None:
            end = start + timedelta(days=7)
        try:
            cal = self._get_calendar()
            if cal is None:
                return []
            events = cal.date_search(start=start, end=end, expand=True)
            result = []
            for ev in events:
                try:
                    comp = ev.icalendar_component
                    dtstart = comp.get("DTSTART")
                    dtend = comp.get("DTEND")
                    start_dt = dtstart.dt if dtstart else None
                    end_dt = dtend.dt if dtend else None
                    result.append({
                        "id": str(ev.url),
                        "uid": str(comp.get("UID", "")),
                        "title": str(comp.get("SUMMARY", "Sem título")),
                        "start": _dt_to_str(start_dt) if start_dt else "",
                        "end": _dt_to_str(end_dt) if end_dt else "",
                        "description": str(comp.get("DESCRIPTION", "")),
                        "start_raw": start_dt.isoformat() if isinstance(start_dt, datetime) else (datetime.combine(start_dt, datetime.min.time()).isoformat() if isinstance(start_dt, date) else ""),
                    })
                except Exception:
                    continue
            result.sort(key=lambda x: x.get("start_raw", ""))
            return result
        except Exception as exc:
            print(f"[CALENDAR] Erro ao listar eventos: {exc}")
            return []

    def create_event(
        self,
        title: str,
        start_dt: datetime,
        end_dt: datetime,
        description: str = "",
    ) -> dict | None:
        """Cria um evento e retorna seu dict, ou None em caso de erro."""
        if not self.is_configured():
            return None
        try:
            from icalendar import Calendar, Event as ICalEvent  # type: ignore

            cal_obj = Calendar()
            cal_obj.add("prodid", "-//Cassandra//PT")
            cal_obj.add("version", "2.0")
            event = ICalEvent()
            uid = str(uuid4())
            event.add("uid", uid)
            event.add("summary", title)
            event.add("dtstart", start_dt)
            event.add("dtend", end_dt)
            event.add("dtstamp", datetime.utcnow())
            if description:
                event.add("description", description)
            cal_obj.add_component(event)
            ical_str = cal_obj.to_ical().decode("utf-8")

            calendar = self._get_calendar()
            if calendar is None:
                return None
            calendar.add_event(ical_str)
            return {
                "uid": uid,
                "title": title,
                "start": _dt_to_str(start_dt),
                "end": _dt_to_str(end_dt),
                "description": description,
            }
        except Exception as exc:
            print(f"[CALENDAR] Erro ao criar evento: {exc}")
            return None

    def delete_event(self, event_id: str) -> bool:
        """Deleta um evento pelo URL (campo 'id' retornado por list_events)."""
        if not self.is_configured():
            return False
        try:
            import caldav  # type: ignore

            client = self._get_client()
            if client is None:
                return False
            event = caldav.Event(client, url=event_id)
            event.delete()
            return True
        except Exception as exc:
            print(f"[CALENDAR] Erro ao deletar evento: {exc}")
            return False

    # ── Helpers internos ──────────────────────────────────────────────────────

    def _get_client(self):
        with self._lock:
            if self._client is None and self.is_configured():
                try:
                    import caldav  # type: ignore

                    self._client = caldav.DAVClient(
                        url=self._creds["url"],
                        username=self._creds["username"],
                        password=self._creds["password"],
                    )
                except Exception:
                    self._client = None
            return self._client

    def _get_calendar(self):
        with self._lock:
            if self._calendar is not None:
                return self._calendar
        client = self._get_client()
        if client is None:
            return None
        try:
            principal = client.principal()
            calendars = principal.calendars()
            # Prefere o calendário principal (normalmente o primeiro ou chamado "Calendar")
            cal = None
            for c in calendars:
                name = getattr(c, "name", "") or ""
                if any(k in name.lower() for k in ["primary", "principal", "calendar", "agenda", "home"]):
                    cal = c
                    break
            if cal is None and calendars:
                cal = calendars[0]
            with self._lock:
                self._calendar = cal
            return cal
        except Exception as exc:
            print(f"[CALENDAR] Erro ao obter calendário: {exc}")
            return None

    @staticmethod
    def _test(url: str, username: str, password: str) -> tuple[bool, str]:
        try:
            import caldav  # type: ignore

            client = caldav.DAVClient(url=url, username=username, password=password)
            principal = client.principal()
            cals = principal.calendars()
            return True, f"Conectado! {len(cals)} calendário(s) encontrado(s)."
        except Exception as exc:
            return False, f"Falha na conexão: {exc}"

    @staticmethod
    def _load_creds() -> dict:
        if _CREDS_PATH.exists():
            try:
                return json.loads(_CREDS_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    @staticmethod
    def _save_creds(creds: dict) -> None:
        _CREDS_PATH.write_text(json.dumps(creds, ensure_ascii=False, indent=2), encoding="utf-8")
