"""Local Rich terminal frontend for the authoritative private VocabBuilder API.

The Mac launcher used to execute the whole TUI on the VM through SSH.  That
made every cursor key cross the Atlantic.  This module keeps rendering and
input local while reusing the existing mobile service as the remote domain
boundary; only operations that need authoritative data cross the network.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from vocab_builder.cli.navigation import interactive_confirm, interactive_select
from vocab_builder.ui_helper import read_line


_DEFAULT_HOST = "vocabbuilder-mobile"
_REQUEST_TIMEOUT = 30.0
_AI_TIMEOUT = 150.0


def escape(value: object) -> str:
    """Escape Rich opening brackets without importing optional markup internals."""
    return str(value).replace("[", r"\[")


class RemoteAPIError(RuntimeError):
    """A private API error safe to present in the local terminal."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "remote_error",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class RemoteAPI:
    """Small synchronous JSON client for the existing private mobile API."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = _REQUEST_TIMEOUT,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.language: Optional[str] = None
        self._opener = opener

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
        include_language: bool = True,
    ) -> Any:
        url = self._url(path, include_language=include_language)
        data = None
        headers = {"Accept": "application/json", "User-Agent": "VocabBuilder-Local-CLI/3"}
        if payload is not None:
            data = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener(request, timeout=timeout or self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            raise self._http_error(exc) from None
        except (TimeoutError, URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise RemoteAPIError(
                f"Cannot reach the private VocabBuilder service: {reason}",
                code="connection_failed",
            ) from None
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RemoteAPIError(
                "The private VocabBuilder service returned an unreadable response.",
                code="invalid_response",
            ) from None

    def download(self, path: str, destination: Path) -> Path:
        request = Request(
            self._url(path, include_language=True),
            headers={"User-Agent": "VocabBuilder-Local-CLI/3"},
        )
        try:
            with self._opener(request, timeout=_AI_TIMEOUT) as response:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as output:
                    shutil.copyfileobj(response, output)
        except HTTPError as exc:
            raise self._http_error(exc) from None
        except (TimeoutError, URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise RemoteAPIError(f"Could not download the generated file: {reason}") from None
        return destination

    def _url(self, path: str, *, include_language: bool) -> str:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if not include_language or not self.language:
            return url
        split = urlsplit(url)
        query = parse_qsl(split.query, keep_blank_values=True)
        query.append(("language", self.language))
        return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), split.fragment))

    @staticmethod
    def _http_error(exc: HTTPError) -> RemoteAPIError:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        if not isinstance(error, dict):
            error = {}
        message = str(error.get("message") or f"The private service returned HTTP {exc.code}.")
        return RemoteAPIError(
            message,
            code=str(error.get("code") or f"http_{exc.code}"),
            details=error,
        )


def resolve_base_url(
    host: str,
    *,
    explicit_url: Optional[str] = None,
    status_loader: Optional[Callable[[], Mapping[str, Any]]] = None,
) -> str:
    """Resolve a MagicDNS machine name to its certificate-bearing HTTPS name."""
    configured = (explicit_url or os.environ.get("VOCABBUILDER_REMOTE_URL", "")).strip()
    if configured:
        return configured.rstrip("/")
    clean_host = host.strip().rstrip(".")
    if clean_host.startswith(("http://", "https://")):
        return clean_host.rstrip("/")
    if "." in clean_host:
        return f"https://{clean_host}"
    loader = status_loader or _tailscale_status
    status = loader()
    peers = status.get("Peer", {})
    if isinstance(peers, dict):
        for peer in peers.values():
            if not isinstance(peer, dict):
                continue
            hostname = str(peer.get("HostName", "")).rstrip(".")
            dns_name = str(peer.get("DNSName", "")).rstrip(".")
            if clean_host in {hostname, dns_name, dns_name.split(".", 1)[0]} and dns_name:
                return f"https://{dns_name}"
    suffix = str(status.get("MagicDNSSuffix", "")).strip().strip(".")
    if suffix:
        return f"https://{clean_host}.{suffix}"
    raise RemoteAPIError(
        f"Tailscale could not resolve the private machine {clean_host!r}.",
        code="host_not_found",
    )


def _tailscale_status() -> Mapping[str, Any]:
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
    except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise RemoteAPIError(
            "Tailscale is unavailable. Connect this Mac to the tailnet and try again.",
            code="tailscale_unavailable",
        ) from exc
    return payload if isinstance(payload, dict) else {}


class RemoteCLI:
    """Local Rich UI that delegates authoritative operations to ``RemoteAPI``."""

    def __init__(
        self,
        api: RemoteAPI,
        *,
        console: Optional[Console] = None,
        requested_language: Optional[str] = None,
        requested_provider: Optional[str] = None,
        download_dir: Optional[Path] = None,
    ) -> None:
        self.api = api
        self.console = console or Console()
        self.requested_language = requested_language
        self.requested_provider = requested_provider
        self.download_dir = download_dir or Path(
            os.environ.get("VOCABBUILDER_DOWNLOAD_DIR", "~/Downloads")
        ).expanduser()
        self.status: dict[str, Any] = {}

    def run(self) -> None:
        try:
            catalog = self.api.request("/api/collections", include_language=False)
            collection = self._choose_collection(catalog)
            self.api.language = str(collection["language"])
            if self.requested_provider:
                self._call(
                    "/api/settings/provider",
                    method="POST",
                    payload={"provider": self.requested_provider},
                    label="Selecting provider…",
                    timeout=_AI_TIMEOUT,
                )
            self._welcome(collection)
            while True:
                self.status = self.api.request("/api/status")
                choice = self._main_menu()
                if choice == "exit":
                    self._goodbye()
                    return
                self._run_action(choice)
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Session closed.[/yellow]")
        except RemoteAPIError as exc:
            self._error(exc)

    def _choose_collection(self, catalog: Mapping[str, Any]) -> Mapping[str, Any]:
        collections = catalog.get("collections", [])
        choices = [item for item in collections if isinstance(item, dict)]
        if not choices:
            raise RemoteAPIError("The private service has no language collections.")
        if self.requested_language:
            for item in choices:
                if item.get("language") == self.requested_language:
                    return item
            raise RemoteAPIError(f"Unknown language collection: {self.requested_language}")
        default = str(catalog.get("default_language") or choices[0].get("language"))
        key = interactive_select(
            self.console,
            "Select Language",
            [
                (
                    str(item["language"]),
                    f"{escape(str(item['language_name']))} [dim]({escape(str(item['language']))})[/dim]",
                )
                for item in choices
            ],
            "Use ↑ and ↓ to choose a language. Press Enter to launch. Esc cancels.",
            default_key=default,
        )
        return next(item for item in choices if item.get("language") == key)

    def _welcome(self, collection: Mapping[str, Any]) -> None:
        language = str(collection.get("language_name", "Vocabulary"))
        provider = str(collection.get("provider", "AI unavailable"))
        count = int(collection.get("entry_count", 0))
        content = (
            f"[bold #E67E50]Welcome to the {escape(language)} Vocabulary Builder![/bold #E67E50]\n\n"
            f"[bold green]Your collection contains {count} words.[/bold green]\n"
            f"[bold cyan]Using LLM provider: {escape(provider)}[/bold cyan]\n"
            "[dim]The interface runs locally; authoritative data remains on the private VM.[/dim]"
        )
        self.console.print(Panel(content, title=f"{escape(language)} Vocab Builder", box=box.ROUNDED))

    def _main_menu(self) -> str:
        language = str(self.status.get("language_name", "Vocabulary"))
        count = int(self.status.get("entry_count", 0))
        ai = "Connected" if self.status.get("ai_available") else "Unavailable"
        self.console.print(
            Panel(
                f"[bold]Library:[/bold] {count} vocab words  |  [bold]AI:[/bold] {ai}",
                title="Status",
                border_style="dim dark_orange",
            )
        )
        options = [("add", f"Add {escape(language)} word")]
        if self.status.get("supports_translation"):
            options.append(("translate", "Translate text"))
        if self.status.get("supports_practice"):
            options.append(("composition", "Composition practice"))
        options.extend(
            [
                ("anki_tools", "Anki tools"),
                ("browse", "Browse vocabulary"),
                ("settings", "Settings & Configuration"),
                ("exit", "[bold yellow]Exit[/bold yellow]"),
            ]
        )
        return interactive_select(
            self.console,
            "Main Menu",
            options,
            "[↑↓] Navigate • [Enter] Select • [Esc] Exit",
        )

    def _run_action(self, choice: str) -> None:
        actions = {
            "add": self._capture,
            "translate": self._translate,
            "composition": self._practice,
            "anki_tools": self._anki,
            "browse": self._browse,
            "settings": self._settings,
        }
        action = actions.get(choice)
        if action is None:
            return
        try:
            action()
        except KeyboardInterrupt:
            return
        except RemoteAPIError as exc:
            self._error(exc)

    def _capture(self) -> None:
        language = str(self.status.get("language_name", "vocabulary"))
        text = self._prompt(f"\nEnter {language} text (Esc to cancel): ")
        if not text:
            return
        try:
            preview = self._preview_entry(text, "reject")
        except RemoteAPIError as exc:
            if exc.code != "duplicate_entry" or not isinstance(exc.details.get("existing_entry"), dict):
                raise
            existing = dict(exc.details["existing_entry"])
            self._show_entry(existing, title="Already in your collection")
            choice = interactive_select(
                self.console,
                "Existing Entry",
                [
                    ("keep", "Keep what I have"),
                    ("merge", "Look up and add new senses"),
                    ("variant", "Create a separate labelled variant"),
                    ("back", "Back to main menu"),
                ],
                "[↑↓] Navigate • [Enter] Select • [Esc] Go back",
            )
            if choice in {"keep", "back"}:
                return
            preview = self._preview_entry(text, choice)

        self._show_entry(preview, title="Vocabulary Preview")
        action = str(preview.get("duplicate_action", "new"))
        options: list[tuple[str, str]] = [("save", "Save this entry")]
        if preview.get("spelling_suggestion"):
            options.append(("original", f"Save original spelling: {escape(str(preview['original_input']))}"))
        if preview.get("route_recommended"):
            options.append(("translate", "Translate instead"))
        if action == "merge":
            added = len(preview.get("new_definitions", [])) or len(preview.get("new_examples", []))
            options[0] = ("save", f"Merge {added} new item{'s' if added != 1 else ''}")
        elif action == "variant" and preview.get("variant_word"):
            options[0] = ("save", f"Save as {escape(str(preview['variant_word']))}")
        options.append(("back", "Discard preview"))
        choice = interactive_select(
            self.console,
            "Confirm Entry",
            options,
            "[↑↓] Navigate • [Enter] Select • [Esc] Discard",
        )
        if choice == "translate":
            self._translate(initial_text=str(preview.get("original_input", text)), initial_direction="target_to_eng")
            return
        if choice == "back":
            return
        receipt = self._call(
            "/api/save",
            method="POST",
            payload={"token": preview["token"], "use_original": choice == "original"},
            label="Saving…",
        )
        self.console.print(f"[bold green]✓ {escape(str(receipt['word']))} is saved.[/bold green]")

    def _preview_entry(self, text: str, duplicate_action: str) -> dict[str, Any]:
        result = self._call(
            "/api/preview",
            method="POST",
            payload={"text": text, "duplicate_action": duplicate_action},
            label="Looking it up…",
            timeout=_AI_TIMEOUT,
        )
        return dict(result)

    def _translate(
        self,
        *,
        initial_text: Optional[str] = None,
        initial_direction: Optional[str] = None,
    ) -> None:
        text_seed = initial_text
        direction_seed = initial_direction
        while True:
            description = self.api.request("/api/translations")
            directions = [item for item in description.get("directions", []) if isinstance(item, dict)]
            options = []
            if description.get("auto_available"):
                options.append(("auto", "Intelligent language detection"))
            options.extend(
                (
                    str(item["id"]),
                    f"{escape(str(item['source_label']))} → {escape(str(item['target_label']))}",
                )
                for item in directions
            )
            options.append(("back", "Back to main menu"))
            if direction_seed and any(key == direction_seed for key, _ in options):
                direction = direction_seed
            else:
                direction = interactive_select(
                    self.console,
                    "Translation Direction",
                    options,
                    "[↑↓] Navigate • [Enter] Select • [Esc] Go back",
                )
            direction_seed = None
            if direction == "back":
                return
            source = text_seed or self._prompt("Text (Esc to cancel): ")
            text_seed = None
            if not source:
                return
            preview = self._call(
                "/api/translations/preview",
                method="POST",
                payload={"direction": direction, "text": source},
                label="Translating…",
                timeout=_AI_TIMEOUT,
            )
            self._show_translation(preview)
            choice = interactive_select(
                self.console,
                "Translation Preview",
                [
                    ("save", "Save translation pair"),
                    ("another", "Translate another sentence"),
                    ("back", "Return to main menu"),
                ],
                "[↑↓] Navigate • [Enter] Select • [Esc] Go back",
            )
            if choice == "save":
                receipt = self._call(
                    "/api/translations/save",
                    method="POST",
                    payload={"token": preview["token"]},
                    label="Saving…",
                )
                message = "already existed" if receipt.get("status") == "duplicate" else "is saved"
                self.console.print(f"[bold green]✓ Translation {message}.[/bold green]")
                return
            if choice == "back":
                return

    def _practice(self) -> None:
        description = self.api.request("/api/practice")
        if not description.get("available"):
            self.console.print("[yellow]Composition practice is unavailable.[/yellow]")
            return
        options = [
            (str(item["id"]), escape(str(item["label"])))
            for item in description.get("modes", [])
            if isinstance(item, dict)
        ]
        options.append(("back", "Back to main menu"))
        mode = interactive_select(
            self.console,
            "Composition Practice",
            options,
            "[↑↓] Navigate • [Enter] Select • [Esc] Go back",
        )
        if mode == "back":
            return
        used: list[str] = []
        session_id: Optional[str] = None
        while True:
            prompt = self._call(
                "/api/practice/prompt",
                method="POST",
                payload={"mode": mode, "exclude_keys": used, "session_id": session_id},
                label="Preparing practice…",
            )
            session_id = str(prompt["session_id"])
            for word in prompt.get("words", []):
                key = str(word.get("key", ""))
                if key and key not in used:
                    used.append(key)
            self._show_practice_prompt(prompt)
            answer = self._read_multiline("Composition (Esc to cancel): ")
            if not answer:
                return
            feedback = self._call(
                "/api/practice/grade",
                method="POST",
                payload={"token": prompt["token"], "text": answer},
                label="Coaching…",
                timeout=_AI_TIMEOUT,
            )
            self._show_feedback(feedback)
            choice = interactive_select(
                self.console,
                "Practice",
                [("another", "Another prompt"), ("back", "Back to main menu")],
                "[↑↓] Navigate • [Enter] Select • [Esc] Go back",
            )
            if choice == "back":
                return

    def _browse(self) -> None:
        while True:
            choice = interactive_select(
                self.console,
                "Browse Vocabulary",
                [
                    ("search", "Search"),
                    ("all", "Browse alphabetical index"),
                    ("random", "Show a random entry"),
                    ("stats", "Collection statistics"),
                    ("back", "Back to main menu"),
                ],
                "[↑↓] Navigate • [Enter] Select • [Esc] Go back",
            )
            if choice == "back":
                return
            if choice == "random":
                self._show_entry(self.api.request("/api/library/random"), title="Random Entry")
            elif choice == "stats":
                self._show_stats(self.api.request("/api/library/stats"))
            else:
                query = self._prompt("Search: ") if choice == "search" else ""
                if choice == "search" and not query:
                    continue
                self._browse_pages(query or "")

    def _browse_pages(self, query: str) -> None:
        page = 1
        while True:
            encoded = urlencode({"q": query, "page": page, "page_size": 30})
            payload = self.api.request(f"/api/library?{encoded}")
            items = [item for item in payload.get("items", []) if isinstance(item, dict)]
            if not items:
                self.console.print("[yellow]No matching vocabulary entries.[/yellow]")
                return
            options = [
                (f"entry:{index}", escape(str(item.get("word", ""))))
                for index, item in enumerate(items)
            ]
            if page > 1:
                options.append(("previous", "Previous page"))
            if payload.get("has_more"):
                options.append(("next", "Next page"))
            options.append(("back", "Back"))
            choice = interactive_select(
                self.console,
                f"Vocabulary ({payload.get('total', len(items))} entries)",
                options,
                "[↑↓] Navigate • [Enter] Open • [Esc] Go back",
            )
            if choice == "back":
                return
            if choice == "next":
                page += 1
            elif choice == "previous":
                page = max(1, page - 1)
            else:
                self._show_entry(items[int(choice.split(":", 1)[1])], title="Vocabulary Entry")

    def _anki(self) -> None:
        while True:
            status = self.api.request("/api/anki")
            pending = int(status.get("pending_count", 0))
            stale = int(status.get("stale_count", 0))
            self.console.print(
                Panel(
                    f"[bold]Ready to export:[/bold] {pending}  |  [bold]Needs attention:[/bold] {stale}",
                    title="Anki Status",
                )
            )
            options = [
                ("incremental", "Export new words"),
                ("reconcile", "Reconcile missing cards"),
                ("rebuild", "Rebuild complete deck"),
                ("selected", "Export selected words"),
            ]
            if stale:
                options.append(("remove_stale", "Remove stale tracking records"))
            options.append(("back", "Back to main menu"))
            choice = interactive_select(
                self.console,
                "Anki Tools",
                options,
                "[↑↓] Navigate • [Enter] Select • [Esc] Go back",
            )
            if choice == "back":
                return
            if choice == "remove_stale":
                if interactive_confirm(self.console, "Remove stale tracking records?", default=False):
                    result = self._call("/api/anki/remove-stale", method="POST", label="Cleaning…")
                    self.console.print(f"[green]Removed {result.get('removed', 0)} records.[/green]")
                continue
            selected: list[str] = []
            if choice == "selected":
                raw = self._prompt("Comma-separated words: ")
                selected = [word.strip() for word in (raw or "").split(",") if word.strip()]
                if not selected:
                    continue
            if choice == "rebuild" and not interactive_confirm(
                self.console, "Rebuild the complete deck?", default=False
            ):
                continue
            result = self._call(
                "/api/anki/export",
                method="POST",
                payload={"mode": choice, "selected_words": selected, "include_mistakes": False},
                label="Building deck…",
                timeout=_AI_TIMEOUT,
            )
            filename = Path(str(result["filename"])).name
            destination = self.download_dir / filename
            self.api.download(str(result["download_url"]), destination)
            self.console.print(f"[bold green]✓ Downloaded to {escape(str(destination))}[/bold green]")

    def _settings(self) -> None:
        while True:
            settings = self.api.request("/api/settings")
            available = "Connected" if settings.get("available") else "Unavailable"
            self.console.print(
                Panel(
                    f"[bold]{escape(str(settings.get('label', 'AI provider')))}[/bold]\n"
                    f"Status: {available}\nModel: {escape(str(settings.get('model', '')))}",
                    title="AI Settings",
                )
            )
            options = [("test", "Test connection")]
            options.extend(
                (f"provider:{item['id']}", escape(str(item["name"])))
                for item in settings.get("providers", [])
                if isinstance(item, dict)
            )
            options.append(("back", "Back to main menu"))
            choice = interactive_select(
                self.console,
                "Settings & Configuration",
                options,
                "[↑↓] Navigate • [Enter] Select • [Esc] Go back",
            )
            if choice == "back":
                return
            if choice == "test":
                result = self._call(
                    "/api/settings/test",
                    method="POST",
                    label="Testing connection…",
                    timeout=_AI_TIMEOUT,
                )
            else:
                provider = choice.split(":", 1)[1]
                key = getpass.getpass("New API key (Enter to use stored key): ").strip() or None
                result = self._call(
                    "/api/settings/provider",
                    method="POST",
                    payload={"provider": provider, "api_key": key},
                    label="Configuring provider…",
                    timeout=_AI_TIMEOUT,
                )
            self.console.print(f"[green]{escape(str(result.get('message', 'Provider ready.')))}[/green]")

    def _call(
        self,
        path: str,
        *,
        method: str,
        payload: Optional[Mapping[str, Any]] = None,
        label: str,
        timeout: float = _REQUEST_TIMEOUT,
    ) -> Any:
        with self.console.status(label, spinner="dots"):
            return self.api.request(path, method=method, payload=payload, timeout=timeout)

    def _prompt(self, prompt: str) -> Optional[str]:
        try:
            line = read_line(prompt, console=self.console)
        except (EOFError, KeyboardInterrupt):
            return None
        if "\x1b" in line:
            return None
        clean = line.strip()
        return clean or None

    def _read_multiline(self, prompt: str) -> Optional[str]:
        lines: list[str] = []
        while True:
            try:
                line = read_line(prompt if not lines else "", console=self.console)
            except (EOFError, KeyboardInterrupt):
                return None
            if "\x1b" in line:
                return None
            if not line.strip():
                return "\n".join(lines).strip() or None
            lines.append(line.rstrip())

    def _show_entry(self, entry: Mapping[str, Any], *, title: str) -> None:
        table = Table.grid(padding=(0, 1))
        table.add_column(style="bold dark_orange", no_wrap=True)
        table.add_column()
        word = entry.get("variant_word") or entry.get("word") or entry.get("original_input", "")
        table.add_row("Word", Text(str(word)))
        table.add_row("Type", Text(str(entry.get("word_type", "Unknown"))))
        definitions = [str(value) for value in entry.get("definitions", [])]
        table.add_row("Definitions", Text("\n".join(f"• {value}" for value in definitions)))
        examples = entry.get("examples", [])
        rendered_examples = []
        for example in examples:
            if isinstance(example, dict):
                rendered_examples.append(f"{example.get('source', '')}\n  → {example.get('target', '')}")
            elif isinstance(example, (list, tuple)) and len(example) >= 2:
                rendered_examples.append(f"{example[0]}\n  → {example[1]}")
        if rendered_examples:
            table.add_row("Examples", Text("\n\n".join(rendered_examples)))
        self.console.print(Panel(table, title=title, border_style="dark_orange", box=box.ROUNDED))

    def _show_translation(self, preview: Mapping[str, Any]) -> None:
        table = Table.grid(padding=(0, 1))
        table.add_column(style="bold dark_orange", no_wrap=True)
        table.add_column()
        table.add_row(str(preview.get("source_label", "Source")), Text(str(preview.get("source_text", ""))))
        table.add_row(str(preview.get("target_label", "Target")), Text(str(preview.get("target_text", ""))))
        notes = [
            str(preview.get("notes") or ""),
            "Review carefully: mixed-language source detected." if preview.get("suspicious") else "",
            f"Ignored fragment: {preview['dropped_fragment']}" if preview.get("dropped_fragment") else "",
        ]
        clean_notes = [value for value in notes if value]
        if clean_notes:
            table.add_row("Notes", Text(" ".join(clean_notes)))
        self.console.print(Panel(table, title="Translation", border_style="dark_orange"))

    def _show_practice_prompt(self, prompt: Mapping[str, Any]) -> None:
        if prompt.get("mode") == "reverse":
            content = (
                f"{prompt.get('source_english', '')}\n\n"
                f"Use: {prompt.get('words', [{}])[0].get('word', '')}"
            )
        else:
            content = "\n".join(
                f"• {word.get('word', '')} — {word.get('first_definition', '')}"
                for word in prompt.get("words", [])
            )
        self.console.print(Panel(Text(content), title="Composition Prompt", border_style="dark_orange"))

    def _show_feedback(self, feedback: Mapping[str, Any]) -> None:
        lines = [str(feedback.get("corrected_text") or "No corrected text returned.")]
        if feedback.get("english_gloss"):
            lines.extend(["", str(feedback["english_gloss"])])
        verdicts = feedback.get("word_verdicts", {})
        if isinstance(verdicts, dict) and verdicts:
            lines.extend(["", *[f"{word}: {verdict}" for word, verdict in verdicts.items()]])
        for correction in feedback.get("corrections", []):
            if isinstance(correction, dict):
                lines.append(
                    f"{correction.get('original', '')} → {correction.get('replacement', '')}: "
                    f"{correction.get('why', '')}"
                )
        self.console.print(Panel(Text("\n".join(lines)), title="Coach's Feedback", border_style="dark_orange"))

    def _show_stats(self, stats: Mapping[str, Any]) -> None:
        lines = [
            f"Total entries: {stats.get('total', 0)}",
            f"With examples: {stats.get('with_examples', 0)}",
            f"With multiple senses: {stats.get('with_multiple_senses', 0)}",
        ]
        lines.extend(
            f"{item.get('name', 'Unknown')}: {item.get('count', 0)}"
            for item in stats.get("types", [])
            if isinstance(item, dict)
        )
        self.console.print(Panel(Text("\n".join(lines)), title="Collection Statistics"))

    def _error(self, exc: RemoteAPIError) -> None:
        self.console.print(f"[bold #ff6b6b]✗ {escape(str(exc))}[/bold #ff6b6b]")

    def _goodbye(self) -> None:
        self.console.print(Panel("Thank you for using VocabBuilder!", title="Goodbye!"))


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local Rich frontend for private VocabBuilder")
    parser.add_argument("--language", "-l", type=str.lower)
    parser.add_argument("--provider", "-p", choices=("gemini", "claude"))
    parser.add_argument("--remote-host", default=os.environ.get("VOCABBUILDER_REMOTE_HOST", _DEFAULT_HOST))
    parser.add_argument("--remote-url", default=os.environ.get("VOCABBUILDER_REMOTE_URL"))
    parser.add_argument("--request-timeout", type=float, default=_REQUEST_TIMEOUT)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = _parse_args(argv)
    try:
        base_url = resolve_base_url(args.remote_host, explicit_url=args.remote_url)
        api = RemoteAPI(base_url, timeout=args.request_timeout)
        RemoteCLI(
            api,
            requested_language=args.language,
            requested_provider=args.provider,
        ).run()
    except RemoteAPIError as exc:
        Console().print(f"[bold #ff6b6b]✗ {escape(str(exc))}[/bold #ff6b6b]")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()


__all__ = ["RemoteAPI", "RemoteAPIError", "RemoteCLI", "main", "resolve_base_url"]
