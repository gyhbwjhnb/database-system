# 存储模块实现说明（成员 A）

本模块实现数据库的**存储管理器、缓存管理器和持久化等值索引**，对外只通过
`StorageEngine` 提供服务，满足 `dbms.contracts.StoragePort` 协议。仅使用 Python
标准库，不依赖任何现成数据库。

```python
from dbms.storage import StorageEngine
```

## 1. 模块文件

| 文件 | 职责 | 对应任务 |
| --- | --- | --- |
| `engine.py` | `StorageEngine`，整合各组件、做 API 边界校验 | A4 |
| `catalog.py` | `catalog.json` 元数据读写（表结构、索引定义） | A1 |
| `disk.py` | 堆文件的原始页 I/O | A2 |
| `page.py` | 定长页、槽目录、记录/字段编解码 | A2 |
| `buffer.py` | LRU 页缓存、脏页写回、统计计数 | A3 |
| `heap.py` | 记录级插入/扫描/更新/删除 | A2/A4 |
| `index.py` | 持久化等值哈希索引 | A5 |

## 2. 磁盘文件布局

```
<db_dir>/
  catalog.json                 # 版本、表结构、索引定义
  tables/<table>.heap          # 4096 字节定长页，页号从 0 开始
  indexes/<table>__<column>.idx  # 等值哈希索引（JSON）
```

- `catalog.json` 与索引文件都采用“写临时文件 + `os.replace` 原子替换”，避免
  半写入。
- 表、索引、列标识符统一转小写；字符串值保留大小写。

## 3. 页格式（4096 字节）

```
[ 页头：uint16 槽数, uint16 空闲边界 ]
[ 槽目录：每项 uint16 偏移 + uint16 长度 + uint8 标志，向后增长 ]
[ 空闲空间 ]
[ 记录：从页尾向前增长 ]
```

- 槽标志 `0=有效，1=已删除`；删除只置标志，**RID 保持稳定**。
- 插入时从最后一页向前找第一个能放下的页，都放不下才分配新页。
- 空闲空间 = 空闲边界 − 槽目录当前末尾。

## 4. 记录编码

一条记录以 `uint16 总长度` 开头，随后是按 schema 顺序拼接的自描述字段：

- `INT`：`标记 'I' + int64 大端有符号`（9 字节）。
- `TEXT`：`标记 'T' + uint16 UTF-8 字节长度 + 字节`。

记录的长度前缀使记录在固定槽内**缩短或原地增长**都不会读到残留字节：解码只
信任长度前缀，不依赖槽的物理长度。

## 5. LRU 缓存

- 以 `(table, page_no)` 为键，容量由 `buffer_pages` 限定（默认 64 页）。
- 命中移动到最近端；缓存满时淘汰最久未用页，**脏页先写回磁盘**。
- `flush` 写回全部脏页；`close` 先 `flush` 再关闭文件句柄。
- 统计计数 `hits / misses / evictions / dirty_flushes` 通过
  `get_buffer_stats()` 以 `BufferStats` 快照返回。

## 6. 持久化等值索引

- 单表单列的哈希索引，整体驻留内存，以 JSON 持久化。
- 键编码稳定且区分类型：整数 `42` 为 `"I:42"`，文本 `"42"` 为 `"T:42"`，
  不使用 Python 运行期随机哈希。
- 允许重复键，键映射到 RID 列表，重复 RID 不会被重复加入。
- `CREATE INDEX` 会扫描已有行回填；`INSERT` 加键，`DELETE` 移除键，
  `UPDATE` 改索引列时先移除旧键、再加入新键。
- `lookup_eq` 返回该键对应的当前行；无索引时抛 `SchemaError`。

## 7. 校验与错误

| 规则 | 异常 |
| --- | --- |
| 表/列/索引不存在、重复表名、重复索引名、同列重复索引、列数不符 | `SchemaError` |
| 值类型不符、`bool` 当作 INT、整数越界、TEXT 超 255 字节 | `TypeMismatchError` |
| 更新后记录超过槽的物理空间、操作已删除/不存在的 RID、引擎已关闭 | `StorageError` |

- `INT` 范围 `[-2^63, 2^63-1]`；`TEXT` 按 UTF-8 字节数最多 255。
- 标识符须为 ASCII 字母/下划线开头、后接字母数字下划线。

## 8. 已知限制（MVP）

- 更新为原地更新，记录编码不得超过该槽已分配的物理空间，否则抛
  `StorageError`（不迁移 RID）。
- 删除后的槽空间不做页压缩/复用（属增强项）。
- 索引仅支持等值查询，不支持范围索引。
- 不支持事务、并发、崩溃原子恢复、`NULL`、主键/外键约束。

## 9. 测试

```powershell
python -m unittest discover -s tests -v
```

存储单元测试 `tests/unit/test_storage.py` 覆盖建表/插入/扫描、跨页、删除标记、
序列化边界、LRU 命中/淘汰/脏页写回、索引重复键与回填、更新/删除索引一致性，
以及关闭重开后的持久化恢复，共 31 个用例，全部在临时目录中可重复运行。
