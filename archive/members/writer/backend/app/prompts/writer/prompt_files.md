# Writer Prompt Files

Writer system prompt fragments are Markdown files so persona and operating rules
can be maintained without editing Python code.

Lookup order:

- `LAMWRITER_PROMPT_DIR/writer`
- `LAMWRITER_PROMPT_DIR`
- `%APPDATA%/LamWriter/prompts/writer`
- `LAMWRITER_MEMBER_RESOURCE_DIR/prompts/writer`
- `LAMTOOLS_RUNTIME_ROOT/members/writer/prompts/writer`
- `members/writer/backend/app/prompts/writer`

Override a fragment by creating a file with the same name in one of the custom
directories. Keep secrets out of prompt files.
