# Source Web UI Onboarding Design

## Problem

The source-run Electron Web UI launches its backend with:

```text
uv run --project <repository-root> electromind --wire ...
```

Its onboarding health check independently requires a globally installed
`electromind` executable. After the command was renamed from `pagent`, a
developer can therefore have a working project backend, a saved API key, and a
completed onboarding record while still being blocked by the setup wizard on
every launch.

The renderer also emits an install button with
`data-setup-install-pagent`, while its event binding looks for
`data-setup-install-electromind`, so the recovery button does not run.

## Scope

This change fixes the Web UI when it is run from the source repository. It does
not make the packaged desktop application self-contained and does not remove the
global CLI fallback used outside a source checkout.

## Design

### One backend resolution rule

The shared agent module will expose a backend invocation resolver whose result
also states whether it is usable:

1. When the application project root contains `pyproject.toml` and `uv` can be
   resolved, use the project invocation.
2. Otherwise, resolve and require a global `electromind` executable.
3. Environment readiness will use this same result instead of performing a
   separate `command -v electromind` check.

This makes startup and onboarding use one source of truth.

### Onboarding behavior

In a source checkout with a usable project invocation:

- the environment step reports the electromind backend as available;
- a missing global `electromind` executable does not block the UI;
- a completed setup plus a configured API key keeps the wizard closed.

Outside a source checkout, the current global CLI requirement remains.

The install button attribute and selector will both use
`data-setup-install-electromind`.

### Error handling

The resolver only declares the project invocation available when both the
project metadata and `uv` are present. If startup later fails for another
reason, the existing bridge error reporting remains responsible for displaying
that runtime failure. Onboarding will not perform dependency installation or
network access automatically.

## Tests

Regression coverage will verify:

1. A source project with `uv`, no global CLI, a configured API key, and completed
   onboarding is ready and does not show the wizard.
2. A non-source installation with no global CLI is still blocked.
3. Backend startup and health detection select the same project invocation.
4. The renderer's install button attribute matches its event-binding selector.

Desktop TypeScript checking and compilation will run after the focused tests.

