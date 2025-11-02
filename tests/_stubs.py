import sys
import types


def install_basic_stubs():
    # Stub for genanki to bypass dependency during import
    if 'genanki' not in sys.modules:
        genanki_stub = types.ModuleType('genanki')
        class _Dummy:
            def __init__(self, *args, **kwargs):
                pass
        class _DummyPackage:
            def __init__(self, deck):
                self.deck = deck
            def write_to_file(self, *_args, **_kwargs):
                pass
        genanki_stub.Model = _Dummy
        genanki_stub.Deck = _Dummy
        genanki_stub.Note = _Dummy
        genanki_stub.Package = _DummyPackage
        sys.modules['genanki'] = genanki_stub

    # Stub for rich.* modules
    def _install_rich():
        rc = types.ModuleType('rich.console')
        class _Console:
            def print(self, *args, **kwargs): pass
            def status(self, *_a, **_k):
                class _Ctx:
                    def __enter__(self): return self
                    def __exit__(self, exc_type, exc, tb): return False
                return _Ctx()
            def input(self, *args, **kwargs): return ""
        rc.Console = _Console
        rc.RenderableType = object
        sys.modules['rich.console'] = rc

        rp = types.ModuleType('rich.progress')
        class _Progress:
            def __enter__(self): return self
            def __exit__(self, exc_type, exc, tb): return False
            def add_task(self, *_a, **_k): return 1
            def advance(self, *_a, **_k): pass
            def update(self, *_a, **_k): pass
        rp.Progress = _Progress
        sys.modules['rich.progress'] = rp

        rpr = types.ModuleType('rich.prompt')
        class _Prompt:
            @staticmethod
            def ask(_m, choices=None, default=None):
                return default or (choices[0] if choices else "")
        class _Confirm:
            @staticmethod
            def ask(_m, default=False): return default
        rpr.Prompt = _Prompt
        rpr.Confirm = _Confirm
        sys.modules['rich.prompt'] = rpr

        rt = types.ModuleType('rich.table')
        class _Table:
            def __init__(self, *a, **k): pass
            def add_column(self, *a, **k): pass
            def add_row(self, *a, **k): pass
        rt.Table = _Table
        sys.modules['rich.table'] = rt

        rpa = types.ModuleType('rich.panel')
        class _Panel:
            def __init__(self, *a, **k): pass
        rpa.Panel = _Panel
        sys.modules['rich.panel'] = rpa

        rtx = types.ModuleType('rich.text')

        class _Text:
            pass

        rtx.Text = _Text
        sys.modules['rich.text'] = rtx

        rs = types.ModuleType('rich.syntax')
        class _Syntax:
            def __init__(self, *args, **kwargs):
                pass
        rs.Syntax = _Syntax
        sys.modules['rich.syntax'] = rs
    _install_rich()

    # Stub keyring
    if 'keyring' not in sys.modules:
        keyring_stub = types.ModuleType('keyring')
        sys.modules['keyring'] = keyring_stub
    if 'keyring.errors' not in sys.modules:
        ke = types.ModuleType('keyring.errors')

        class KeyringError(Exception):
            pass

        setattr(ke, 'KeyringError', KeyringError)
        sys.modules['keyring.errors'] = ke

    # Stub llm_client to avoid SDK imports
    if 'llm_client' not in sys.modules:
        ll = types.ModuleType('llm_client')
        class _LLMClient:
            def stream(self, _prompt: str):
                yield ""
            def model_label(self) -> str:
                return "Stub LLM"
        class _GeminiClient(_LLMClient):
            pass
        class _ProviderFactory:
            @staticmethod
            def create(_provider_name: str, _api_key: str = None):
                return _GeminiClient()
            @staticmethod
            def default_provider() -> str:
                return 'gemini'
        ll.LLMClient = _LLMClient
        ll.GeminiClient = _GeminiClient
        ll.ProviderFactory = _ProviderFactory
        sys.modules['llm_client'] = ll
