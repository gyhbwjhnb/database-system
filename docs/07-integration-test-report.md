# 三模块集成测试记录（2026-10-22）

## 集成基线

- A 存储模块：远端 `main`，提交 `a682f7c`。
- B SQL 前端与 CLI：`feature/frontend`，提交 `ec515d5`。
- C 执行引擎：`feature/executor`，提交 `1bff7dd`。
- 本地集成分支：`integration/all-components`。按 A → B → C 合并，保留原始提交历史。仅 `tests/__init__.py` 和 `tests/unit/__init__.py` 的说明文字发生冲突，已保留可用的包标记与原有说明。

## 环境与命令

- 环境：Windows、Python 3.10.19；项目依赖 Python 标准库。
- 完整回归：`python -m unittest discover -s tests -v`。
- 集成专项：`python -m unittest discover -s tests/integration -v`。
- 演示脚本：集成测试在全新临时数据库目录中通过 `python -m dbms --db <临时目录> --file examples/demo.sql` 实际运行，随后关闭并重新打开数据库核对数据。

## 实际结果

| 检查项 | 结果 |
| --- | --- |
| 全套单元与集成测试 | 123 个通过，0 失败，0 跳过 |
| 三项端到端测试 | 全部通过 |
| 建表、插入、无索引等值查询 | 通过；查询显示 `SeqScan` |
| 建索引后重复键等值查询 | 通过；查询显示 `IndexEqScan`，结果与建索引前一致 |
| 修改索引列、删除对应行 | 通过；旧键、新键及删除后的查询结果正确 |
| CLI 遇到错误后继续处理脚本 | 通过；最终进程返回非零状态，后续有效插入仍保留 |
| 关闭并重新打开数据库 | 通过；最终仅剩 `(2, 'Bob', 60)` |
| 缓存命中、淘汰、脏页写回 | A 的存储单元测试通过 |

本轮没有改动 A、B 的模块接口或内部实现。新增的 `test_demo_script_runs_in_fresh_database` 用真实 CLI 执行演示脚本，并在重新打开数据库后检查最终行。

## 当前边界

课程 MVP 仍不提供事务回滚、异常断电恢复和多进程并发。此处的通过结果针对上述测试场景与运行环境；提交最终作业前，组员还应在目标提交版本上再次运行同一命令并记录结果。
