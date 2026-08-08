import sys

from rich.console import Console
from rich.panel import Panel
from rich.padding import Padding
from rich.prompt import Prompt
from rich.table import Table
from rich import box
from typing import List, Dict, Any, Optional, Tuple, Sequence
from enum import Enum
from vocab_builder.core.esc_config import read_esc_sequence_timeout

try:
    from vocab_builder.diagnostics import esc_latency
except ImportError:  # pragma: no cover - diagnostics are optional
    esc_latency = None  # type: ignore[assignment]

_ESCAPE_SENTINEL = "\x1b"
_ESC_SEQUENCE_TIMEOUT = read_esc_sequence_timeout()


class NonInteractiveError(RuntimeError):
    """Raised when headless code attempts to request console input."""


def _configure_timeout(app) -> None:
    """Force prompt_toolkit to dispatch ESC immediately."""
    try:
        app.timeoutlen = 0  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive for prompt_toolkit internals
        pass
    try:
        if hasattr(app, "ttimeoutlen"):
            app.ttimeoutlen = max(0.0, _ESC_SEQUENCE_TIMEOUT)  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        pass


_ESC_TRACER = esc_latency.tracer() if esc_latency else None
_PROMPT_TOOLKIT_INIT_ATTEMPTED = False
_PROMPT_SESSION = None
_PATCH_STDOUT = None


def read_line(prompt: str = "", *, console: Optional[Console] = None) -> str:
    """Return a single line of user input with shared history & arrow support."""
    result = _prompt_with_prompt_toolkit(prompt)
    if result is not None:
        return result

    result = _prompt_with_console(prompt, console)
    if result is not None:
        return result

    if _ESC_TRACER:
        _ESC_TRACER.log_fallback("builtins.input")
    return input(prompt)


def _prompt_with_console(prompt: str, console: Optional[Console]) -> Optional[str]:
    if console is None:
        return None
    console_input = getattr(console, "input", None)
    if not callable(console_input):
        return None
    if _ESC_TRACER:
        _ESC_TRACER.log_fallback("console.input")
    return console_input(prompt)


def _prompt_with_prompt_toolkit(prompt: str) -> Optional[str]:
    if not sys.stdin.isatty():
        return None

    session, patch_stdout = _get_prompt_toolkit_handles()
    if session is None or patch_stdout is None:
        return None

    try:
        if _ESC_TRACER:
            _ESC_TRACER.mark_prompt_start(prompt)
        _safe_configure_timeout(session.app)
        with patch_stdout(raw=True):
            result = session.prompt(prompt)
        if _ESC_TRACER:
            _ESC_TRACER.mark_prompt_end(result)
        return result
    except EOFError:
        if _ESC_TRACER:
            _ESC_TRACER.mark_prompt_end("EOFError")
        return None


def _safe_configure_timeout(app) -> None:
    try:
        _configure_timeout(app)
    except Exception:  # pragma: no cover - defensive for prompt_toolkit internals
        return


def _get_prompt_toolkit_handles():
    global _PROMPT_TOOLKIT_INIT_ATTEMPTED, _PROMPT_SESSION, _PATCH_STDOUT

    if _PROMPT_SESSION is not None and _PATCH_STDOUT is not None:
        return _PROMPT_SESSION, _PATCH_STDOUT

    _ensure_prompt_toolkit_initialized()
    return _PROMPT_SESSION, _PATCH_STDOUT


def _ensure_prompt_toolkit_initialized() -> None:
    global _PROMPT_TOOLKIT_INIT_ATTEMPTED, _PROMPT_SESSION, _PATCH_STDOUT

    if _PROMPT_TOOLKIT_INIT_ATTEMPTED:
        return
    _PROMPT_TOOLKIT_INIT_ATTEMPTED = True

    imports = _try_import_prompt_toolkit()
    if imports is None:
        _PROMPT_SESSION = None
        _PATCH_STDOUT = None
        return

    PromptSession, InMemoryHistory, patch_stdout, KeyBindings = imports
    session = _build_prompt_toolkit_session(PromptSession, InMemoryHistory, KeyBindings)
    _PROMPT_SESSION = session
    _PATCH_STDOUT = patch_stdout


