import sys
import types


def _install_genanki_stub() -> None:
    if "genanki" in sys.modules:
        return

    genanki_stub = types.ModuleType("genanki")

    class _Dummy:
        def __init__(self, *args, **kwargs):
            if "fields" in kwargs:
                self.fields = kwargs["fields"]
                self.sort_field = self.fields[0] if self.fields else ""

    class _DummyPackage:
        def __init__(self, deck):
            self.deck = deck

        def write_to_file(self, *_args, **_kwargs):
            pass

    genanki_stub.Model = _Dummy
    genanki_stub.Deck = _Dummy
    genanki_stub.Note = _Dummy
    genanki_stub.Package = _DummyPackage
    sys.modules["genanki"] = genanki_stub


def _install_rich_console_stub() -> None:
    rc = types.ModuleType("rich.console")

    class _Console:
        def print(self, *args, **kwargs):
            pass

        def status(self, *_a, **_k):
            class _Ctx:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            return _Ctx()

        def input(self, *args, **kwargs):
            return ""

    rc.Console = _Console
    rc.RenderableType = object
    sys.modules["rich.console"] = rc


def _install_rich_progress_stub() -> None:
    rp = types.ModuleType("rich.progress")

    class _Progress:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def add_task(self, *_a, **_k):
            return 1

        def advance(self, *_a, **_k):
            pass

        def update(self, *_a, **_k):
            pass

    rp.Progress = _Progress
    sys.modules["rich.progress"] = rp


def _install_rich_prompt_stub() -> None:
    rpr = types.ModuleType("rich.prompt")

    class _Prompt:
        @staticmethod
        def ask(_m, choices=None, default=None):
            return default or (choices[0] if choices else "")

    class _Confirm:
        @staticmethod
        def ask(_m, default=False):
            return default

    rpr.Prompt = _Prompt
    rpr.Confirm = _Confirm
    sys.modules["rich.prompt"] = rpr


def _install_rich_table_stub() -> None:
    rt = types.ModuleType("rich.table")

    class _Table:
        def __init__(self, *a, **k):
            pass

        def add_column(self, *a, **k):
            pass

        def add_row(self, *a, **k):
            pass

    rt.Table = _Table
    sys.modules["rich.table"] = rt


def _install_rich_panel_stub() -> None:
    rpa = types.ModuleType("rich.panel")

    class _Panel:
        def __init__(self, *a, **k):
            pass

    rpa.Panel = _Panel
    sys.modules["rich.panel"] = rpa


def _install_rich_text_stub() -> None:
    rtx = types.ModuleType("rich.text")

    class _Text:
        pass

    rtx.Text = _Text
    sys.modules["rich.text"] = rtx


def _install_rich_syntax_stub() -> None:
    rs = types.ModuleType("rich.syntax")

    class _Syntax:
        def __init__(self, *args, **kwargs):
            pass

    rs.Syntax = _Syntax
    sys.modules["rich.syntax"] = rs


def _install_rich_stubs() -> None:
    _install_rich_console_stub()
    _install_rich_progress_stub()
    _install_rich_prompt_stub()
    _install_rich_table_stub()
    _install_rich_panel_stub()
    _install_rich_text_stub()
    _install_rich_syntax_stub()


def _install_keyring_stub() -> None:
    keyring_stub = sys.modules.get("keyring")
    if keyring_stub is None:
        keyring_stub = types.ModuleType("keyring")
        sys.modules["keyring"] = keyring_stub

    if not hasattr(keyring_stub, "_store"):
        keyring_stub._store = {}

    def _kr_get_password(service, name):
        return keyring_stub._store.get((service, name))

    def _kr_set_password(service, name, value):
        keyring_stub._store[(service, name)] = value

    def _kr_delete_password(service, name):
        keyring_stub._store.pop((service, name), None)

    keyring_stub.get_password = _kr_get_password
    keyring_stub.set_password = _kr_set_password
    keyring_stub.delete_password = _kr_delete_password

    if "keyring.errors" not in sys.modules:
        ke = types.ModuleType("keyring.errors")

        class KeyringError(Exception):
            pass

        setattr(ke, "KeyringError", KeyringError)
        sys.modules["keyring.errors"] = ke


def _install_llm_client_stub() -> None:
    if "vocab_builder.llm_client" in sys.modules:
        return

    ll = types.ModuleType("vocab_builder.llm_client")

    class _LLMClient:
        def stream(self, _prompt: str, *, thinking_level: str = "low"):
            yield ""

        def model_label(self) -> str:
            return "Stub LLM"

        def verify_credentials(self, timeout: float = 5.0):  # noqa: ARG002 - stubbed signature
            return True

    class _GeminiClient(_LLMClient):
        pass

    class _ProviderFactory:
        @staticmethod
        def create(_provider_name: str, _api_key: str = None):
            return _GeminiClient()

        @staticmethod
        def default_provider() -> str:
            return "gemini"

    ll.LLMClient = _LLMClient
    ll.GeminiClient = _GeminiClient
    ll.ProviderFactory = _ProviderFactory
    sys.modules["vocab_builder.llm_client"] = ll
    # Legacy alias for backward compatibility
    sys.modules["llm_client"] = ll


def install_basic_stubs():
    _install_genanki_stub()
    _install_rich_stubs()
    _install_keyring_stub()
    _install_llm_client_stub()
