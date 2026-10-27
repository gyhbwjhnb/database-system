# 数据库管理系统课程大作业

这是一个已集成的教学用关系数据库管理系统。它实现 SQL 解析与计划、执行、磁盘页存储、LRU 缓存、持久化等值索引，以及命令行和可选的桌面图形界面。核心使用 Python 3.10+ 标准库，不依赖 SQLite 等现成数据库。

**第一次使用请阅读[完整使用手册](docs/09-user-manual.md)**，其中包括安装、GUI/CLI 操作、SQL 语法、数据备份和常见错误。

## 快速开始

在仓库根目录运行桌面界面：

```powershell
python -m dbms.gui --db .\gui_data
```

Windows 用户也可以双击根目录的 `launch_gui.pyw`；它默认使用 `gui_data/`。如果 `.pyw` 文件没有关联 Python，可在 PowerShell 中运行 `pythonw .\launch_gui.pyw`。窗口内可切换数据库目录、输入或加载 SQL、查看表结构和查询结果。操作细节见[图形界面使用指南](docs/08-gui-guide.md)。桌面界面依赖 Python 自带的 Tkinter；若 Python 安装时未包含 Tkinter，可继续使用下方命令行入口。

命令行交互与脚本运行：

```powershell
python -m dbms --db .\demo_data
python -m dbms --db .\demo_data --file .\examples\demo.sql
```

演示脚本包含建表语句，请在全新数据库目录运行。使用同一个 `--db` 目录重新启动，可读取之前保存的数据。运行全部测试：

```powershell
python -m unittest discover -s tests -v
```

## 从题目图片确认的要求

题目为“设计一个数据库管理系统”，要求按软件工程规范开发，3～4 人组队且分工明确。系统应有存储管理器、缓存管理器、查询处理器、执行引擎和用户界面。提交报告时还需提交**源代码、可执行程序、使用说明、各模块实现方法及相关测试报告，以及小组成员的分工和完成任务情况说明**。

图片没有规定编程语言、数据库文件格式、必须支持的 SQL 子集、索引类型、事务或并发级别。以下文档中的这些选择是本组建议方案，需要在开工前统一，不应当表述为教师原文要求。

## 推荐实现基线

- Python 3.10+，仅用标准库实现数据库核心；不得调用 SQLite、DuckDB 等现成数据库代替核心模块。
- 单进程程序，数据持久化到本地目录；提供命令行与 Tkinter 桌面界面，不提供网络服务或多用户并发。
- 支持 `CREATE TABLE`、`CREATE INDEX`、`INSERT`、`SELECT`、`UPDATE`、`DELETE` 的约定子集；语法见[需求与范围](docs/01-requirements.md)。
- 4096 字节定长数据页、LRU 缓存、基于等值查询的持久化哈希索引；查询规划至少能在全表扫描和索引扫描之间作选择。
- 三个人分别负责：①存储与缓存，②SQL 前端与命令行，③执行引擎与集成。具体边界、交付物和合并顺序见[分工计划](docs/03-team-plan.md)。

## 文档导航

| 文件 | 用途 |
| --- | --- |
| [docs/01-requirements.md](docs/01-requirements.md) | 题目要求、建议 SQL 范围、验收标准 |
| [docs/02-architecture-and-interfaces.md](docs/02-architecture-and-interfaces.md) | 架构、磁盘结构、跨模块接口与语义 |
| [docs/03-team-plan.md](docs/03-team-plan.md) | 三人任务、依赖、集成节奏、协作规则 |
| [docs/04-testing-and-delivery.md](docs/04-testing-and-delivery.md) | 测试矩阵、演示脚本、最终提交清单 |
| [docs/05-upload-and-pr-guide.md](docs/05-upload-and-pr-guide.md) | 三人上传目录、权限、Git 命令、PR 和验收细则 |
| [docs/06-executor-implementation.md](docs/06-executor-implementation.md) | 执行器实现与交接 |
| [docs/07-integration-test-report.md](docs/07-integration-test-report.md) | 三模块集成测试记录 |
| [docs/08-gui-guide.md](docs/08-gui-guide.md) | 桌面图形界面使用说明 |
| [docs/09-user-manual.md](docs/09-user-manual.md) | 从零开始的完整使用手册 |
| [dbms/types.py](dbms/types.py) | 已固定的 AST、Plan、行、结果和异常类型 |
| [dbms/contracts.py](dbms/contracts.py) | 存储公开方法与前端/执行函数的类型签名 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | GitHub 目录分工、分支、上传与 PR 步骤 |

## 仓库目录和上传位置

一个 GitHub 仓库即可；三人分别在自己的分支提交，再合并到 `main`。A 上传 `dbms/storage/` 与对应单元测试，B 上传 `dbms/frontend/`、`dbms/__main__.py` 与对应单元测试，C 上传 `dbms/executor/`、集成测试和 `examples/demo.sql`。共享接口与设计文档已在仓库初始版本中，后续改动应通过 PR 审阅。具体命令和验收要求见[组员上传细则](docs/05-upload-and-pr-guide.md)。

## 当前实现范围

系统支持 `CREATE TABLE`、`CREATE INDEX`、`INSERT`、`SELECT`、`UPDATE`、`DELETE`，列类型为 `INT` 和 `TEXT`。`WHERE` 最多一个条件；索引等值查询会选择 `IndexEqScan`，其他查询使用 `SeqScan`。不支持连接、排序、聚合、事务和并发操作。详细 SQL 规则见[需求与范围](docs/01-requirements.md)。