def _try_import_prompt_toolkit():  # pragma: no cover - depends on optional dependency
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import InMemoryHistory
        from prompt_toolkit.patch_stdout import patch_stdout
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return None
    return PromptSession, InMemoryHistory, patch_stdout, KeyBindings


def _build_prompt_toolkit_session(PromptSession, InMemoryHistory, KeyBindings):
    history = InMemoryHistory()
    key_bindings = KeyBindings()

    @_wrap_key_binding_add(key_bindings)
    def _handle_escape(event) -> None:
        if _ESC_TRACER:
            _ESC_TRACER.log_escape_handler("key_binding")
        event.app.exit(result=_ESCAPE_SENTINEL)

    session = PromptSession(history=history, key_bindings=key_bindings)
    _safe_configure_timeout(session.app)
    return session


def _wrap_key_binding_add(key_bindings_obj):
    """Return a decorator that registers a binding, keeping the callsite tidy."""
    return key_bindings_obj.add("escape", eager=True)

class MessageType(Enum):
    """Enum for consistent message styling with Anthropic-inspired color palette"""
    ERROR = ("bold #ff6b6b", "Error", "#ff6b6b")  # Coral red
    SUCCESS = ("bold #51cf66", "Success", "green3")  # Mint green
    WARNING = ("bold #ffd43b", "Warning", "yellow3")  # Warm yellow
    INFO = ("bold #E67E50", "Info", "dark_orange")  # Anthropic orange
    DEBUG = ("#909090", "Debug", "#909090")  # Medium gray for better accessibility


DEFAULT_MENU_INSTRUCTIONS = (
    "[↑↓] Navigate • [Enter] Select • [Esc] Go back"
)

