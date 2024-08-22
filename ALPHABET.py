import os
import logging
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Header, Footer, Input, Static
from textual.reactive import reactive

# Set up logging
log_file = os.path.join(os.path.dirname(__file__), 'french_words_app.log')
logging.basicConfig(filename=log_file, level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

french_words = [
    'Bonjour', 'Merci', 'S\'il vous plaît', 'Au revoir', 'Oui',
    'Non', 'Comment ça va?', 'Bien', 'Mal', 'À bientôt'
]


class FrenchWordsApp(App):
    CSS = """
    #all_words, #filtered_words {
        height: 1fr;
        width: 100%;
        border: solid green;
    }

    #user_input {
        dock: bottom;
    }

    .label {
        padding: 1 2;
        background: $accent;
        color: $text;
    }
    """

    BINDINGS = [("ctrl+c", "quit", "Quit")]

    user_input = reactive("")
    is_listening = reactive(True)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static(", ".join(french_words), id="all_words"),
            Static(id="filtered_words"),
            Static(id="status"),
        )
        yield Input(id="user_input", placeholder="Type to filter...")
        yield Footer()

    def on_mount(self):
        self.query_one("#user_input").focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.user_input = event.value
        self.filter_words()

    def filter_words(self):
        logging.debug(f"Filtering words with query: {self.user_input}")
        try:
            filtered = [word for word in french_words if self.user_input.lower() in word.lower()]
            logging.debug(f"Filtered words: {filtered}")
            self.query_one("#filtered_words").update(", ".join(filtered))
        except Exception as e:
            logging.error(f"Error in filter_words: {str(e)}")

    def on_key(self, event):
        if event.key == "tab":
            self.is_listening = not self.is_listening
            self.update_status()
            return

        if self.is_listening:
            self.query_one("#user_input").focus()
        else:
            self.query_one("#user_input").blur()

    def update_status(self):
        status = f"Listening: {'Yes' if self.is_listening else 'No'} (Press Tab to toggle)"
        self.query_one("#status").update(status)

    def on_mount(self):
        self.update_status()


if __name__ == "__main__":
    try:
        app = FrenchWordsApp()
        app.run()
    except Exception as e:
        logging.critical(f"Critical error in main: {str(e)}")