# 数据库管理系统课程大作业：三人协作设计

本目录是一套可供三人并行开发、最终合并的项目规范。**接口基线 v1 已固定**：共享类型见 `dbms/types.py`，存储端口和函数签名见 `dbms/contracts.py`，行为规则见 `docs/02-architecture-and-interfaces.md`。三人可以直接按各自模块开工。

## 从题目图片确认的要求

题目为“设计一个数据库管理系统”，要求按软件工程规范开发，3～4 人组队且分工明确。系统应有存储管理器、缓存管理器、查询处理器、执行引擎和用户界面。提交报告时还需提交**源代码、可执行程序、使用说明、各模块实现方法及相关测试报告，以及小组成员的分工和完成任务情况说明**。

图片没有规定编程语言、数据库文件格式、必须支持的 SQL 子集、索引类型、事务或并发级别。以下文档中的这些选择是本组建议方案，需要在开工前统一，不应当表述为教师原文要求。

## 推荐实现基线

- Python 3.10+，仅用标准库实现数据库核心；不得调用 SQLite、DuckDB 等现成数据库代替核心模块。
- 单进程命令行程序，数据持久化到本地目录；无需网络服务、图形界面或多用户并发。
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
| [dbms/types.py](dbms/types.py) | 已固定的 AST、Plan、行、结果和异常类型 |
| [dbms/contracts.py](dbms/contracts.py) | 存储公开方法与前端/执行函数的类型签名 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | GitHub 目录分工、分支、上传与 PR 步骤 |

## 仓库目录和上传位置

一个 GitHub 仓库即可；三人分别在自己的分支提交，再合并到 `main`。A 上传 `dbms/storage/` 与对应单元测试，B 上传 `dbms/frontend/`、`dbms/__main__.py` 与对应单元测试，C 上传 `dbms/executor/`、集成测试和 `examples/demo.sql`。共享接口与设计文档已在仓库初始版本中，后续改动应通过 PR 审阅。具体命令和验收要求见[组员上传细则](docs/05-upload-and-pr-guide.md)。

## 现在可以开始的工作

1. A 实现 `dbms/storage/StorageEngine`；B 实现 `dbms/frontend/parse`、`plan` 和 CLI；C 实现 `dbms/executor/execute`。详细任务与验收见 `docs/03-team-plan.md`。
2. 每人用自己的模拟对象和单元测试并行开发，按已固定的共享代码导入类型。共享接口变更须同步更新代码契约、02 文档和相关测试。
3. C 负责集成协调，A/B 共同审核集成结果；若课程另有要求，再按实际通知调整技术范围。
