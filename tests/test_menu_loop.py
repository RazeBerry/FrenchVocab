from vocab_builder.core.menu_loop import main_menu_loop


class _MenuApp:
    def __init__(self):
        self.entry_count = 0
        self.persisted_count = 444
        self.eng_to_target_translator = None
        self.target_to_eng_translator = None
        self.auto_translator = None
        self.welcome_count = None
        self.menu_counts = []
        self._choices = iter(("add", "exit"))

    def count_entries(self):
        return self.persisted_count

    def welcome_screen(self):
        self.welcome_count = self.entry_count

    def show_menu(self):
        self.menu_counts.append(self.entry_count)
        return next(self._choices)

    def handle_new_word_entry(self):
        self.persisted_count += 1

    def exit_screen(self):
        pass

    def show_translation_menu(self):
        raise AssertionError("translation menu should not be opened")

    def handle_composition(self):
        raise AssertionError("composition should not be opened")

    def handle_anki_tools(self):
        raise AssertionError("Anki tools should not be opened")

    def browse_vocabulary(self):
        raise AssertionError("browser should not be opened")

    def show_settings_screen(self):
        raise AssertionError("settings should not be opened")


def test_menu_refreshes_persisted_count_before_welcome_and_after_actions():
    app = _MenuApp()

    main_menu_loop(app)

    assert app.welcome_count == 444
    assert app.menu_counts == [444, 445]
