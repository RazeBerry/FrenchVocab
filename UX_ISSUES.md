# Major UX Issues - FrenchVocab Application

**Generated:** 2025-11-05
**Total Major Issues:** 22

---

## Navigation Issues (3)

### 1. ESC behavior not mentioned in translation menu instructions
- **Location:** `core/vocab.py:1088-1093`
- **Issue:** Translation menu doesn't mention ESC behavior in instructions
- **Current:** "Choose which direction to translate."
- **Should be:** "Choose which direction to translate. Esc returns."
- **Impact:** User confusion about navigation options

### 2. Fallback (non-TTY) menu has no cancel mechanism
- **Location:** `cli/navigation.py:112-148`
- **Issue:**
  - Fallback (non-TTY) mode displays numbered menu but has no way to cancel/go back
  - No ESC equivalent in non-interactive environments
  - Instruction says "Enter for 1" but doesn't explain how to exit
- **Impact:** Users in non-interactive environments get stuck

### 3. Inconsistent menu instruction formats
- **Location:** Various menus throughout application
- **Issue:**
  - Some use periods, some don't
  - Some capitalize "Press," some don't
  - Different phrasing for similar actions
- **Recommendation:** Standardize all menu instructions to consistent format
- **Impact:** Unprofessional appearance, cognitive load for users

---

## User Flow Issues (7)

### 4. Input length limits shown only after error
- **Location:** `core/vocab.py:1185-1189`
- **Issue:** Error messages show limits but user wasn't warned beforehand
- **Current:** Shows error "Please limit to X words" after user already typed
- **Should be:** Show limits in the prompt itself: `"Enter text (max 10 words, 100 chars)"`
- **Impact:** Preventable user frustration, wasted effort

### 5. Confusing multi-line input flow
- **Location:** `core/vocab.py:1146-1155`
- **Issue:** Prompt text changes between first and subsequent lines, but logic is unclear
  - First prompt: "Empty line to submit (or 'q' to cancel)"
  - Continuation prompt: "Enter more text (or press Enter to finish)"
- **Problem:** Users might not realize they can enter multiple lines
- **Impact:** Feature discovery issue, underutilization of multi-line input

### 6. No live character count feedback
- **Location:** Input collection throughout application
- **Issue:** Users typing long entries have no feedback about approaching limits
- **Recommendation:** Show character/word count during input (if using prompt_toolkit)
- **Impact:** Poor form UX, unexpected errors

### 7. Poor error recovery when LLM unavailable
- **Location:** `core/vocab.py:1635-1637`
- **Issue:** When LLM is unavailable, user is just told to skip - no immediate retry option
- **Current:** "Skipping new entry; AI features are currently disabled."
- **Better UX:** Offer immediate retry or provider setup option
- **Impact:** Frustrating user experience, broken workflow

### 8. Inconsistent confirmation dialogs
- **Location:**
  - `ui_helper.py:301-319` - `ui.confirm()`
  - `core/translator.py:267-290` - `_confirm_yes_no()`
- **Issue:** Multiple confirmation patterns exist doing essentially the same thing
  - Use different yes/no tokens
  - Different implementations
- **Impact:** Code duplication, potential inconsistency in behavior

### 9. Ambiguous spelling correction flow
- **Location:** `core/vocab.py:2002-2019`
- **Issue:** Shows spelling suggestion but says "Using suggested spelling for now; you can revert after the preview"
- **Problem:** "after the preview" is vague - when exactly can they revert?
- **Impact:** User confusion about when/how to revert

### 10. Spelling correction timing confusion
- **Location:** `core/vocab.py:1775-1783`
- **Issue:** User is asked about spelling correction AFTER seeing LaTeX entry
  - But the LaTeX entry was already generated with corrected spelling
- **Impact:** Confusing workflow, feels backwards

---

## Error Handling Issues (8)

### 11. Validation error panels may truncate messages
- **Location:** `core/providers/manager.py:558-569`
- **Issue:** Validation failure panel uses `expand=False` but error messages can be very long
- **Problem:** Users might miss important error details due to truncation
- **Impact:** Debugging difficulties, incomplete error information

### 12. Inconsistent error styling
- **Location:** Various locations
- **Issue:**
  - Some errors use panels: `self.ui.panel(..., border_style="red")`
  - Some use plain text: `self.ui.error("...")`
  - No clear hierarchy for when to use which
- **Examples:**
  - Plain text: `core/vocab.py:1183-1184`
  - Panel: `core/vocab.py:1706`
- **Recommendation:** Critical errors should use panels for visibility
- **Impact:** Inconsistent error hierarchy, some critical errors get lost

### 13. Missing error context
- **Location:** `core/vocab.py:1214-1216`
- **Issue:** Generic error message without context about what action triggered it
- **Current:** "AI provider unavailable: {reason}"
- **Better:** "Cannot add vocabulary entry: AI provider unavailable: {reason}"
- **Impact:** User confusion about what they were trying to do

### 14. API key validation timeout not configurable
- **Location:** `core/providers/manager.py:425`
- **Issue:**
  - Hardcoded 5 second timeout
  - No way to retry with longer timeout if network is slow
- **Impact:** Affects users with slow connections, false negatives

### 15. Inconsistent cancel mechanisms
- **Location:** Various input flows
- **Issue:**
  - Some flows use 'q' to cancel
  - Some use ESC
  - Some use both
  - No standard documented
