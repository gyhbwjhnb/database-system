# B 部分测试与完成记录

- 验证日期：2026-10-19（Asia/Shanghai）。
- 仓库：`https://github.com/gyhbwjhnb/database-system`。
- 原始基线：`e282fce25006ba9dea84d911a9bc48ab92860d49`。
- 交付分支：`feature/frontend`，按仓库协作约定经功能分支与 PR 供小组审阅后合入 `main`。
- 环境：Windows / PowerShell / Python 3.12.10，标准库，无第三方运行依赖。
- 公共接口：未改 `dbms/types.py`、`dbms/contracts.py` 或共享接口文档；A、C 实现目录未改。

## 实际测试结果

在仓库根目录运行：

```powershell
python -m unittest discover -s tests -v
```

实际结果：**Ran 82 tests / OK，0 失败、0 错误**。部分测试方法使用 subTest 覆盖多组输入；82 为 unittest 报告的方法数量。

| 测试文件 | 测试方法数 | 代表输入与预期 | 实际结果 |
| --- | ---: | --- | --- |
| `test_frontend_parser.py` | 15 | 六类 SQL 生成精确 AST；`'O''Brien; A'` 保留内容；多语句、注释、错误运算符及超出子集的语法被拒绝 | 通过 |
| `test_frontend_planner.py` | 29 | SELECT 通配符展开；INT64 边界；255/256 UTF-8 字节；未知表列、列数、类型、重复列；bool 不作为 INT；三种读写计划的索引/全表选择 | 通过 |
| `test_frontend_cli.py` | 35 | 引号内分号不切分；多行输入；BOM；三阶段错误后继续；退出码、关闭失败、Ctrl+C、程序错误不被吞掉；中文/组合字符表格对齐 | 通过 |
| `test_frontend_workflow.py` | 3 | 使用真实 parse/plan 连通六类 CLI 输入；语法/类型错误不会到达假执行器且后续 SQL 继续；交互字符串转义 | 通过 |

额外运行：

```powershell
python -m dbms --help
python -m dbms --db .\missing_backend_check
git diff --check
```

- `--help`：退出码 0，显示 `--db`、`--file` 和 `--buffer-pages`。
- 缺少 A/C 实现时启动数据库：退出码 1，错误明确列出 `dbms.storage.StorageEngine` 和 `dbms.executor.execute` 尚不可用，未创建数据库目录。
- `git diff --check`：通过。

## B1—B6 完成对应

| 编号 | 实际完成 |
| --- | --- |
| B1 | tokenizer 识别关键字、标识符、负整数、转义单引号、比较符和分号，并保留错误位置 |
| B2 | 六类 SQL 的递归下降 parser；只接受单条 SQL 和可选结尾分号 |
| B3 | 规划前校验表列、列数、数据类型、范围、重复列及合法比较操作 |
| B4 | 六类冻结 Plan；仅等值且对应列有索引时用 `index_eq`，其余用 `seq` |
| B5 | 交互/UTF-8 脚本 CLI，结果表格与计划标签，错误续执行及退出关闭 |
| B6 | 前端单测、CLI 及 B 链路测试，README 使用说明和本报告 |

## 发现及修正

- 常规字符串长度无法准确对齐中文结果：改为标准库字符宽度计算，并增加中文、组合重音字符测试。
- 多行输入等待分号时需要明确退出方式：字符串外的独立 `.exit` 行丢弃未提交内容后退出；字符串内仍视为字面内容，新增对应测试。
- Python 对超长十进制字符串存在转换限制：parser 采用分块转换，不修改解释器全局设置；INT64 溢出由 planner 按契约报告。

## 验证边界

所有数据库边界使用模拟目录/存储接口与返回固定 Result 的假执行函数。测试数据保存在临时目录，不访问真实生产数据库。
真实 B 模块的语法、语义、计划、CLI 调度与显示已验证；假执行函数只验证调用契约，不替代 C 的行处理，也不实现 A 的持久化。
原始仓库的 A/C 仍为占位包，因此全系统读写、索引维护、真实缓存统计、落盘重启和跨模块集成尚未验证，待 A/C 合入后由 C 组织。
Python 3.10 是项目目标最低版本，本次实际执行版本为 3.12.10；未声称在 3.10 解释器上运行过。

报告署名及学号须由实际提交成员填写，未虚构小组身份。
