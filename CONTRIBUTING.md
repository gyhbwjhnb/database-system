# 三人协作与上传规则

本项目使用**一个 GitHub 仓库**，按模块目录分工，不需要为三个人分别创建仓库。以 `main` 为稳定版本；每个人在自己的分支开发，测试通过后发起 Pull Request（PR）合并到 `main`。初始文档与共享接口已经提交，后续直接从最新 `main` 开始。

若三人都要直接向同一仓库推送分支，仓库所有者需先在 GitHub 的 **Settings → Collaborators** 邀请另外两位成员，成员接受邀请后才有写入权限。当前没有两位成员的 GitHub 用户名，因此邀请尚未发送。也可以不邀请：成员各自 Fork 此公开仓库，在自己的 Fork 中推送分支，再向本仓库发起 PR；此时下文命令中的 `origin` 指向各自的 Fork。

| 成员 | 主要上传位置 | 对外导出 |
| --- | --- | --- |
| A：存储与缓存 | `dbms/storage/`、`tests/unit/test_storage*.py` | `from dbms.storage import StorageEngine` |
| B：SQL 前端与 CLI | `dbms/frontend/`、`dbms/__main__.py`、`tests/unit/test_frontend*.py` | `from dbms.frontend import parse, plan` |
| C：执行与集成 | `dbms/executor/`、`tests/unit/test_executor*.py`、`tests/integration/`、`examples/demo.sql` | `from dbms.executor import execute` |

共享文件 `dbms/types.py`、`dbms/contracts.py`、`docs/02-architecture-and-interfaces.md` 不由任何人单独改变。确需修改时，在 PR 中解释原因、同步修改文档和测试，并请另外两人审阅。

## 首次获取项目

```powershell
git clone <仓库地址>
cd database-system
python -c "import dbms.types, dbms.contracts; print('接口可导入')"
```

实际本地文件夹名由 `git clone` 命令决定；如果手工指定了其他目录名，按实际目录进入。

## 各自开发与上传

从 `main` 创建个人分支。例如 A：

```powershell
git switch main
git pull origin main
git switch -c feature/storage
# 修改 dbms/storage/ 和对应测试后
python -m unittest discover -s tests -v
git add dbms/storage tests/unit
git commit -m "Implement storage and buffer manager"
git push -u origin feature/storage
```

B 使用 `feature/frontend`，C 使用 `feature/executor`，并把 `git add` 的路径改为上表中的自己负责区域。三人分别在 GitHub 上从个人分支向 `main` 发起 PR；同伴审核后合并。后续继续开发时先 `git switch main`、`git pull origin main`，再创建新分支，避免长期分支与 `main` 脱节。

Git 不跟踪空目录，因此 `tests/` 和 `examples/` 里暂放 `.gitkeep`。开始加入真实测试或示例脚本后，可以删除相应 `.gitkeep`。

## PR 检查

1. 说明实现了分工文档中的哪项任务，列出关键文件。
2. 给出实际运行的测试命令和结果；如果尚无完整测试，说明缺口。
3. 说明是否改变共享接口；改变时指出已同步更新的代码契约、文档和测试。
4. 在新数据库目录中复查读写功能；不要提交 `catalog.json`、`.heap`、`.idx` 或个人开发环境文件。

详细任务及验收条件见 [分工计划](docs/03-team-plan.md)。
