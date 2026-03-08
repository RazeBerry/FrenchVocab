# ESC Button Behavior Analysis (VocabBuilder)

## 🔍 Investigation Summary

**Question**: Does the ESC button go back to the previous menu?

**Answer**: **YES, by design!** The ESC button behavior is contextual and intentional.

---

## ✅ Current Implementation

### Navigation System (`vocab_builder/cli/navigation.py:89-90`)

When ESC is pressed in any interactive menu:
```python
elif key in {"escape", "ctrl_c"}:
    raise KeyboardInterrupt
```

The navigation system raises `KeyboardInterrupt`, which is then caught by each menu handler.

---

## 🎯 Contextual Behavior

### 1. **Main Menu** (`vocab_builder/core/vocab.py`)

```python
def show_menu(self):
    # ... menu options ...
    try:
        return self.ui.interactive_menu(
            "Main Menu",
            options,
            "Use ↑ and ↓ to navigate. Press Enter to choose. Esc exits.",
        )
    except KeyboardInterrupt:
        return "exit"  # ← ESC exits the application
```

**Behavior**: ESC → exits the entire application
**Rationale**: User at top level wants to quit

---

### 2. **Translation Submenu** (`vocab_builder/core/vocab.py`)

```python
def show_translation_menu(self) -> str:
    """Display translation direction submenu."""
    # ... menu options with "back" option ...
    try:
        return self.ui.interactive_menu(
            "Translation Direction",
            options,
            "Choose which direction to translate.",
        )
    except KeyboardInterrupt:
        return "back"  # ← ESC returns to main menu
```

**Behavior**: ESC → returns to main menu
**Rationale**: User in submenu wants to go back

---

### 3. **Anki Tools Submenu** (`vocab_builder/core/vocab.py`)

```python
def show_anki_menu(self) -> str:
    """Display the nested Anki submenu and return the selected option."""
    # ... menu options with "back" option ...
    try:
        return self.ui.interactive_menu(
            "Anki Tools",
            options,
            "Use ↑ and ↓ to navigate. Press Enter to select. Esc returns.",
        )
    except KeyboardInterrupt:
        return "back"  # ← ESC returns to main menu
```

**Behavior**: ESC → returns to main menu
**Rationale**: User in submenu wants to go back

---

## 📊 Menu Flow Diagram

```
┌─────────────────────────────────────┐
│         Main Menu                   │
│  - Add word                         │
│  - Translate ─────────┐             │
│  - Anki tools ───┐    │             │
│  - Display       │    │             │
│  - Settings      │    │             │
│  - Exit          │    │             │
│                  │    │             │
│  [ESC = Exit App]│    │             │
└──────────────────┼────┼─────────────┘
                   │    │
                   │    └──────────────┐
                   │                   │
        ┌──────────▼─────────┐  ┌──────▼──────────────┐
        │  Anki Tools Menu   │  │ Translation Menu    │
        │  - Export          │  │ - Eng → French      │
        │  - Reconcile       │  │ - French → Eng      │
        │  - Back            │  │ - Back              │
        │                    │  │                     │
        │  [ESC = Back]      │  │ [ESC = Back]        │
        └────────────────────┘  └─────────────────────┘
```

---

## 🎨 User Instructions (Current)

The instructions shown to users are **accurate**:

- **Main Menu**: `"Use ↑ and ↓ to navigate. Press Enter to choose. Esc exits."`
- **Anki Menu**: `"Use ↑ and ↓ to navigate. Press Enter to select. Esc returns."`
- **Translation Menu**: `"Choose which direction to translate."` (no ESC mention, but behavior is "back")

---

## 🤔 Potential Issues

### Issue 1: Inconsistent Instructions
The Translation Menu doesn't mention ESC behavior in its instructions, while Anki menu does.

**Suggestion**: Update translation menu instructions to match:
```python
"Choose which direction to translate. Esc returns."
```

### Issue 2: Main Menu Redundancy
The main menu has both:
- An explicit "Exit" option
- ESC key that also exits

**This is actually GOOD UX**:
- Mouse/number users: Select "Exit" option
- Keyboard users: Quick ESC to exit
- Redundancy prevents frustration

### Issue 3: User Expectation Mismatch?
If the user reports "ESC doesn't go back", they might be:
1. **On the main menu** → ESC exits (not "back") ← This is intentional!
2. **Experiencing a bug** → ESC not working at all
3. **Expecting different behavior** → ESC should do nothing on main menu

---

## ✅ Verification Checklist

Test these scenarios:

- [ ] **Main Menu + ESC**: Should exit application
- [ ] **Translation Submenu + ESC**: Should return to main menu
- [ ] **Anki Submenu + ESC**: Should return to main menu
- [ ] **Any menu + Ctrl+C**: Should raise KeyboardInterrupt (same as ESC)

---

## 🎯 Recommended Actions

### 1. **If behavior is working correctly:**
   - ✅ Keep current implementation
   - ✅ Update translation menu instructions to mention ESC
   - ✅ Clarify to user this is intentional design

### 2. **If ESC isn't working at all:**
   - 🔧 Check terminal compatibility
   - 🔧 Test _read_key() functions (POSIX vs Windows)
   - 🔧 Verify no exception swallowing

### 3. **If user wants different behavior:**
   Discuss options:
   - **Option A**: ESC on main menu does nothing (stays in menu)
   - **Option B**: ESC always goes "back" (need confirmation dialog to exit)
   - **Option C**: Keep current (ESC exits from main, backs from subs)

---

## 💡 Design Philosophy

The current ESC behavior follows **standard CLI conventions**:

✅ **Vim/Emacs style**: ESC cancels/goes back in context
✅ **Terminal tools**: ESC exits at top level
✅ **Progressive disclosure**: Deeper in menu = ESC goes back; at root = ESC exits

**This is intentional, thoughtful UX design!** 🎯

---

## 📝 Code Locations

| Component | File | Lines |
|-----------|------|-------|
| ESC key detection | `vocab_builder/cli/navigation.py` | 89-90 |
| Main menu handler | `vocab_builder/core/vocab.py` | `show_menu()` |
| Translation submenu | `vocab_builder/core/vocab.py` | `show_translation_menu()` |
| Anki submenu | `vocab_builder/core/vocab.py` | `show_anki_menu()` |

---

## 🆕 2025-11-03 Update

- macOS/Linux now read directly from the TTY file descriptor and check for follow-up bytes immediately before falling back to a two-stage poll (0 ms + 15 ms, then 30 ms). ANSI (`ESC [A/B/C/D`) and application-cursor (`ESC OA/OB/OC/OD`) arrow sequences are both recognised, eliminating the accidental exits without adding perceivable delay.
- Windows keeps the conservative `msvcrt.getwch()` handling until we can validate ConPTY behaviour; small clean-up only.

---

*Investigation completed: 2025-11-03*
