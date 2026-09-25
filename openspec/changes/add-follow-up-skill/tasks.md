## Phase A — Навык

- [x] A.1 `workspace/skills/follow_up/SKILL.md` — фронтматтер (`name`,
      `description`, `metadata.nanobot.always: true`), таблица «когда
      Follow Up / когда `audit_analyzer`», семь инструментов
      `mcp_follow_up_*`, контракт дословного вывода, порядок ожидания
      карточки (`card_start` → `card_status`, вызов сам ждёт до 20 с).
- [x] A.2 `workspace/skills/follow_up/backend/` — код сервера навыка.
- [x] A.3 `scripts/follow_up_mcp` — лаунчер (stdlib, shebang, бит
      исполнения): код рядом → интерпретатор агента; `--where`, `--check`;
      `follow_up_mcp.cmd` — Windows.
- [x] A.4 `requirements.txt` навыка — без пакетов, закреплённых в корневом.
- [x] A.5 `ruff.toml` (исключает `backend/`), `.gitignore` (рабочие данные).
- [x] A.6 `follow_up.env.local.example` — только для отдельного клона.

## Phase B — Реестры

- [x] B.1 `config.json` → `tools.mcpServers.follow_up` (статичный блок,
      `tool_timeout: 120`).
- [x] B.2 `project.json` → `skills.follow_up: {"enabled": true}` с
      комментарием, почему без `tables`/`vector_indexes`.

## Phase C — Документация и тесты

- [x] C.1 `tests/test_follow_up_skill.py`: фронтматтер, набор имён
      инструментов, статичность блока, запись в реестре, stdlib-only
      лаунчер, код рядом находится без настройки, код 3 и чистый stdout
      без кода, `ruff.toml`, `requirements.txt` не спорит с корневым,
      навык не импортирует код проекта.
- [x] C.2 CHANGELOG `[Unreleased] → Added`, README (одна строка),
      `docs/skill-tool-inventory.md` (одна строка).
- [x] C.3 `pytest tests/ -m "not live and not integration"` и
      `ruff check lib workspace tests tools` — без новых падений
      относительно master.

## Phase D — Приёмка (на стороне владельца)

- [ ] D.1 Слить ветку, «Получить из master» на машине gateway.
- [ ] D.2 `python workspace/skills/follow_up/scripts/follow_up_mcp --check`
      — `ok: true`; иначе поставить `requirements.txt` навыка.
- [ ] D.3 Перезапустить gateway (`--profile=prod`), увидеть в логе
      `MCP server 'follow_up': connected, 7 capabilities registered`.
- [ ] D.4 Из чата Единого рабочего места (К1-2) спросить про акт проверки.
- [ ] D.5 Архивировать change, перенести спеку в
      `openspec/specs/architecture/external-process-skill/spec.md`.
