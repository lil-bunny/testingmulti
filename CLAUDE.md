# Secrets policy

`.env` holds real credentials (Turvo, Unipile, LLM gateway, DB). Never read, print, log, quote,
or copy its contents, including via `cat`, `grep`, `head`, editors, or shell one-liners.
`.env.example` is fine to read (placeholders only).

`.claude/settings.json` enforces this for the Read/Edit tools and common shell commands, but
shell access is inherently hard to fully lock down, treat this as a hard rule to follow, not
just something already handled for you.

If a task genuinely requires a secret value (e.g. debugging why a specific env var isn't
loading), ask the user to confirm or paste the specific value themselves rather than reading the
file directly.
