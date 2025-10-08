from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum

class MessageType(Enum):
    """Enum for consistent message styling"""
    ERROR = ("bold red", "Error", "red")
    SUCCESS = ("bold green", "Success", "green")
    WARNING = ("bold yellow", "Warning", "yellow")
    INFO = ("bold blue", "Info", "blue")
    DEBUG = ("dim", "Debug", "dim")

class UIHelper:
    """Centralized UI helper for all console output operations"""
    
    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()
        self._progress_stack = []  # Reserved for future progress integrations
    
    # ========== Basic Message Methods ==========
    
    def message(self, text: str, msg_type: MessageType) -> None:
        """Display a formatted message based on type"""
        style, _, _ = msg_type.value
        self.console.print(f"[{style}]{text}[/{style}]")
    
    def error(self, text: str, with_panel: bool = False) -> None:
        """Display error message, optionally in a panel"""
        if with_panel:
            self.panel(text, "Error", "red", style="bold red")
        else:
            self.message(text, MessageType.ERROR)
    
    def success(self, text: str, with_panel: bool = False) -> None:
        """Display success message, optionally in a panel"""
        if with_panel:
            self.panel(text, "Success", "green", style="bold green")
        else:
            self.message(text, MessageType.SUCCESS)
    
    def warning(self, text: str, with_panel: bool = False) -> None:
        """Display warning message, optionally in a panel"""
        if with_panel:
            self.panel(text, "Warning", "yellow", style="bold yellow")
        else:
            self.message(text, MessageType.WARNING)
    
    def info(self, text: str, with_panel: bool = False) -> None:
        """Display info message, optionally in a panel"""
        if with_panel:
            self.panel(text, "Information", "blue", style="bold blue")
        else:
            self.message(text, MessageType.INFO)
    
    def debug(self, text: str) -> None:
        """Display debug message"""
        self.message(text, MessageType.DEBUG)
    
    # ========== Panel Methods ==========
    
    def panel(self, content: str, title: str = "", border_style: str = "blue", 
              expand: bool = False, **kwargs) -> None:
        """Display content in a styled panel"""
        self.console.print(Panel(
            content, 
            title=title, 
            border_style=border_style,
            expand=expand,
            **kwargs
        ))
    
    # ========== Table Methods ==========
    
    def create_table(self, title: str = "", columns: List[Dict[str, str]] = None) -> Table:
        """Create a table with specified columns"""
        table = Table(title=title)
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
        """Display a formatted menu"""
        table = Table(show_header=False, box=None, padding=(0, 1), expand=True)
        table.add_column(style="bold cyan", width=3, justify="right")
        table.add_column()
        
        for i, (key, description) in enumerate(options):
            if show_numbers and key.isdigit():
                table.add_row(f"{key}.", description)
            else:
                table.add_row(f"[{key}]", description)
        
        self.panel(table, title=title, border_style="blue", expand=False)
    
    # ========== Input Methods ==========
    
    # ========== Specialized Display Methods ==========
    
    def display_word_entry(self, word: str, word_type: str, 
                          definitions: List[str], examples: List[Tuple[str, str]]) -> None:
        """Display a vocabulary entry in a formatted table"""
        table = self.create_table(
            title=f"Information for [bold green]{word.capitalize()}[/bold green]",
            columns=[
                {"name": "Category", "style": "cyan", "no_wrap": True},
                {"name": "Information", "style": "magenta"}
            ]
        )
        
        table.add_row("Word Type", word_type)
        
        def_str = "\n".join([f"• {d}" for d in definitions])
        table.add_row("Definitions", def_str)
        
        ex_str = "\n".join([
            f"• {f}\n  {e if e.startswith('(') and e.endswith(')') else f'({e})'}" 
            for f, e in examples
        ])
        table.add_row("Examples", ex_str)
        
        self.display_table(table)
    
    def display_latex_entry(self, latex_entry: str) -> None:
        """Display a LaTeX entry in a panel"""
        self.panel(latex_entry, title="Generated LaTeX Entry", border_style="bold blue")
    
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
        self.panel(metrics_text, title="LLM Performance", border_style="dim blue")
    
    # ========== Utility Methods ==========
    
    def clear_line(self) -> None:
        """Clear the current line"""
        self.console.print("\r", end="")
    
    def input_with_style(self, prompt: str, style: str = "bold cyan") -> str:
        """Get input with styled prompt"""
        self.console.print(f"[{style}]{prompt}[/{style}]", end="")
        return input() 
