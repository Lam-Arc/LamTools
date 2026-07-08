# Markdown Knowledge Base Tool

A small local command-line tool for organizing Markdown notes. It uses only the
Python standard library.

## Install

No package install is required. Use Python 3.10 or newer.

```bash
python kbtool.py --help
```

## Run

Generate or refresh `index.md` inside a notes directory:

```bash
python kbtool.py scan ./demo_notes
```

Print a health report:

```bash
python kbtool.py report ./demo_notes
```

## What It Extracts

- First `# Heading` as the note title
- Tags from front matter and inline hashtags, such as `#python`
- Wiki links, such as `[[Project Plan]]`
- Markdown file links, such as `[Plan](plan.md)`
- Todo items, such as `- [ ] Review links`

## Example Output

```text
Files: 3
Tags: 4
Todos: 3
Broken links:
- projects.md:7 -> Missing Page (missing wiki page)
- inbox.md:8 -> missing.md (missing file)
```

## Tests

```bash
python -m unittest discover -s tests
```

