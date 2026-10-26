"""Tkinter desktop interface for the course DBMS."""

from __future__ import annotations

import argparse
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from dbms.gui.session import DatabaseSession, ExecutionRecord
from dbms.types import DBMSError


TEMPLATES = {
    "选择 SQL 示例…": "",
    "创建学生表": "CREATE TABLE students (id INT, name TEXT, score INT);",
    "插入学生": "INSERT INTO students VALUES (1, 'Alice', 90);",
    "查询所有学生": "SELECT * FROM students;",
    "按分数查询": "SELECT id, name FROM students WHERE score >= 60;",
    "创建分数索引": "CREATE INDEX idx_students_score ON students (score);",
    "更新分数": "UPDATE students SET score = 95 WHERE id = 1;",
    "删除学生": "DELETE FROM students WHERE id = 1;",
}


class DatabaseApp:
    def __init__(self, root: tk.Tk, session: DatabaseSession) -> None:
        self.root = root
        self.session = session
        self.records: list[ExecutionRecord] = []
        self.db_path = tk.StringVar(value=str(session.db_dir))
        self.status = tk.StringVar(value="就绪 · 输入 SQL 后点击“执行”，或按 Ctrl+Enter")
        self.detail = tk.StringVar(value="查询结果会显示在这里。")
        self.stats = tk.StringVar(value="")
        self.template_name = tk.StringVar(value="选择 SQL 示例…")
        self._configure_window()
        self._build_ui()
        self._refresh_tables()
        self._update_stats()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind("<Control-Return>", self._run_shortcut)

    def _configure_window(self) -> None:
        self.root.title("数据库实验台")
        self.root.geometry("1180x760")
        self.root.minsize(860, 580)
        self.root.configure(bg="#f3f6fb")
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("App.TFrame", background="#f3f6fb")
        style.configure("Panel.TFrame", background="#ffffff")
        style.configure("Title.TLabel", background="#f3f6fb", foreground="#10213a", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Sub.TLabel", background="#f3f6fb", foreground="#5e6b80", font=("Microsoft YaHei UI", 9))
        style.configure("PanelTitle.TLabel", background="#ffffff", foreground="#10213a", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Panel.TLabel", background="#ffffff", foreground="#435168", font=("Microsoft YaHei UI", 9))
        style.configure("Accent.TButton", padding=(14, 8), background="#245eea", foreground="white", font=("Microsoft YaHei UI", 9, "bold"))
        style.map("Accent.TButton", background=[("active", "#174ac3")])
        style.configure("Action.TButton", padding=(10, 7), font=("Microsoft YaHei UI", 9))
        style.configure("Result.Treeview", rowheight=28, font=("Microsoft YaHei UI", 9))
        style.configure("Result.Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, style="App.TFrame", padding=18)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill="x", pady=(0, 14))
        ttk.Label(header, text="数据库实验台", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="用图形界面运行 SQL，查看数据、执行计划和缓存状态", style="Sub.TLabel").pack(anchor="w", pady=(3, 0))

        db_bar = ttk.Frame(outer, style="Panel.TFrame", padding=10)
        db_bar.pack(fill="x", pady=(0, 12))
        ttk.Label(db_bar, text="数据库目录", style="Panel.TLabel").pack(side="left", padx=(0, 10))
        ttk.Entry(db_bar, textvariable=self.db_path).pack(side="left", fill="x", expand=True)
        ttk.Button(db_bar, text="浏览…", command=self._choose_database, style="Action.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(db_bar, text="打开目录", command=self._switch_database, style="Action.TButton").pack(side="left", padx=(8, 0))

        body = ttk.PanedWindow(outer, orient="horizontal")
        body.pack(fill="both", expand=True)
        sidebar = ttk.Frame(body, style="Panel.TFrame", padding=12)
        main = ttk.Frame(body, style="App.TFrame")
        body.add(sidebar, weight=1)
        body.add(main, weight=4)
        self._build_sidebar(sidebar)
        self._build_main(main)

        footer = ttk.Frame(outer, style="App.TFrame")
        footer.pack(fill="x", pady=(12, 0))
        ttk.Label(footer, textvariable=self.status, style="Sub.TLabel").pack(side="left")
        ttk.Label(footer, textvariable=self.stats, style="Sub.TLabel").pack(side="right")

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Panel.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="数据表", style="PanelTitle.TLabel").pack(side="left")
        ttk.Button(top, text="刷新", command=self._refresh_tables, style="Action.TButton").pack(side="right")
        self.tables = tk.Listbox(
            parent, exportselection=False, relief="flat", borderwidth=0,
            bg="#f7f9fd", fg="#22344d", selectbackground="#dbe7ff",
            selectforeground="#173b8a", font=("Microsoft YaHei UI", 10), height=11,
        )
        self.tables.pack(fill="both", expand=True, pady=(12, 7))
        self.tables.bind("<<ListboxSelect>>", self._show_selected_schema)
        self.tables.bind("<Double-Button-1>", self._preview_table)
        ttk.Button(parent, text="查看选中表的数据", command=self._preview_table, style="Action.TButton").pack(fill="x", pady=(0, 14))
        ttk.Separator(parent).pack(fill="x", pady=(0, 12))
        ttk.Label(parent, text="表结构", style="PanelTitle.TLabel").pack(anchor="w")
        self.schema_text = tk.Text(
            parent, height=8, wrap="word", relief="flat", borderwidth=0,
            bg="#ffffff", fg="#435168", font=("Consolas", 10), state="disabled",
        )
        self.schema_text.pack(fill="x", pady=(8, 0))

    def _build_main(self, parent: ttk.Frame) -> None:
        editor_panel = ttk.Frame(parent, style="Panel.TFrame", padding=12)
        editor_panel.pack(fill="x", pady=(0, 12))
        toolbar = ttk.Frame(editor_panel, style="Panel.TFrame")
        toolbar.pack(fill="x", pady=(0, 9))
        ttk.Label(toolbar, text="SQL 编辑器", style="PanelTitle.TLabel").pack(side="left")
        ttk.Label(toolbar, text="可一次执行多条语句", style="Panel.TLabel").pack(side="left", padx=(12, 0))
        ttk.Button(toolbar, text="执行  Ctrl+Enter", command=self._run_sql, style="Accent.TButton").pack(side="right")
        self.editor = tk.Text(
            editor_panel, height=10, undo=True, wrap="none", relief="flat",
            borderwidth=0, bg="#f7f9fd", fg="#10213a", insertbackground="#10213a",
            font=("Consolas", 11), padx=12, pady=10,
        )
        self.editor.pack(fill="x")
        actions = ttk.Frame(editor_panel, style="Panel.TFrame")
        actions.pack(fill="x", pady=(9, 0))
        samples = ttk.Combobox(actions, textvariable=self.template_name, values=list(TEMPLATES), state="readonly", width=19)
        samples.pack(side="left")
        samples.bind("<<ComboboxSelected>>", self._insert_template)
        ttk.Button(actions, text="打开 SQL 文件", command=self._open_sql_file, style="Action.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="保存 SQL", command=self._save_sql_file, style="Action.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="清空编辑器", command=lambda: self.editor.delete("1.0", "end"), style="Action.TButton").pack(side="right")

        output = ttk.Frame(parent, style="Panel.TFrame", padding=12)
        output.pack(fill="both", expand=True)
        title = ttk.Frame(output, style="Panel.TFrame")
        title.pack(fill="x", pady=(0, 10))
        ttk.Label(title, text="执行结果", style="PanelTitle.TLabel").pack(side="left")
        ttk.Label(title, textvariable=self.detail, style="Panel.TLabel").pack(side="right")
        result_area = ttk.PanedWindow(output, orient="horizontal")
        result_area.pack(fill="both", expand=True)
        history_panel = ttk.Frame(result_area, style="Panel.TFrame")
        table_panel = ttk.Frame(result_area, style="Panel.TFrame")
        result_area.add(history_panel, weight=1)
        result_area.add(table_panel, weight=4)
        ttk.Label(history_panel, text="本次会话记录", style="Panel.TLabel").pack(anchor="w", pady=(0, 7))
        self.history = tk.Listbox(
            history_panel, exportselection=False, relief="flat", borderwidth=0,
            bg="#f7f9fd", fg="#22344d", selectbackground="#dbe7ff",
            selectforeground="#173b8a", font=("Microsoft YaHei UI", 9), width=24,
        )
        self.history.pack(fill="both", expand=True, padx=(0, 10))
        self.history.bind("<<ListboxSelect>>", self._show_history)
        self.result_table = ttk.Treeview(table_panel, show="headings", style="Result.Treeview")
        y_scroll = ttk.Scrollbar(table_panel, orient="vertical", command=self.result_table.yview)
        x_scroll = ttk.Scrollbar(table_panel, orient="horizontal", command=self.result_table.xview)
        self.result_table.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.result_table.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        table_panel.rowconfigure(0, weight=1)
        table_panel.columnconfigure(0, weight=1)

    def _run_shortcut(self, _event: tk.Event) -> str:
        self._run_sql()
        return "break"

    def _run_sql(self) -> None:
        try:
            sql = self.editor.get("sel.first", "sel.last")
        except tk.TclError:
            sql = self.editor.get("1.0", "end")
        if not sql.strip():
            self.status.set("请输入 SQL，或从示例菜单选择语句。")
            return
        self.status.set("正在执行…")
        self.root.update_idletasks()
        try:
            new_records = self.session.execute_text(sql)
        except Exception as error:
            messagebox.showerror("执行失败", f"发生内部错误：{error}", parent=self.root)
            self.status.set("执行中断；请检查错误信息。")
            return
        for record in new_records:
            self.records.append(record)
            marker = "✗" if record.error else "✓"
            title = " ".join(record.sql.split())[:30]
            self.history.insert("end", f"{marker}  {title}")
        if new_records:
            last_index = len(self.records) - 1
            self.history.selection_clear(0, "end")
            self.history.selection_set(last_index)
            self.history.see(last_index)
            self._render_record(self.records[last_index])
            errors = sum(record.error is not None for record in new_records)
            self.status.set(f"已执行 {len(new_records)} 条语句；成功 {len(new_records) - errors}，失败 {errors}。")
        else:
            self.status.set("没有可执行的 SQL 语句。")
        self._refresh_tables()
        self._update_stats()

    def _render_record(self, record: ExecutionRecord) -> None:
        self.result_table.delete(*self.result_table.get_children())
        self.result_table["columns"] = ()
        if record.error is not None:
            self.detail.set(f"错误：{record.error}")
            return
        result = record.result
        if result is None:
            self.detail.set("没有返回结果")
            return
        if result.columns:
            identifiers = tuple(f"col_{index}" for index in range(len(result.columns)))
            self.result_table["columns"] = identifiers
            for identifier, label in zip(identifiers, result.columns):
                self.result_table.heading(identifier, text=label)
                self.result_table.column(identifier, width=130, minwidth=90, stretch=True)
            for row in result.rows:
                self.result_table.insert("", "end", values=tuple(str(value) for value in row))
            count_text = f"{len(result.rows)} 行结果"
        else:
            count_text = f"影响 {result.affected_rows} 行"
        self.detail.set(f"{result.plan_label} · {count_text} · {record.elapsed_ms:.1f} ms")

    def _show_history(self, _event: tk.Event) -> None:
        selection = self.history.curselection()
        if selection:
            self._render_record(self.records[selection[0]])

    def _refresh_tables(self) -> None:
        selection = self.tables.curselection()
        previous = self.tables.get(selection[0]) if selection else None
        try:
            names = self.session.list_tables()
        except (DBMSError, OSError) as error:
            self.status.set(f"读取数据表失败：{error}")
            return
        self.tables.delete(0, "end")
        for name in names:
            self.tables.insert("end", name)
        if previous in names:
            index = names.index(previous)
            self.tables.selection_set(index)
            self._show_selected_schema()
        else:
            self._set_schema_text("选择一个数据表查看列结构。" if names else "当前数据库还没有表。")

    def _selected_table(self) -> str | None:
        selection = self.tables.curselection()
        return self.tables.get(selection[0]) if selection else None

    def _show_selected_schema(self, _event: tk.Event | None = None) -> None:
        table = self._selected_table()
        if table is None:
            return
        try:
            schema = self.session.get_schema(table)
        except (DBMSError, OSError) as error:
            self._set_schema_text(f"读取失败：{error}")
            return
        lines = [f"{column.name}  {column.type}" for column in schema.columns]
        self._set_schema_text("\n".join(lines))

    def _set_schema_text(self, text: str) -> None:
        self.schema_text.configure(state="normal")
        self.schema_text.delete("1.0", "end")
        self.schema_text.insert("1.0", text)
        self.schema_text.configure(state="disabled")

    def _preview_table(self, _event: tk.Event | None = None) -> None:
        table = self._selected_table()
        if table is None:
            self.status.set("请先从左侧选择数据表。")
            return
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", f"SELECT * FROM {table};")
        self._run_sql()

    def _insert_template(self, _event: tk.Event) -> None:
        sql = TEMPLATES[self.template_name.get()]
        if sql:
            self.editor.insert("insert", sql + "\n")
            self.editor.focus_set()
        self.template_name.set("选择 SQL 示例…")

    def _open_sql_file(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title="打开 SQL 文件", filetypes=[("SQL 文件", "*.sql"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            sql = Path(path).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            messagebox.showerror("打开失败", str(error), parent=self.root)
            return
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", sql)
        self.status.set(f"已打开 {path}；点击执行以运行脚本。")

    def _save_sql_file(self) -> None:
        path = filedialog.asksaveasfilename(parent=self.root, title="保存 SQL 文件", defaultextension=".sql", filetypes=[("SQL 文件", "*.sql")])
        if not path:
            return
        try:
            Path(path).write_text(self.editor.get("1.0", "end-1c"), encoding="utf-8")
        except OSError as error:
            messagebox.showerror("保存失败", str(error), parent=self.root)
            return
        self.status.set(f"SQL 已保存到 {path}")

    def _choose_database(self) -> None:
        path = filedialog.askdirectory(parent=self.root, title="选择数据库目录", initialdir=str(self.session.db_dir.parent))
        if path:
            self.db_path.set(path)
            self._switch_database()

    def _switch_database(self) -> None:
        path = self.db_path.get().strip()
        if not path:
            messagebox.showwarning("目录不能为空", "请输入或选择数据库目录。", parent=self.root)
            return
        try:
            self.session.switch_database(path)
        except (DBMSError, OSError, ValueError) as error:
            messagebox.showerror("打开数据库失败", str(error), parent=self.root)
            self.db_path.set(str(self.session.db_dir))
            return
        self.db_path.set(str(self.session.db_dir))
        self.records.clear()
        self.history.delete(0, "end")
        self.result_table.delete(*self.result_table.get_children())
        self.result_table["columns"] = ()
        self.detail.set("已切换数据库。")
        self._refresh_tables()
        self._update_stats()
        self.status.set(f"当前数据库：{self.session.db_dir}")

    def _update_stats(self) -> None:
        try:
            hits, misses, evictions, flushes = self.session.buffer_stats()
        except (DBMSError, OSError):
            self.stats.set("缓存状态不可用")
        else:
            self.stats.set(f"缓存命中 {hits} · 未命中 {misses} · 淘汰 {evictions} · 写回 {flushes}")

    def _close(self) -> None:
        try:
            self.session.close()
        except (DBMSError, OSError) as error:
            messagebox.showerror("关闭数据库失败", f"无法完成数据写回：{error}", parent=self.root)
            return
        self.root.destroy()


def _positive_integer(text: str) -> int:
    try:
        value = int(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError("缓存页数必须是正整数") from error
    if value <= 0:
        raise argparse.ArgumentTypeError("缓存页数必须是正整数")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动数据库桌面图形界面")
    parser.add_argument("--db", default="gui_data", metavar="PATH", help="数据库目录（默认 gui_data）")
    parser.add_argument("--buffer-pages", type=_positive_integer, default=64, metavar="N", help="缓存页数（默认 64）")
    args = parser.parse_args(argv)
    try:
        session = DatabaseSession(args.db, buffer_pages=args.buffer_pages)
    except (DBMSError, OSError, ValueError) as error:
        print(f"打开数据库失败：{error}", file=sys.stderr)
        return 1
    try:
        root = tk.Tk()
    except tk.TclError as error:
        session.close()
        print(f"无法启动图形界面：{error}", file=sys.stderr)
        return 1
    DatabaseApp(root, session)
    root.mainloop()
    return 0