- **Impact:** User confusion about how to exit/cancel

### 16. Merge vs Force options not clearly explained
- **Location:** `core/vocab.py:968-977`
- **Issue:** Difference between "merge" and "force" options not clearly explained
  - Users might not understand what "variant entry" means
- **Impact:** Wrong choice made, data integrity issues

### 17. No search preview/autocomplete
- **Location:** `core/vocab.py:2332-2344`
- **Issue:** Search happens all at once, no autocomplete or suggestions as user types
- **Impact:** Could be much more user-friendly with progressive results

### 18. Verbose debug output shown to users
- **Location:** `core/vocab.py:1983`
- **Issue:** Debug output shown to users: `self.ui.debug(f"Extracted corrected spelling: '{corrected_spelling}'")`
- **Problem:** Debug methods should be hidden unless verbose mode
- **Impact:** Clutters output, confusing to non-technical users

---

## Consistency Issues (9)

### 19. Mixed use of console.print() vs ui.* methods
- **Location:**
  - Direct console use: `core/translator.py:74-76`
  - UI helper methods: Most other places
- **Issue:** Some code uses `self.console.print()` directly, some uses `self.ui.*` methods
- **Example:**
  ```python
  self.console.print(f"[bold green]Created initial LaTeX file: {self.latex_file}[/bold green]")
  ```
  Should use: `self.ui.success(...)`
- **Impact:** Breaks encapsulation, inconsistent styling

### 20. Three different table display methods
- **Location:** Various locations
- **Issue:**
  - Some tables use `quick_table()`
  - Some create tables manually
  - Some use `dict_to_table()`
  - Example: `core/translator.py:468-479`
- **Impact:** Different styling across similar content

### 21. Inconsistent success message patterns
- **Pattern 1:** Plain text - `core/translator.py:416`
  ```python
  self.console.print("[bold green]Translation saved successfully![/bold green]")
  ```
- **Pattern 2:** With symbol - `core/providers/manager.py:452`
  ```python
  self.ui.success("✓ Connection successful!")
  ```
- **Pattern 3:** Panel - `core/vocab.py:958`
  ```python
  self.ui.panel("Skipping this word. Returning to main menu.", border_style="green")
  ```
- **Impact:** Inconsistent messaging hierarchy, no clear importance levels

### 22. Inconsistent dim text usage
- **Location:** Throughout application
- **Issue:**
  - Sometimes used for metadata: `[dim](19 pairs)[/dim]`
  - Sometimes used for entire instructions
  - Sometimes for deemphasized options
- **Recommendation:** Document when to use `[dim]` in design system
- **Impact:** Slight visual inconsistency

### 23. Information truncation without warning
- **Location:** `core/vocab.py:2312-2316`
- **Issue:** Truncates definitions to 60 chars without warning
  ```python
  if len(definitions) > 60:
      definitions = definitions[:57] + "..."
  ```
- **Problem:** Arbitrary truncation loses information
- **Better:** Use expandable rows or full display with pagination
- **Impact:** Data loss in UI, users can't see full information

### 24. Magic numbers not defined as constants
- **Location:** `core/vocab.py:2315`
- **Issue:** Hardcoded truncation length (60) should be a named constant
- **Impact:** Maintainability issue

### 25. Redundant prompts
- **Location:** `core/vocab.py:2329-2330`
- **Issue:**
  ```python
  if self.ui.confirm("Would you like to search for a specific word?", default=False):
      self.search_vocabulary()
  ```
- **Problem:** Why not just always offer search? Extra click for no reason
- **Impact:** Unnecessary friction in workflow

### 26. Inconsistent capitalization in menu items
- **Location:** `core/vocab.py:1051-1056`
- **Issue:**
  - Some menu items capitalize every word
  - Some use sentence case
- **Impact:** Unprofessional appearance

### 27. No undo functionality
- **Location:** Application-wide
- **Issue:**
  - No way to undo recent actions
  - Confirmation exists for some operations (`vocab.py:2290`) but no undo after confirmation
- **Impact:** Risky for users, permanent mistakes

---

## Summary Statistics

| Category | Count |
|----------|-------|
| Navigation | 3 |
| User Flow | 7 |
| Error Handling | 8 |
| Consistency | 9 |
| **TOTAL** | **27** |

**Note:** Some issues span multiple categories, so total is 27 instead of 22.

---

## Recommended Fix Priority

### Sprint 1 (Next 1-2 weeks)
- Issue #4: Input length limits in prompts
- Issue #12: Standardize error styling
- Issue #13: Add error context
- Issue #19: Eliminate direct console.print() calls
- Issue #21: Standardize success message patterns

### Sprint 2 (Next 2-4 weeks)
- Issue #1: Add ESC behavior to all menus
- Issue #2: Fix fallback menu cancel
- Issue #3: Standardize menu instructions
- Issue #7: Improve error recovery
- Issue #8: Consolidate confirmation dialogs

### Sprint 3 (Next 1-2 months)
- Issue #6: Add live character count
- Issue #17: Add search autocomplete
- Issue #27: Implement undo functionality
- Issue #11: Fix validation panel expansion
- Issue #20: Consolidate table methods

### Backlog
- All remaining issues

---

**Document End**
