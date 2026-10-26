# 桌面图形界面使用指南

## 启动

需要 Python 3.10+ 和随 Python 提供的 Tkinter。核心数据库与界面均只使用标准库。进入项目根目录后执行：

```powershell
python -m dbms.gui --db .\gui_data
```

不填 `--db` 时也默认使用当前目录下的 `gui_data/`。可用 `--buffer-pages 32` 调整缓存页数。Windows 上可双击项目根目录的 `launch_gui.pyw`；它固定使用项目下的 `gui_data/`，启动后不显示命令行窗口。若双击无效，可执行 `pythonw .\launch_gui.pyw`。

## 窗口操作

1. 顶部显示当前数据库目录。可直接输入新路径并点击“打开目录”，或点击“浏览…”选择已有目录。新路径不存在时会创建数据库。切换前，旧数据库会正常关闭并写回数据。
2. 在 **SQL 编辑器**输入语句，点击“执行”或按 `Ctrl+Enter`。可以一次输入多条，用分号分隔；选中一部分文本时仅执行选中部分。也可以从示例菜单插入模板，或打开、保存 UTF-8 `.sql` 文件。
3. 左侧显示当前数据库中的表。选中表可查看列名和类型；双击表或点“查看选中表的数据”会执行 `SELECT *`。
4. 下方记录本次会话的每条语句。点击记录可查看对应结果或错误；查询结果用表格显示，写操作显示影响行数与执行计划标签。
5. 窗口底部显示缓存命中、未命中、淘汰和写回计数。关闭窗口时程序会关闭存储并写回数据。

图形界面复用 `dbms.frontend.parse/plan`、`dbms.executor.execute` 和 `dbms.storage.StorageEngine`。成功的写操作会立即调用 `flush()`，便于关闭前保存数据；语句错误会显示在记录中，后续语句继续执行。课程 MVP 不提供事务回滚，批量修改中途失败时可能已有部分行被修改。

## 可以直接试的 SQL

在**新数据库目录**中，依次执行：

```sql
CREATE TABLE students (id INT, name TEXT, score INT);
INSERT INTO students VALUES (1, 'Alice', 90);
INSERT INTO students VALUES (2, 'Bob', 60);
SELECT * FROM students;
CREATE INDEX idx_students_id ON students (id);
SELECT name FROM students WHERE id = 1;
```

最后一条查询会显示 `IndexEqScan`。再关闭窗口、用同一目录启动，点击左侧 `students` 表即可看到已经保存的数据。演示脚本 `examples/demo.sql` 也可通过“打开 SQL 文件”载入并执行；其中包含建表语句，每次演示应使用新目录。

## 已知边界

- 桌面界面适合本机单人使用；不要同时用两个进程写同一数据库目录。
- 大量数据的查询会在执行期间短暂占用窗口主线程；此项目的课程场景以小型数据集为主。
- SQL 语法仍以[需求与范围](01-requirements.md)为准；界面没有扩大数据库核心支持的 SQL 子集。
