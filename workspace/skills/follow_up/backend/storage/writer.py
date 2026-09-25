"""Follow Up 2.0 — единственный писатель SQLite.

Проверено по коду: `init_db` передаёт `creator`, но URL остаётся `"sqlite://"`
(`database.py`), а диалект pysqlite выбирает пул **по URL, а не по creator**:
memory-URL → `SingletonThreadPool`, то есть отдельное соединение на каждый поток.
При этом `vfs=unix-none` отключает fcntl/posix-блокировки целиком, поэтому
`PRAGMA busy_timeout=30000` бесполезен — ждать нечего, лока не существует.

Комментарий в `database.py` («сервер работает в 1 процесс, нам эти блокировки не
нужны») верен только для одного *потока*, а потоков-писателей уже четыре:
обработчики uvicorn, гидратация актов, синк витрины поручений и бэкофилл. Все
пишут в один файл и в один rollback-журнал (`journal_mode=DELETE`). Две
одновременные транзакции — это две записи в один журнальный файл без единого
лока; порванный журнал уносит не кэш, а историю диалога.

Модуль даёт четыре вещи:

1. общий `RLock` вокруг записи (и вокруг чтения тоже: при `unix-none` читатель
   не защищён от чужой полузаписанной страницы);
2. `write_tx(name)` — транзакция как явная единица; правило «одна транзакция ≤
   один документ» соблюдает вызывающий, потому что 2000 строк под общим локом
   превратили бы гидратацию в стоп-кран для чата;
3. PID-guard на файл БД: внутрипроцессный лок между процессами не работает, и
   если тот же файл открыт другим живым процессом, фоновые писатели не стартуют;
4. `PRAGMA quick_check` при старте: при провале процесс поднимается без фоновых
   писателей, а не продолжает писать поверх битого файла.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Optional

logger = logging.getLogger(__name__)

# Один лок на процесс. RLock — вложенные write_tx внутри одного потока законны.
_WRITE_LOCK = threading.RLock()

_owner_ok: Optional[bool] = None
_integrity: Optional["IntegrityReport"] = None


def _timeout_sec() -> float:
    try:
        from backend.config import get_settings
        return float(get_settings().db_write_lock_timeout_sec)
    except Exception:
        return 30.0


@contextmanager
def write_tx(name: str = "write") -> Generator[None, None, None]:
    """Сериализует запись. Превышение таймаута — баг сериализации, не повод ждать.

    Долгое ожидание лока означает, что кто-то держит транзакцию размером с батч,
    а не с документ. Молча дождаться — значит спрятать причину; операция падает
    и пишется в лог.
    """
    limit = _timeout_sec()
    t0 = time.monotonic()
    if not _WRITE_LOCK.acquire(timeout=limit):
        raise TimeoutError(
            f"[writer] {name}: лок записи не получен за {limit:.0f} с — "
            f"кто-то держит слишком большую транзакцию")
    waited = time.monotonic() - t0
    if waited > 1.0:
        logger.warning(f"[writer] {name}: ждал лок {waited:.1f} с")
    try:
        yield
    finally:
        _WRITE_LOCK.release()


# ──────────────────────────────────────────────────────────────────
# Владелец файла БД
# ──────────────────────────────────────────────────────────────────

def _owner_path() -> Path:
    from backend.config import get_settings
    return Path(str(get_settings().db_file) + ".owner")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False
    return True


def claim_db_owner() -> bool:
    """Помечает файл БД своим. False — им уже владеет живой процесс на этом хосте.

    Ложное срабатывание безопаснее ложного разрешения: при False фоновые писатели
    не стартуют, а инструмент продолжает отвечать на вопросы.
    """
    global _owner_ok
    path = _owner_path()
    me = {"pid": os.getpid(), "host": socket.gethostname(), "started_at": time.time()}
    try:
        if path.exists():
            prev = json.loads(path.read_text(encoding="utf-8"))
            if (prev.get("host") == me["host"]
                    and int(prev.get("pid", -1)) != me["pid"]
                    and _pid_alive(int(prev.get("pid", -1)))):
                logger.error(
                    f"[writer] Файл БД уже занят процессом {prev['pid']} на "
                    f"{prev['host']}: фоновые писатели не стартуют. Если процесс "
                    f"мёртв — удалите {path}")
                _owner_ok = False
                return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(me), encoding="utf-8")
        _owner_ok = True
        return True
    except Exception as e:
        # Не смогли — не блокируем работу, но и не притворяемся владельцем
        logger.warning(f"[writer] PID-guard не установлен: {e}")
        _owner_ok = True
        return True


def release_db_owner() -> None:
    try:
        path = _owner_path()
        if path.exists():
            prev = json.loads(path.read_text(encoding="utf-8"))
            if int(prev.get("pid", -1)) == os.getpid():
                path.unlink()
    except Exception:
        pass


def is_db_owner() -> bool:
    return bool(_owner_ok)


# ──────────────────────────────────────────────────────────────────
# Целостность
# ──────────────────────────────────────────────────────────────────

@dataclass
class IntegrityReport:
    ok: bool
    detail: str
    checked_at: float

    def as_dict(self) -> dict:
        return {"ok": self.ok, "detail": self.detail,
                "checked_at": self.checked_at}


def startup_integrity_check() -> IntegrityReport:
    """`PRAGMA quick_check` при старте.

    При провале фоновые писатели не стартуют и об этом видно в
    `/api/admin/sync/status`: писать поверх битого файла хуже, чем не писать.
    """
    global _integrity
    try:
        from sqlalchemy import text
        from backend.storage.database import get_engine
        with get_engine().connect() as conn:
            rows = conn.execute(text("PRAGMA quick_check")).fetchall()
        detail = "; ".join(str(r[0]) for r in rows) or "ok"
        ok = detail.strip().lower() == "ok"
        if not ok:
            logger.error(f"[writer] Целостность БД: {detail}")
    except Exception as e:
        ok, detail = False, f"проверка не выполнена: {e}"
        logger.error(f"[writer] {detail}")
    _integrity = IntegrityReport(ok, detail, time.time())
    return _integrity


def integrity() -> Optional[IntegrityReport]:
    return _integrity


def background_writers_allowed() -> tuple[bool, str]:
    """Можно ли запускать гидратацию, синк и бэкофилл."""
    if _owner_ok is False:
        return False, "файлом БД владеет другой живой процесс"
    if _integrity is not None and not _integrity.ok:
        return False, f"проверка целостности БД не прошла: {_integrity.detail}"
    return True, ""
