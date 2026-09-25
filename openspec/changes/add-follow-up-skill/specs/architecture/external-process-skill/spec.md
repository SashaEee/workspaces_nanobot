## Purpose

Определить, как навык, работающий **отдельным процессом** (своя база,
свои фоновые потоки), подключается к агенту, не нарушая границу
Skill/Tool и не создавая второго реестра. Первый такой навык —
`follow_up`; контракт общий для любого следующего.

## Requirements

### Requirement: External-process skill lives under workspace/skills

The system SHALL represent an external-process skill as a directory
`workspace/skills/<name>/` containing `SKILL.md` (agent instructions), the
implementation code, and a launcher `scripts/<name>_mcp` (POSIX) with a
`.cmd` twin (Windows).

#### Scenario: Agent discovers the skill

- **WHEN** gateway builds the system prompt
- **THEN** `SkillsLoader` SHALL pick up `workspace/skills/<name>/SKILL.md`
  like any other skill, and `metadata.nanobot.always` SHALL control whether
  it is always in context.

### Requirement: Registration goes through nanobot-ai MCP only

The system SHALL register the skill's tools through
`config.json::tools.mcpServers.<name>` (stdio), the generic MCP mechanism
of `nanobot-ai`, and SHALL declare the skill in `project.json::skills.<name>`.

#### Scenario: Static configuration in git

- **WHEN** `tools.mcpServers.<name>` is committed
- **THEN** `command` SHALL be the launcher path relative to the repository
  root, SHALL NOT contain machine-specific absolute paths and SHALL NOT
  contain `${VAR}` references (an unset variable fails
  `resolve_config_env_vars` at startup).

### Requirement: No per-machine configuration

The launcher SHALL find the implementation inside the skill directory and
SHALL start it with the agent's interpreter, so that a checkout of the
repository is enough to run the skill.

#### Scenario: Launcher passes the agent context

- **WHEN** the launcher starts the implementation
- **THEN** it SHALL set `NANOBOT_HOME` to the repository root derived from
  its own location, and the implementation SHALL take the model settings,
  the database connection (`channels.postgres.dsn`) and the schema
  (`channels.postgres.schema`) from the agent's configuration, explicit
  settings of the skill taking precedence.

#### Scenario: Machine where the skill cannot start

- **WHEN** the implementation is absent
- **THEN** the launcher SHALL exit with code 3, SHALL write the reason to
  stderr only (stdout is the JSON-RPC channel), and gateway SHALL log
  `failed to connect` for that server and continue startup.

### Requirement: Launcher has no project dependencies

The launcher SHALL use only the Python standard library and SHALL run under
any interpreter available on `PATH` (`python` on Windows, the shebang
interpreter on POSIX).

## Negative Requirements

The system SHALL NOT:

- import the skill implementation from `lib/`, `workspace/tools/` or any
  other skill, nor import project code from the implementation;
- pin in the skill's `requirements.txt` packages already pinned in the root
  `requirements.txt`;
- contain host names, database names or schema names of a particular site
  in the skill implementation;
- add a second registry of skills or tools besides `project.json::skills.*`
  and `config.json::tools.mcpServers.*`;
- introduce a dependency on OpenSpec from production code.
