# 数据库管理系统完整使用手册

本手册面向第一次使用本项目的同学。系统提供桌面图形界面和命令行，两种入口访问相同的本地数据库目录。建议先按第 2 节完成一次建表与查询，再阅读后面的 SQL 规则和常见问题。

## 1. 运行准备

- 安装 **Python 3.10 或更新版本**。数据库核心仅使用 Python 标准库；桌面界面还需要 Python 安装中包含 Tkinter。
- 下载或克隆本仓库。在 PowerShell 中进入仓库根目录，即包含 `dbms/`、`docs/` 和 `examples/` 的目录。
- 使用 `python --version` 检查 Python。下文命令均在仓库根目录执行；如果系统使用 `py` 启动 Python，可以将命令开头的 `python` 换成 `py`。

Windows 本机示例：

```powershell
cd "D:\study\school_work\数据库大作业"
python --version
```

`--db` 后面填写的是**数据库目录**，不是某个 `.db` 文件。目录不存在时程序会创建它；下次使用同一路径可继续读取原有表和数据。

## 2. 五分钟上手：图形界面

在仓库根目录运行：

```powershell
python -m dbms.gui --db .\my_data
```

Windows 用户也可以双击根目录的 `launch_gui.pyw`。它默认使用仓库下的 `gui_data/`；如果文件关联未生效，可运行 `pythonw .\launch_gui.pyw`。想自行指定数据库目录时使用上面的 `python -m dbms.gui --db ...` 命令。

在 SQL 编辑器中粘贴并执行以下语句。可一次粘贴全部内容并点击“执行”，也可逐条执行：

```sql
CREATE TABLE students (id INT, name TEXT, score INT);
INSERT INTO students VALUES (1, 'Alice', 90);
INSERT INTO students VALUES (2, 'Bob', 60);
SELECT * FROM students;
CREATE INDEX idx_students_id ON students (id);
SELECT name FROM students WHERE id = 1;
```

预期结果：左侧出现 `students` 表，第一次查询返回两行；最后一次查询返回 `Alice`，计划标签为 `IndexEqScan`。关闭窗口后，用同一 `--db .\my_data` 路径重新启动，表仍应存在。请勿在同一目录再次执行 `CREATE TABLE students ...`，否则会得到“表已存在”错误。

### 窗口各区域

| 区域 | 用法 |
| --- | --- |
| 顶部“数据库目录” | 输入目录并点击“打开目录”；“浏览…”用于选择已有目录。切换时旧数据库会正常关闭。 |
| 左侧“数据表” | 点击表名查看列和类型；双击或点击“查看选中表的数据”执行 `SELECT *`。 |
| SQL 编辑器 | 点击“执行”或按 `Ctrl+Enter`。选中文本时仅执行选中部分；未选中时执行编辑器全部内容。 |
| 示例与文件按钮 | 插入 SQL 模板、打开 UTF-8 `.sql` 文件或保存编辑器内容。打开文件后仍需点击“执行”。 |
| 下方记录与结果 | 本次会话的语句逐条记录；点击记录可查看该语句的结果、影响行数、计划标签或错误。记录不会在重启后保留。 |
| 底部状态 | 显示累计缓存命中、未命中、淘汰和写回次数。 |

执行多条 SQL 时，某一条报错会显示在记录中，后面的语句仍会继续执行。成功的写操作会刷新数据到磁盘；正常关闭窗口也会关闭存储。

## 3. 命令行使用

### 3.1 交互输入

```powershell
python -m dbms --db .\my_data
```

在 `dbms>` 提示符输入 SQL，例如 `SELECT * FROM students;`。可以跨多行输入，以分号结束语句；一行也可放多条语句。输入单独一行 `.exit` 退出。Windows 终端可用 `Ctrl+Z` 后按回车发送文件结束信号。

### 3.2 执行 SQL 文件

```powershell
python -m dbms --db .\fresh_demo --file .\examples\demo.sql
```

脚本使用 UTF-8 编码，也接受 UTF-8 BOM。`examples/demo.sql` 包含建表、插入、索引前后查询、更新和删除；**每次运行该演示脚本应使用一个全新目录**，例如第二次改为 `fresh_demo_2`。脚本中的一条 SQL 出错时，程序显示错误并继续执行后续语句，最后以非零退出码表示脚本曾有错误。

### 3.3 可选参数

| 入口 | 参数 | 含义 |
| --- | --- | --- |
| CLI | `--db PATH` | 必填，数据库目录 |
| CLI | `--file PATH` | 可选，执行 SQL 文件；不填则进入交互模式 |
| GUI | `--db PATH` | 可选，默认当前工作目录下的 `gui_data/` |
| 两者 | `--buffer-pages N` | 缓存容量，正整数，默认 64 页 |

