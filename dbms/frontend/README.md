# B 部分：SQL 前端与命令行

本模块完成分工文档 B1—B6。仅依赖 Python 3.10+ 标准库，公开接口保持不变：

```python
from dbms.frontend import parse, plan

statement = parse("SELECT name FROM students WHERE id = 1;")
query_plan = plan(statement, catalog)
```

`catalog` 只需实现共享协议中的 `get_schema(table)` 和 `has_index(table, column)`。
`parse` 只做词法和语法解析；`plan` 校验元数据和字面量，返回 `dbms.types` 中的计划数据类。

## 文件与实现方法

| 文件 | 职责 |
| --- | --- |
| `lexer.py` | 顺序扫描 SQL，记录 token 的偏移与行列；识别关键字、ASCII 标识符、整数、字符串、符号 |
| `parser.py` | 递归下降解析六类语句，生成冻结的 Statement；拒绝多语句和未支持的语法 |
| `planner.py` | 检查表列、列数、重复列、值类型及范围；展开通配符；选择扫描路径 |
| `cli.py` | 脚本分句、交互输入、解析/规划/执行调度、结果表格与错误呈现、存储关闭 |
| `../__main__.py` | `python -m dbms` 入口 |
| `../../tests/unit/test_frontend*.py` | 模拟目录和执行函数上的独立测试 |

前端不读写堆文件或索引，不扫描或过滤行。CLI 调用 C 的 `execute`，存储由 A 的 `StorageEngine` 提供。

## 支持的 SQL

```sql
CREATE TABLE students (id INT, name TEXT, score INT);
CREATE INDEX idx_students_id ON students (id);
INSERT INTO students VALUES (1, 'Alice', 90);
SELECT id, name FROM students WHERE id = 1;
SELECT * FROM students WHERE score >= 60;
UPDATE students SET score = 95 WHERE id = 1;
DELETE FROM students WHERE id = 1;
```

- 标识符以 ASCII 字母或 `_` 开头，后接字母、数字或 `_`；统一小写。已识别的 SQL 关键字作为保留字，不能用作未加引号的名称；不支持引号标识符。
- 关键字大小写不限，字符串内容保留大小写。字符串中的 `'` 用 `''` 表示，例如 `'O''Brien; A'`，其中分号不会分句。
- 整数可带紧邻数字的负号；INT 为有符号 64 位整数。TEXT 按 UTF-8 字节数最多 255 字节，空字符串合法。不支持 NULL、浮点数和隐式类型转换。
- SELECT 只支持单表、`*` 或列清单；WHERE 最多一个 `列 运算符 字面量`，支持 `= != < <= > >=`。
- INSERT 按 schema 顺序提供全部值；UPDATE 一次赋值一列。UPDATE、DELETE 可以没有 WHERE，此时作用于全表。
- `parse` 接收一条语句，允许一个结尾分号。多条 SQL 由 CLI 在字符串外的分号处切分。脚本最后一条可省略分号。
- 不支持 SQL 注释、连接、排序、聚合、事务等需求文档列出的非目标。

## 语义与计划

未知表/列、列数错误、重复建表列使用 `SchemaError`；类型错误、整数溢出、TEXT 超长使用 `TypeMismatchError`；非法 SQL 使用 `SQLSyntaxError`。
建表重名、索引重名和同列重复索引按契约由存储层最终检查。

`SELECT *` 按 schema 列序展开。SELECT、UPDATE、DELETE 仅在 WHERE 为 `=` 且该列有索引时选择 `index_eq`；范围、不等、无谓词或无索引时使用 `seq`。查询结果的行顺序由契约规定为未定义。

## 运行

在仓库根目录执行：

```powershell
python -m dbms --help
python -m dbms --db .\demo_data
python -m dbms --db .\demo_data --file .\your_script.sql
```

交互模式支持多行 SQL，输入分号后执行，可以一行输入多条；在字符串外单独一行输入 `.exit` 会放弃尚未提交的输入并退出。字符串内的 `.exit` 行仍作为字符串内容。EOF 会执行尚未以分号结束的最后一条 SQL，再关闭存储。
在 Windows 终端，EOF 通常用 Ctrl+Z 后回车；Ctrl+C 中断本次程序并关闭存储。
脚本使用 UTF-8 编码，也兼容 UTF-8 BOM。结果包含执行器给出的计划标签；查询显示列名和表格，写操作显示影响行数。`--buffer-pages N` 可指定正整数缓存页数，默认 64。
表格按常见终端中中日韩字符的双宽、组合字符的零宽做对齐，并转义换行及控制字符。终端字体或复杂 emoji 的显示宽度可能存在差异。

一条 SQL 的约定错误会显示在标准错误并继续处理后续语句。脚本存在错误时最终退出码非零；关闭存储失败也会报告错误。
未闭合字符串内没有可靠的分句边界，因此该字符串之后的内容会作为同一错误语句处理。

## 独立验证与集成边界

```powershell
python -m unittest discover -s tests -v
python -m unittest discover -s tests/unit -p "test_frontend*.py" -v
```

测试只使用模拟目录、模拟执行函数和临时脚本，验证 B 自己的输入/计划/输出与资源生命周期，不访问生产数据库。
`tests/__init__.py` 与 `tests/unit/__init__.py` 使仓库规定的 unittest 发现命令能进入测试子目录。

本次仓库基线中的 A、C 包仅有占位说明。因此 `--help` 和 B 单元测试可以独立运行；实际数据库 CLI 操作需要 A 导出 `StorageEngine`，C 导出 `execute`。
缺少这两个导出时，CLI 会清楚报告依赖尚未实现。此交付不补写 A/C，也不声称磁盘持久化、索引维护或全系统集成已通过。
真实 A/C 合入后的端到端与重启验证由 C 按 `docs/04-testing-and-delivery.md` 组织。

实际测试环境、命令和结果见同目录 `TEST_REPORT.md`。
