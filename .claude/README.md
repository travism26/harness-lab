# Claude Code hooks

`.claude/settings.json` declares two command hooks: a PreToolUse hook that refuses secret-shaped shell commands and commits, and a Stop hook that can hold a session open until a check has passed. The scripts are in `.claude/hooks/`. `.claude/hooks/record_check.py` is the wrapper that records a passing check.

1. **Permissions.** Both hook scripts are commands that run with your permissions, outside the sandbox, after the folder is trusted. The trust dialog is the gate: the scripts do not run before it. Read `.claude/hooks/block_secret.py` and `.claude/hooks/stop_check.py` before accepting it. From Claude Code 2.1.329 the trust dialog's warning names where hooks are declared.

2. **Off switch.** One session turns both hooks off with:

   ```
   claude --settings '{"disableAllHooks": true}'
   ```

   There is no per-hook switch in the product. Leaving `HARNESS_LAB_REQUIRE_CHECK` unset, or unsetting it, turns off only the Stop requirement; the secret hook stays on.

3. **Kind and location only.** A match is reported as a kind (`api-key`, `bearer` or `pem`) and a location (`command` or `staged file <repo-relative path>`). The matched value is never printed. The kinds are an Anthropic API key prefix, a `Bearer` token of 20 or more characters, and a PEM private-key header.

4. **The Stop hook is opt-in.** `.claude/hooks/stop_check.py` does nothing unless `HARNESS_LAB_REQUIRE_CHECK` is exactly `1`. With the variable set, it blocks when `.claude/check-passed/<session_id>` is missing or its first line does not start with `passed `, and when the hook input is not a JSON object with a usable session id. The wrapper that writes that marker is `python3 .claude/hooks/record_check.py <session_id> factory` or `python3 .claude/hooks/record_check.py <session_id> project:<name>`. `factory` runs `uv run pytest tests/factory`, `project:<name>` runs `projects/<name>/check`, and the marker is written only when that command exits 0. The factory's workflows do not set the variable. The Stop hook answers with the documented `decision` / `reason` object. The scripts were written against the public hooks reference as fetched on 2026-11-23; a live confirmation is [issue #193](https://github.com/travism26/harness-lab/issues/193).

5. **The cap.** After eight consecutive Stop blocks, Claude Code ends the turn anyway. The hook does not raise that cap (the product variable is `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`; this repo leaves it alone).

6. **What the secret hook scans.** `git commit` and `git push` are scanned on their added staged lines (`git diff --cached -U0`). Any other Bash or PowerShell command is denied only when the command text itself matches. A secret that is already committed, and so is no longer an added staged line, is not scanned on a later push.

7. **What the scripts do not do.** They do not source another file, do not call a model, and do not open a network connection. They are Python 3 standard library only.
