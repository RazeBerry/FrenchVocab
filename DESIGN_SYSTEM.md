# FrenchVocab Design System

## 🎨 Anthropic-Inspired Design Principles

This document outlines the visual design system for FrenchVocab CLI, inspired by Anthropic's warm, approachable brand aesthetic.

---

## Color Palette

### Primary Colors
- **Anthropic Orange**: `#E67E50` / `dark_orange` - Primary accent, info messages, headers
- **Coral Red**: `#ff6b6b` - Error messages, critical alerts
- **Mint Green**: `#51cf66` / `green3` - Success messages, confirmations
- **Warm Yellow**: `#ffd43b` / `yellow3` - Warnings, cautions

### Supporting Colors
- **Magenta**: For data values and highlights
- **Dim/Gray**: For supplementary text and metadata

---

## Panel Width Guidelines

### Full-Width Panels (`expand=True`)
**Purpose**: Establish major sections and visual hierarchy

**Use for**:
- ✓ Section headers (e.g., "Translator Mode", "Vocab Builder")
- ✓ Welcome/exit screens
- ✓ Major mode transitions
- ✓ Content that needs visual weight

**Example**:
```python
Panel(
    content,
    title="Translator Mode",
    border_style="dark_orange",
    box=box.ROUNDED,
    expand=True,  # Full-width for visual impact
)
```

### Content-Wrapped Panels (`expand=False`)
**Purpose**: Provide contextual information without overwhelming

**Use for**:
- ✓ Instructions and helper text
- ✓ Inline menus and options
- ✓ Confirmation dialogs
- ✓ Warnings and alerts
- ✓ Tips and short messages

**Example**:
```python
Panel(
    instructions,
    border_style="dark_orange",
    box=box.ROUNDED,
    expand=False,  # Wraps tightly around content
)
```

---

## Typography & Symbols

### Unicode Symbols
- ✓ Success / Checkmark
- ✗ Error / Cross
- ⚡ Warning / Alert
- ℹ Information
- ○ Inactive menu item
- → Active menu item / Arrow

### Text Styles
- **Headers**: `[bold #E67E50]` - Warm, attention-grabbing
- **Labels**: `[bold dark_orange]` - Consistent with brand
- **Success text**: `[bold #51cf66]` - Positive reinforcement
- **Metadata**: `[dim]` - Subtle, non-intrusive
- **Body text**: Default white

---

## Border Styles

### Default
- **Box style**: `box.ROUNDED` - Friendly, modern aesthetic
- **Border color**: `dark_orange` - Consistent with Anthropic brand

### Contextual
- **Errors**: `#ff6b6b` border
- **Warnings**: `yellow3` border
- **Success**: `green3` border
- **Subtle/Metadata**: `dim dark_orange` border

---

## Interactive Elements

### Menu Active State
```python
# Active item
"[black on dark_orange] → {label} [/]"

# Inactive item
"  [dim]○[/] {label}"
```

### Panel Structure
```python
Panel(
    content,
    title=f"[bold #E67E50]{title}[/]",  # Warm orange title
    border_style="dark_orange",          # Consistent border
    box=box.ROUNDED,                     # Friendly corners
    expand=True/False,                   # Context-dependent width
)
```

---

## Design Rationale

### Why Anthropic Orange?
- **Warm & Approachable**: Creates friendly user experience
- **Brand Consistency**: Aligns with Anthropic's design language
- **Visibility**: Distinct without being harsh
- **Professional**: Modern while remaining accessible

### Why Full-Width vs. Wrapped?
**Full-width panels** create clear visual boundaries and establish hierarchy - they say "this is a major section."

**Wrapped panels** keep focus tight and avoid overwhelming the user - they say "this is supplementary information."

This distinction helps users quickly understand the structure and importance of different interface elements.

---

## Implementation Checklist

When adding new UI elements:
- [ ] Choose appropriate color from palette
- [ ] Decide: full-width or wrapped panel?
- [ ] Add rounded borders (`box=box.ROUNDED`)
- [ ] Use unicode symbols for message types
- [ ] Add explanatory comment about design choice
- [ ] Ensure consistency with existing patterns

---

## Examples

### Section Header (Full-Width)
```python
# Header panel: full-width for major section indicator
Panel(
    "[bold #E67E50]German → English Translator[/]\nManaging 19 pairs",
    title="Translator Mode",
    border_style="dark_orange",
    box=box.ROUNDED,
    expand=True,
)
```

### Instructions (Wrapped)
```python
# Instructions panel: wrapped for contextual info
instructions = (
    "[#E67E50]Enter German text to translate.[/]\n"
    "[dim]- Type or paste your text.\n"
    "- Press Enter on an empty line to finish.[/dim]"
)
Panel(instructions, border_style="dark_orange", box=box.ROUNDED, expand=False)
```

### Confirmation (Wrapped)
```python
# Confirmation panel: wrapped for focused decision-making
table = Table(show_header=False, box=None)
table.add_column(style="dark_orange")
table.add_column(style="white")
Panel(table, border_style="dark_orange", box=box.ROUNDED, expand=False)
```

---

*Last updated: 2025-11-03*
*Design inspired by Anthropic's brand guidelines*
