# Interface languages

Core supports `zh-CN` (default), `zh-TW`, `ja`, and `en`. Settings → General →
Interface language persists `{ "locale": "en" }` in the `core.language`
namespace of `settings.jsonc`. The saved preference loads when the app starts.
The setting changes interface copy immediately without remounting the app or
discarding settings drafts. It does not set the language of model responses.

The matching CLI commands, run from `core/`, are:

```powershell
py -3.14 -m lamtools_core.cli language get
py -3.14 -m lamtools_core.cli language set en
```

CLI changes apply to the interface on its next launch.

All four catalogs are bundled JSON files; translation needs no network access
at runtime. Use `t(source, params)` only for authored interface text. Leave
user/model content, paths, protocol IDs, configuration values and prompt text
intact. Translate placeholders as part of a full phrase instead of translating
their values. HTML remains code; translate and escape only its text/attributes.

Use getters or computed values for option labels defined outside render
functions. `defaultUiText(value, defaultSource)` translates a component's
default copy while preserving a caller's custom text. Locale is part of
Markdown cache and message-part memo dependencies; streaming DOM resets only
on a language change, retaining normal incremental behavior between changes.

Update every catalog when adding a source key. `interface-language.test.ts`
checks source-key coverage, matching keys, placeholder preservation, live
switching, persistence failure, startup races, Workflow filters, Markdown
caches, and settings-draft preservation. Long help text has initial translated
copy; the common menu/action vocabulary has been curated for consistency.
