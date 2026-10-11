# SkillDock

[English](README.en.md) · [简体中文](README.md)

A standalone macOS desktop app for managing **user-level global skills** across local AI agents.

[Download for macOS Apple Silicon](https://github.com/Way-To-AGI/SkillDock/releases) · [Test records (Chinese)](docs/TESTING.md) · MIT License

## Open the app

Double-click `release/SkillDock-darwin-arm64/SkillDock.app`, or drag it into Applications.

The packaged app targets Apple Silicon and requires Python 3.10 or later. It looks for Python in Homebrew, `/usr/local/bin`, and system locations. You can also set `SKILLDOCK_PYTHON` to an executable path. The app scans skill directories on first launch; larger collections may take a moment.

## What it manages

SkillDock reads skills from each agent's user-level directories. Creating, editing, and deleting skills operate directly on those directories. These global skills are available across projects according to each agent's loading rules. Project directories are not scanned automatically. The list shows the agent; the editor and deletion dialog show the actual paths.

`~/.agents/skills` is a shared global directory supported by some agents, including Codex, Cline, Kimi, Pi, Warp, and Zed. Actual loading behavior depends on the agent version. `~/.codex/skills` is managed separately. Editing a shared directory affects every agent that reads it. Copies placed in other directories are independent.

### Directory discovery

The built-in catalog contains user-level directory rules for **77 agent types** as of October 10, 2026, including Claude Code, Codex, Cursor, Windsurf, Gemini CLI, OpenCode, and OpenClaw. Shared paths are merged into one directory with the applicable agents listed. See [`app/agent-catalog.json`](app/agent-catalog.json). Finding a directory does not prove that an agent is installed or loads its skills.

Heuristic discovery also looks for `skills` collections containing `*/SKILL.md` in hidden user configuration directories, `~/.local/share`, macOS Application Support, and Windows AppData. Unknown directories remain **unconfirmed and read-only** until you confirm them in the global directory manager. Rescan to update discovery, or manually add a global skill path.

Discovery skips project, dependency, build, temporary, credential, and cache directories and does not follow directory symlinks. It visits at most 2,400 directories, 200 children per level, and four levels deep, with a two-second budget. The interface reports when a limit is reached. Absolute paths set through `XDG_CONFIG_HOME`, `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, `VIBE_HOME`, `HERMES_HOME`, `AUTOHAND_HOME`, and `GROK_HOME` are supported.

Discovery cannot cover every agent, future version, or custom location. Products that do not use the SKILL.md format require separate support. Unknown locations are inferred from their structure and need user confirmation.

New directories are explicitly registered as global directories. Older registrations with other scopes are retained but excluded from the global list.

## Interface and features (v1.4.0)

The workspace has navigation on the left, a skill list in the middle, and details on the right. Views include all skills, editable skills, skills used by multiple agents, and skills needing attention, with agent filters. Skills with the same name are grouped. Selecting a skill opens SKILL.md directly; copy selection and Finder access stay above the editor. Attachments and installation locations expand on demand.

- Reveal a skill folder in Finder from the editor or installation list, including read-only, built-in, plugin, and linked skills. Remote skills support this after installation.
- Create a skill in the right panel with a name, description, target agent, and body, then continue editing it.
- Select skills for batch additions or deletion while keeping search available. Search matches names, descriptions across copies, and agent labels.
- Copying and remote installation share an “Add to Agent…” flow. Targets indicate existing installations. Copies include attachments; existing directories with the same name are skipped.
- Save directly to the selected path, keeping a backup of the previous document. External changes prevent overwriting.
- Delete the current copy to SkillDock's trash with an undo action. Batch deletion lists the affected copies and paths. Older deletions can be restored from the trash view.
- Access skills.sh search and installation, the directory manager, and trash from the sidebar. Refresh and creation controls are at the top.

Shortcuts: `/` to search, `⌘S` to save, and `Esc` to close. The desktop app modifies real local files; the HTML prototype uses in-memory data.

Codex's built-in `.system` skills and plugin cache are read-only. Copy them into a personal skill directory to edit them. Skill directory symlinks can lead to a registered global source for editing; details show discovered references. Links themselves are read-only. Deleting a link from a personal directory preserves its source directory. Copying skips symlink attachments, dependency directories, and build directories.

Creating a skill also creates the selected agent directory if necessary. Whether an agent loads the skill depends on its directory rules; restarting the agent may be necessary. SkillDock does not control agent enablement or execution.

## Data and privacy

Skills remain in their original agent directories. App settings, trash, and document history are stored by default at:

`~/Library/Application Support/SkillDock/store/`

- `settings.json`: skill directories, trash index, and recent activity.
- `trash/`: complete skill folders removed from their original locations.
- `history/`: backups of SKILL.md before edits.
- `cache/`: temporary archives of public repositories.

The local service listens only on `127.0.0.1` and creates a separate session on each launch. Remote searches send search terms to skills.sh; previews and installations access GitHub. Local skills are not uploaded.

Deleting the store folder removes the data needed to restore its trash. Back up both the store folder and the actual skill directories.

## Remote sources

The search integration follows the [official Vercel skills client](https://github.com/vercel-labs/skills/blob/main/src/find.ts). Directory conventions reference its [agent registry](https://github.com/vercel-labs/skills/blob/main/src/agents.ts).

The skills.sh API may change. Non-GitHub sources currently provide external detail links; installation inside the app supports public GitHub repositories. Installation uses the repository's current HEAD and records the source and archive hash in `.skilldock-source.json`. Remote upgrades and version pinning are not currently available.

## Run from source

From the repository directory:

```sh
npm install
npm start
```

Package the Apple Silicon app:

```sh
npm run package
```

If Electron downloads are slow, set `ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/` for the command. This does not change global npm settings.

Source layout: `desktop.cjs` is the desktop entry point, `preload.cjs` exposes native directory selection, `app/server.py` is a local file service using only the Python standard library, and `app/web/` contains the interface.

The build is unsigned and not notarized. If macOS blocks it, try right-clicking the app in Finder and choosing Open.

## Tests

Requires Python 3.10+ and Node.js 22+:

```sh
npm test
npm run test:network # Optional: live search, preview, and installation into temporary directories
```

Offline automated tests use temporary directories and do not require network access or Electron. GitHub Actions runs offline tests with Python 3.10 and 3.13. See the [test records (Chinese)](docs/TESTING.md) for the scope and version of recorded results.