class UIHelper:
    """Centralized UI helper for all console output operations"""
    
    def __init__(
        self,
        console: Optional[Console] = None,
        *,
        interactive: bool = True,
    ):
        self.console = console or Console()
        self.interactive = interactive
        self._message_indent = 2  # Consistent gutter for inline status text
    
    # ========== Basic Message Methods ==========
    
    def message(
        self,
        text: str,
        msg_type: MessageType,
        *,
        accent: str | None = None,
        indent: bool = True,
    ) -> None:
        """Display a formatted message based on type"""
        style, _, _ = msg_type.value
        rendered = text
        if accent:
            rendered = f"[{accent}]{rendered}[/{accent}]"
        rendered = f"[{style}]{rendered}[/{style}]"
        if indent and self._message_indent:
            rendered = Padding(rendered, (0, 0, 0, self._message_indent))
        self.console.print(rendered)

    def error(self, text: str, with_panel: bool = False, *, accent: str | None = None) -> None:
        """Display error message with symbol, optionally in a panel.

        Use with_panel=True for:
        - Critical system errors (file I/O failures, API unavailable)
        - Errors that block core functionality
        - Multi-line error messages with context

        Use plain text (with_panel=False) for:
        - User input validation errors
        - Recoverable errors
        - Single-line error messages
        """
        formatted_text = f"✗ {text}"
        if with_panel:
            self.panel(formatted_text, "Error", "#ff6b6b", style="bold #ff6b6b")
        else:
            self.message(formatted_text, MessageType.ERROR, accent=accent)

    def success(self, text: str, with_panel: bool = False, *, accent: str | None = None) -> None:
        """Display success message with symbol, optionally in a panel"""
        formatted_text = f"✓ {text}"
        if with_panel:
            self.panel(formatted_text, "Success", "green3", style="bold #51cf66")
        else:
            self.message(formatted_text, MessageType.SUCCESS, accent=accent)

    def warning(self, text: str, with_panel: bool = False, *, accent: str | None = None) -> None:
        """Display warning message with symbol, optionally in a panel"""
        formatted_text = f"⚡ {text}"
        if with_panel:
            self.panel(formatted_text, "Warning", "yellow3", style="bold #ffd43b")
        else:
            self.message(formatted_text, MessageType.WARNING, accent=accent)

    def info(self, text: str, with_panel: bool = False, *, accent: str | None = None) -> None:
        """Display info message with symbol, optionally in a panel"""
        formatted_text = f"ℹ {text}"
        if with_panel:
            self.panel(formatted_text, "Information", "dark_orange", style="bold #E67E50")
        else:
            self.message(formatted_text, MessageType.INFO, accent=accent)
    
    def debug(self, text: str) -> None:
        """Display debug message"""
        self.message(text, MessageType.DEBUG)
    
    # ========== Panel Methods ==========
    
    def panel(
        self,
        content: str,
        title: str = "",
        border_style: str = "dark_orange",
        expand: bool = True,
        box_style=None,
        **kwargs,
    ) -> None:
        """Display content in a styled panel with rounded borders by default"""
        if box_style is None:
            box_style = box.ROUNDED
        self.console.print(Panel(
            content,
            title=title,
            border_style=border_style,
            expand=expand,
            box=box_style,
            **kwargs
        ))
    
    # ========== Table Methods ==========
    
    def create_table(
        self,
        title: str = "",
        columns: List[Dict[str, str]] = None,
        *,
        expand: bool = False,
        box_style=None,
        show_header: bool = True,
    ) -> Table:
        """Create a table with specified columns and shared defaults."""
        table = Table(
            title=title,
            expand=expand,
            box=box_style,
            show_header=show_header,
        )
        if columns:
            for col in columns:
                table.add_column(
                    col.get("name", ""),
                    style=col.get("style", "white"),
                    justify=col.get("justify", "left"),
                    no_wrap=col.get("no_wrap", False)
                )
        return table
    
    def display_table(self, table: Table) -> None:
        """Display a table"""
        self.console.print(table)
    
    def quick_table(self, title: str, headers: List[str], rows: List[List[str]],
                    header_style: str = "cyan") -> None:
        """Quick method to create and display a simple table"""
        table = Table(title=title)
        for header in headers:
            table.add_column(header, style=header_style)
        for row in rows:
            table.add_row(*row)
        self.display_table(table)

    def render_table(
        self,
        title: str,
        columns: List[str],
        rows: List[List[str]],
        *,
        column_styles: Optional[List[str]] = None,
        header_style: str = "cyan",
    ) -> None:
        """Render a table with shared styling to keep layouts consistent."""
        table = Table(title=title, show_header=True, header_style=header_style)
        for idx, header in enumerate(columns):
            kwargs: Dict[str, Any] = {}
            if column_styles and idx < len(column_styles):
                kwargs["style"] = column_styles[idx]
            table.add_column(header, **kwargs)
        for row in rows:
            table.add_row(*row)
        self.display_table(table)
    
    def dict_to_table(self, data: Dict[str, Any], title: str = "", 
                      key_header: str = "Key", value_header: str = "Value",
                      key_style: str = "cyan", value_style: str = "magenta") -> None:
        """Convert dictionary to a two-column table and display it"""
        table = self.create_table(title, [
            {"name": key_header, "style": key_style},
            {"name": value_header, "style": value_style}
        ])
        for key, value in data.items():
            table.add_row(str(key), str(value))
        self.display_table(table)
    
    # ========== Menu Methods ==========
    
    def display_menu(self, title: str, options: List[Tuple[str, str]],
                     show_numbers: bool = True) -> None:
        """Display a formatted menu with modern Anthropic-inspired styling"""
        table = Table(show_header=False, box=None, padding=(0, 1), expand=True)
        table.add_column(style="bold dark_orange", width=3, justify="right")
        table.add_column()

        for i, (key, description) in enumerate(options):
            if show_numbers and key.isdigit():
                table.add_row(f"{key}.", description)
            else:
                table.add_row(f"[{key}]", description)

        self.panel(table, title=title, border_style="dark_orange", expand=False)

    def interactive_menu(
        self,
        title: str,
        options: Sequence[Tuple[str, str]],
        instructions: str | None = None,
        *,
        show_keys: bool = False,
    ) -> str:
        """Display an interactive menu navigated via arrow keys.

        Returns the key associated with the selected option.
        """
        if not self.interactive:
            raise NonInteractiveError(
                "UIHelper.interactive_menu cannot run because this process has no console."
            )

        from vocab_builder.cli.navigation import interactive_select

        final_instructions = instructions or DEFAULT_MENU_INSTRUCTIONS

        return interactive_select(
            self.console,
            title,
            options,
            final_instructions,
            show_keys=show_keys,
        )
    
    # ========== Input Methods ==========
    
    # ========== Specialized Display Methods ==========
    
    def display_word_entry(
        self,
        word: str,
        word_type: str,
        definitions: List[str],
        examples: List[Tuple[str, str]],
    ) -> None:
        """Display a vocabulary entry using the shared full-width section layout."""
        table = self.create_table(
            columns=[
                {"name": "Category", "style": "cyan", "no_wrap": True},
                {"name": "Information", "style": "magenta"},
            ],
            expand=True,
            box_style=None,
        )

        table.add_row("Word Type", word_type)

        def_str = "\n".join([f"• {d}" for d in definitions])
        table.add_row("Definitions", def_str)

        ex_str = "\n".join([
            f"• {f}\n  {e if e.startswith('(') and e.endswith(')') else f'({e})'}" 
            for f, e in examples
        ])
        table.add_row("Examples", ex_str)

        panel = Panel(
            table,
            title=f"[bold #E67E50]Information for {word.capitalize()}[/]",
            border_style="dark_orange",
            box=box.ROUNDED,
            expand=True,
            padding=(0, 1),
        )
        self.console.print(panel)
    
    def display_latex_entry(self, latex_entry: str) -> None:
        """Display a LaTeX entry in a panel"""
        self.panel(latex_entry, title="Generated LaTeX Entry", border_style="dark_orange")
    
    def display_metrics(self, metrics: Dict[str, float]) -> None:
        """Display performance metrics in a formatted panel"""
        if not metrics:
            self.warning("LLM Performance metrics not available.")
            return

        ttft = metrics.get('ttft', -1)
        tps = metrics.get('tps', -1)
        tokens = metrics.get('tokens_out', -1)

        metrics_text = (
            f"TTFT: {ttft:.3f}s | "
            f"Output Tokens: {tokens} | "
            f"TPS: {tps:.1f}"
        )
        self.panel(metrics_text, title="LLM Performance", border_style="dim dark_orange")
    
    # ========== Utility Methods ==========
    
    def prompt(
        self,
        prompt: str = "",
        *,
        style: Optional[str] = None,
        default: Optional[str] = None,
    ) -> str:
        """Prompt for input using shared input helper."""
        if not self.interactive:
            raise NonInteractiveError(
                "UIHelper.prompt cannot run because this process has no console."
            )

        suffix = f" [{default}]" if default else ""
        label = f"{prompt}{suffix}".strip()
        if style and prompt:
            self.console.print(f"[{style}]{label}[/]", end=": ")
            prompt_text = ""
        else:
            prompt_text = f"{label}: " if label else ""

        try:
            response = read_line(prompt_text, console=self.console)
        except (EOFError, OSError):
            return Prompt.ask(
                prompt or "",
                default=default,
                console=self.console,
                show_default=default is not None,
            )

        response = response.strip()
        if not response and default is not None:
            return default
        return response

    def confirm(self, message: str, *, default: bool = True) -> bool:
        """Prompt user for a yes/no confirmation using visual selector."""
        if not self.interactive:
            raise NonInteractiveError(
                "UIHelper.confirm cannot run because this process has no console."
            )

        from vocab_builder.cli.navigation import interactive_confirm

        return interactive_confirm(self.console, message, default=default)
