# C 部分：执行引擎实现与交接

## 实现范围

公开入口为 `from dbms.executor import execute`，签名 `execute(plan, storage) -> Result`。执行器只使用 `StoragePort`，不读取磁盘文件、不解析 SQL、不打印结果。

| 计划 | 执行行为 |
| --- | --- |
| `CreateTablePlan`、`CreateIndexPlan` | 调用对应存储方法，返回约定标签 |
| `InsertPlan` | 插入一行，`affected_rows=1` |
| `SelectPlan` | 按计划扫描或索引查找、复核谓词、按列名顺序投影 |
| `UpdatePlan` | 先收集全部匹配行，再生成整行新值并逐个更新 |
| `DeletePlan` | 先收集全部匹配行，再按 RID 逐个删除 |

执行器支持 `=`, `!=`, `<`, `<=`, `>`, `>=` 六种谓词比较。`index_eq` 仅用于等值谓词；即使存储层返回额外候选行，执行器仍按当前行值复核。结果行顺序不作保证。写入失败时异常直接交给 CLI；课程 MVP 不提供事务回滚，因此批量更新中途失败可能已有部分行被修改。

## 测试和演示

在项目根目录运行：

```powershell
python -m unittest discover -s tests -v
```

截至 C 模块独立开发阶段，执行器的 7 个单元测试通过；2 个集成测试已写好，因 A 的 `StorageEngine` 与 B 的 `parse`、`plan`、CLI 尚未接入而跳过。集成测试覆盖索引前后同结果、重复键、索引列更新、删除、关闭重开，以及 CLI 错误后继续执行。三方合并后应重新运行，要求不再出现跳过项。

三方合并后的实际结果见 [07 集成测试记录](07-integration-test-report.md)：完整测试 123 个通过，0 跳过。

接入完成后，用全新数据库目录运行：

```powershell
python -m dbms --db .\demo_data --file .\examples\demo.sql
```

演示脚本依次展示无索引查询、建索引后的查询、修改索引列、删除及最终查询。预期先看到 `SeqScan`，后看到 `IndexEqScan`。每次演示请使用新目录，因为脚本含建表语句。

## 合并检查

1. A 确认 `scan` 与 `lookup_eq` 返回 `RowRef`，`update` 接收整行元组并保持 RID 稳定。
2. B 确认 `SelectPlan.columns` 已展开 `*`，索引等值计划使用 `access='index_eq'`，CLI 导入 `execute` 并显示 `plan_label`。
3. C 运行全套单元和集成测试，再现场运行演示脚本；测试失败时附 SQL、预期、实际与堆栈，交给对应模块负责人修复。