可用 `python -m dbms --help` 和 `python -m dbms.gui --help` 查看实际参数。GUI 与 CLI 不应**同时**写同一个数据库目录。

## 4. 支持的 SQL

本项目实现教学用 SQL 子集。SQL 关键字与表名、列名不区分大小写；字符串值保留原样。每条语句末尾可以有一个分号。以下示例在已建好 `students(id INT, name TEXT, score INT)` 的数据库中使用。

| 功能 | 形式与示例 | 说明 |
| --- | --- | --- |
| 建表 | `CREATE TABLE students (id INT, name TEXT, score INT);` | 列类型仅有 `INT` 和 `TEXT`。 |
| 插入 | `INSERT INTO students VALUES (3, 'Cara', 88);` | 必须按建表列序为每列提供值。 |
| 查全部列 | `SELECT * FROM students;` | 查询结果的行顺序不作保证。 |
| 查指定列 | `SELECT id, name FROM students WHERE score >= 60;` | 仅支持单表；`WHERE` 最多一个比较条件。 |
| 建索引 | `CREATE INDEX idx_students_id ON students (id);` | 单列等值索引，允许重复键；同一列最多一个索引。 |
| 更新 | `UPDATE students SET score = 95 WHERE id = 3;` | 一次只修改一列；省略 `WHERE` 将作用于全表。 |
| 删除 | `DELETE FROM students WHERE id = 3;` | 省略 `WHERE` 将删除表中全部行。 |

`WHERE` 支持 `=`, `!=`, `<`, `<=`, `>` 和 `>=`。有索引的列使用等值条件 `=` 时，计划标签通常为 `IndexEqScan`；其他条件显示 `SeqScan`。标签说明采用的访问路径，不表示查询一定更快。

### 数据值与名称规则

- `INT` 为有符号 64 位整数，范围 `-9223372036854775808` 到 `9223372036854775807`。不接受 `TRUE`、小数或字符串代替整数。
- `TEXT` 使用单引号，UTF-8 编码后最多 **255 字节**；中文通常占多个字节。字符串内的单引号写两次，例如 `'O''Brien'`。空字符串 `''` 合法。
- 表名、列名和索引名以 ASCII 字母或 `_` 开头，后面可接 ASCII 字母、数字、`_`；不能使用保留关键字或带引号的标识符。
- 不支持 `NULL`、默认值、主外键、`JOIN`、`ORDER BY`、聚合、子查询、事务和 SQL 注释。不要把 `-- 注释` 放进待执行的 SQL 文件。
- `UPDATE` 保持记录位置不变。若新记录比原来占用的空间更长，程序会报错；例如把很短的文本更新为更长的文本可能失败。

## 5. 数据存放、关闭与备份

数据库目录中包含 `catalog.json`、`tables/` 和 `indexes/` 等内部文件。不要手工编辑、单独移动或删除其中某个文件。

正常退出 CLI 或关闭 GUI 时会写回缓存和索引。GUI 成功写入后也会立即刷新。备份时先退出所有使用该目录的程序，再复制**整个数据库目录**；恢复时也应整体复制到新目录，并通过 `--db` 指向该目录。本项目不提供事务、异常断电恢复或多进程并发写入保证。

## 6. 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| `No module named dbms` | 当前目录不是仓库根目录；先 `cd` 到包含 `dbms/` 的目录。 |
| 图形界面报 `No module named tkinter` | 当前 Python 未安装 Tkinter；安装包含 Tkinter 的 Python，或先使用 CLI。 |
| 重跑演示脚本提示表或索引已存在 | 演示脚本含 `CREATE`；换一个新的 `--db` 目录。 |
| 查询报未知表或未知列 | 检查当前数据库目录及表、列名；GUI 左侧可查看已有表及结构。 |
| 插入、更新报类型或长度错误 | 核对列类型、值个数、整数范围、TEXT 的 UTF-8 字节长度。变长更新还受原记录占用空间限制。 |
| 新启动后看不到原数据 | 确认使用的是**同一个绝对数据库目录**；相对路径会随启动时的工作目录变化。 |
| SQL 报语法错误 | 核对第 4 节支持范围；当前不接受 SQL 注释、多条件 `WHERE` 或其他完整 SQL 语法。 |

若脚本包含错误但后面的语句仍执行，这是既定行为；可在 CLI 错误输出或 GUI 会话记录中定位失败语句。

## 7. 验证安装与进一步阅读

在仓库根目录运行全部自动测试：

```powershell
python -m unittest discover -s tests -v
```

测试会使用临时目录，不会写入你指定的正式数据库目录。更多信息见[图形界面操作细节](08-gui-guide.md)、[需求与范围](01-requirements.md)、[架构与接口](02-architecture-and-interfaces.md)。
