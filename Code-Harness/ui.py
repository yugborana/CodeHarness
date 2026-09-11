import json
from contextlib import contextmanager
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
ACCENT = "#7aa2f7"
USER = "#9ece6a"
TOOL = "#e0af68"
MUTED = "#565f89"
MAX_TOOL_OUTPUT_LINES = 12
class UI:
    def __init__(self):
        self.console = Console()
        self._totals = {}
    # ---------------------------------------------------------------- input
    def banner(self):
        self.console.print()
        self.console.print(
            Rule(Text(" coding agent ", style=f"bold {ACCENT}"), style=MUTED)
        )
        self.console.print(
            Padding(Text("ctrl-d to exit", style=MUTED), (0, 0, 0, 2))
        )
    def ask(self):
        self.console.print()
        try:
            return self.console.input(f"[bold {USER}]>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            self.console.print()
            return ""
    # --------------------------------------------------------------- output
    def user(self, text):
        self.console.print(
            Padding(Text(text.strip(), style=f"bold {USER}"), (1, 0, 0, 2))
        )
    def agent(self, text):
        self.console.print(
            Padding(
                Group(
                    Text("agent", style=f"bold {ACCENT}"),
                    Padding(Markdown(text.strip()), (1, 0, 0, 0)),
                ),
                (1, 2, 0, 2),
            )
        )
    def tool(self, name, args, result):
        header = Text.assemble(
            (f"{name} ", f"bold {TOOL}"),
            (self._format_args(args), MUTED),
        )
        self.console.print(
            Padding(
                Panel(
                    Group(header, Rule(style=MUTED), self._format_result(result)),
                    border_style=MUTED,
                    padding=(0, 1),
                ),
                (1, 2, 0, 2),
            )
        )
    @contextmanager
    def working(self):
        with self.console.status(
            Text("thinking", style=MUTED), spinner="dots", spinner_style=ACCENT
        ):
            yield
    # ---------------------------------------------------------------- usage
    def usage(self, stats):
        for key, value in stats.items():
            self._totals[key] = self._totals.get(key, 0) + (value or 0)
        parts = " · ".join(
            f"{value:,} {key.replace('_tokens', '')}"
            for key, value in stats.items()
            if value
        )
        self.console.print(Padding(Text(parts, style=MUTED), (1, 0, 0, 2)))
    def summary(self):
        if not self._totals:
            return
        table = Table.grid(padding=(0, 2))
        table.add_column(style=MUTED)
        table.add_column(style=f"bold {ACCENT}", justify="right")
        for key, value in self._totals.items():
            table.add_row(key.replace("_", " "), f"{value:,}")
        self.console.print(Padding(table, (1, 2)))
        self.console.print(Rule(style=MUTED))
        self.console.print()
    # -------------------------------------------------------------- helpers
    def _format_args(self, args):
        if len(args) == 1:
            return str(next(iter(args.values())))
        return json.dumps(args)
    def _format_result(self, result):
        lines = result.strip().splitlines() or ["(no output)"]
        shown = lines[:MAX_TOOL_OUTPUT_LINES]
        body = Text("\n".join(shown), style=MUTED)
        hidden = len(lines) - len(shown)
        if hidden > 0:
            body.append(f"\n… {hidden} more lines", style=f"italic {TOOL}")
        return body
ui = UI()