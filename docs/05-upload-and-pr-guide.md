# 05 组员上传细则与验收要求

本文件用于三位组员把各自实现上传到同一个仓库：[gyhbwjhnb/database-system](https://github.com/gyhbwjhnb/database-system)。目标是让每次上传都能独立审查、测试，并最终合并为一个可运行程序。这里的流程是**小组协作约定**，不是教师课件新增的要求；功能验收仍以 [01 需求与范围](01-requirements.md) 和 [03 分工计划](03-team-plan.md) 为准。

## 1. 上传到哪里

| 成员 | 必须上传的实现 | 对应测试与材料 | 不应自行改动 |
| --- | --- | --- | --- |
| A：存储与缓存 | `dbms/storage/`，并在其中的 `__init__.py` 导出 `StorageEngine` | `tests/unit/test_storage*.py`；存储格式与缓存说明 | `dbms/frontend/`、`dbms/executor/` |
| B：SQL 前端与界面 | `dbms/frontend/`，导出 `parse`、`plan`；`dbms/__main__.py` 实现命令行入口 | `tests/unit/test_frontend*.py`；运行与 SQL 使用说明 | `dbms/storage/`、`dbms/executor/` |
| C：执行与集成 | `dbms/executor/`，导出 `execute` | `tests/unit/test_executor*.py`、`tests/integration/`、`examples/demo.sql`；集成结果 | `dbms/storage/`、`dbms/frontend/` |

`dbms/types.py`、`dbms/contracts.py`、`docs/02-architecture-and-interfaces.md` 是共享接口。任何成员若发现确需修改，先在 PR 里说明具体调用、旧行为和新行为，同时修改代码契约、文档及相关测试；请另外两位成员审阅后合并。不得只在自己模块中复制或重定义共享类型。

`tests/` 和 `examples/` 目前用 `.gitkeep` 保存空目录。添加真实文件后可删掉同目录的 `.gitkeep`。最终仓库中代码文件与测试文件都应在上述对应位置，不能只上传截图、压缩包或报告。

## 2. 权限准备：选择一种方式

### 方式一：受邀为仓库协作者（推荐）

仓库所有者在 [Settings → Collaborators](https://github.com/gyhbwjhnb/database-system/settings/access) 输入组员 GitHub 用户名并发送邀请；组员必须接受邀请，之后才能直接向本仓库推送分支。邀请仅解决写入权限；仍按下文使用个人分支和 PR，不直接把未审查的代码推入 `main`。[GitHub 官方邀请说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/inviting-collaborators-to-a-personal-repository)

### 方式二：Fork 后提交 PR

如果暂未被邀请，组员可在仓库页面点击 **Fork**，把自己的代码推到个人 Fork，再从 Fork 向 `gyhbwjhnb/database-system` 的 `main` 发起 PR。下文命令里的 `origin` 应是组员自己的 Fork 地址。该仓库目前是公开的，因此可以采用此方式。[GitHub 官方 Fork PR 说明](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/creating-a-pull-request-from-a-fork)

## 3. 首次下载与建立分支

有协作者权限的组员执行：

```powershell
git clone https://github.com/gyhbwjhnb/database-system.git
cd database-system
git switch main
git pull origin main
git switch -c feature/storage
```

最后一行按人替换：A 用 `feature/storage`，B 用 `feature/frontend`，C 用 `feature/executor`。若同名分支已经存在，不要再次执行 `-c`；用 `git switch <分支名>` 切换，或者为下一次任务新建更具体的分支，例如 `feature/storage-index`。Fork 方式先在网页创建 Fork，再克隆**自己的 Fork URL**；其余步骤相同。

首次下载后可确认共享接口能导入：

```powershell
python -c "import dbms.types, dbms.contracts; print('接口可导入')"
```

## 4. 每次上传前必须完成

1. 把源码、测试和必要说明放到第 1 节规定的位置，确认公开导入路径与 [02 接口文档](02-architecture-and-interfaces.md) 一致。
2. 在干净的临时数据库目录测试；不要把自己电脑上的 `catalog.json`、`.heap`、`.idx`、`demo_data/`、虚拟环境、编辑器配置、密码或 Token 提交到 Git。
3. 运行当前能执行的测试，并记录**实际命令与实际结果**。仓库还没有完整实现时，其他成员的测试可能未出现；在 PR 中说明已运行的模块测试和暂时无法运行的测试。
4. 用 `git status` 检查本次修改；只暂存自己的模块、对应测试和经过协商的共享文件。

统一的完整测试命令是：

```powershell
python -m unittest discover -s tests -v
```

模块开发中可以先运行自己的测试文件；集成阶段应运行完整命令。测试未通过时不要写“全部通过”，应列出失败用例和处理计划。

## 5. 提交与推送命令

以下命令在第 3 节创建的个人分支中执行。先根据自己的角色暂存文件：

```powershell
# A：存储与缓存
git add dbms/storage tests/unit/test_storage*.py

# B：SQL 前端与界面
git add dbms/frontend dbms/__main__.py tests/unit/test_frontend*.py

# C：执行与集成
git add dbms/executor tests/unit/test_executor*.py tests/integration examples
```

PowerShell 中路径通配符若没有匹配文件会报错；测试文件尚未写好时，先创建测试或只暂存已存在的具体路径。然后执行：

```powershell
git status
git diff --cached --stat
git commit -m "Implement storage module"
git push -u origin feature/storage
```

示例提交信息和分支名需按实际角色或任务替换。一次提交尽量只完成一项清楚的任务，例如 `Implement SQL parser` 或 `Add index lookup tests`。不要用 `git add .` 把无关文件一起上传。首次推送带 `-u`，同一分支后续更新可直接 `git push`。

如果 `git push` 提示无权限，先确认是否接受了协作者邀请、是否登录了正确的 GitHub 账号；暂未获写入权限时改用 Fork。不要把账号密码或访问令牌提交到项目里。

## 6. 在 GitHub 上发起 PR

1. 推送后打开仓库页面，点击 **Compare & pull request**；也可在 **Pull requests → New pull request** 选择分支。
2. 确认 **base** 是 `gyhbwjhnb/database-system:main`，**compare** 是自己的功能分支。Fork 方式须在 head fork 选择自己的 Fork。
3. 按仓库 PR 模板填写任务编号、改动文件、测试命令和结果、接口变化及已知限制。
4. 创建 PR，请其他组员检查；发现问题就在原分支继续提交并 `git push`，PR 会自动更新。
5. 审查通过后由仓库所有者或集成负责人合并。合并后，其他成员先更新各自的 `main`，再开展依赖这些代码的新工作。[GitHub 官方 PR 说明](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/creating-a-pull-request)

合并前核对：文件在正确目录；公开符号能导入；没有修改别人的模块或绕过共享接口；测试结果真实；没有生成的数据文件或凭据；PR 目标分支是 `main`。

## 7. 后续同步与冲突处理

有协作者权限的组员开始新任务前：

```powershell
git switch main
git pull origin main
git switch -c feature/storage-index
```

上例的分支名按自己的任务替换。Fork 方式先在 GitHub 上使用 **Sync fork** 更新个人 Fork 的 `main`，再在本地执行 `git switch main` 和 `git pull origin main`。不要在同一工作目录里一边保留未提交修改、一边直接切换到 `main` 拉取；先提交或妥善保存自己的工作。出现合并冲突时，先确认冲突文件的负责成员和共享接口含义，保留正确实现，运行相关测试，再提交解决结果。不要用强制推送覆盖他人的 `main` 或功能分支。

## 8. 分工验收清单

| 成员 | PR 中最少展示的证据 |
| --- | --- |
| A | 表创建、插入/扫描、重启持久化、索引重复键及更新删除一致性、缓存命中/淘汰测试 |
| B | 六类语句的解析与错误处理、索引/全表计划选择、CLI 输入和脚本运行测试 |
| C | 计划执行、过滤与投影、影响行数、索引候选复核、端到端演示与重启查询 |

这些证据可以分阶段提交多个 PR；不要求一次提交全部完成。但每个 PR 必须说明自己已实现的范围，不能把未来计划写成已完成内容。最终提交材料仍按 [04 测试与提交规范](04-testing-and-delivery.md) 检查。
