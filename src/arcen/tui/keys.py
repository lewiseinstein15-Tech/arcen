"""Frozen key-binding map for the redesigned TUI (TUI-02).

Bindings are plain data here — no Textual import at module load — so the
map is testable headlessly and shared by the help screen, the footer hints,
and the app shell. The new map supersedes the legacy shortcuts while
keeping the muscle memory that already shipped (``ctrl+n`` new,
``ctrl+o`` config, ``ctrl+q`` quit); the prototype adds ``ctrl+c``
interrupt, ``ctrl+g`` external editor, slash commands, ``ctrl+r`` resume
and ``?`` help.

Scopes:

- ``global``  — available on the main screen;
- ``composer``— only while the input has focus;
- ``modal``   — only while a modal screen is pushed.
"""

from __future__ import annotations

from dataclasses import dataclass

SCOPE_GLOBAL = "global"
SCOPE_COMPOSER = "composer"
SCOPE_MODAL = "modal"


@dataclass(frozen=True)
class KeySpec:
    """One frozen key binding."""

    key: str           # Textual key identifier, e.g. "ctrl+c" or "/"
    action: str        # action_<action> handler name on the app
    description: str
    scope: str = SCOPE_GLOBAL
    priority: bool = False


# ── the frozen map ──────────────────────────────────────────────────────────
KEYS: tuple[KeySpec, ...] = (
    # run control
    KeySpec("ctrl+c", "interrupt", "Interrupt running turn", priority=True),
    KeySpec("ctrl+q", "quit", "Quit ARCEN", priority=True),
    # sessions
    KeySpec("ctrl+n", "new_chat", "New session"),
    KeySpec("ctrl+r", "resume", "Resume / replay last session"),
    KeySpec("ctrl+b", "toggle_sessions", "Sessions drawer"),
    KeySpec("ctrl+l", "clear_transcript", "Clear transcript"),
    # surfaces
    KeySpec("ctrl+o", "show_config", "Configuration modal"),
    KeySpec("ctrl+s", "show_sandbox", "Sandbox status modal"),
    KeySpec("?", "help", "Help"),
    KeySpec("f1", "help", "Help"),
    # composer
    KeySpec("/", "command_palette", "Slash commands", scope=SCOPE_COMPOSER),
    KeySpec("ctrl+g", "external_editor", "Open $EDITOR", scope=SCOPE_COMPOSER),
    KeySpec("enter", "submit", "Submit goal", scope=SCOPE_COMPOSER),
    # modals
    KeySpec("escape", "close_modal", "Close modal", scope=SCOPE_MODAL),
    KeySpec("q", "close_modal", "Close modal", scope=SCOPE_MODAL),
    KeySpec("enter", "modal_submit", "Save / confirm", scope=SCOPE_MODAL),
)


def for_scope(scope: str) -> tuple[KeySpec, ...]:
    """All bindings visible in a scope (global bindings apply everywhere)."""
    if scope == SCOPE_GLOBAL:
        return tuple(k for k in KEYS if k.scope == SCOPE_GLOBAL)
    return tuple(
        k for k in KEYS if k.scope in (SCOPE_GLOBAL, scope)
    )


def to_textual_bindings(scope: str = SCOPE_GLOBAL):
    """Lazily build Textual ``Binding`` objects for a scope."""
    from textual.app import Binding

    return tuple(
        Binding(
            key=spec.key,
            action=spec.action,
            description=spec.description,
            priority=spec.priority,
        )
        for spec in for_scope(scope)
    )


def help_rows(scope: str = SCOPE_GLOBAL) -> tuple[tuple[str, str], ...]:
    """``(key, description)`` pairs for rendering a help screen/footer."""
    return tuple((spec.key, spec.description) for spec in for_scope(scope))


# Footer hint order used by the prototype chrome.
FOOTER_HINTS: tuple[tuple[str, str], ...] = (
    ("^C", "interrupt"),
    ("^G", "editor"),
    ("/", "commands"),
    ("^R", "resume"),
    ("F1", "help"),
)
