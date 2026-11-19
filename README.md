# SynTime（与时偕行）

> 私有化部署的多云成本管理（FinOps）平台：把多云账单、资产台账、事件中心与项目成本分摊收口到一个自托管后台，让"钱花在哪、哪些在空烧、哪个项目超预算"一目了然。

[![Stars](https://img.shields.io/github/stars/sujx/syntime?style=social)](https://github.com/sujx/syntime/stargazers)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![Django](https://img.shields.io/badge/django-5.2-0C4B33)](https://www.djangoproject.com/)
[![Tests](https://img.shields.io/badge/tests-231%20passed-brightgreen)](#-开发与质量门)

**适合谁用**：需要向财务/管理层按期交代云开销、又不想把账单数据交给第三方 SaaS 的中小团队与个人开发者。本项目定位为**免费、可自托管的个人作品**，单组织部署、无多租户层，数据全部留在你自己的服务器上。

> 当前为开发中项目：后端地基与成本查询/聚合/自算检测链路已完成并通过测试；前端与云厂商同步适配器尚在推进。详见下方[实现进度](#-实现进度)。

---

## ✨ 项目亮点

- **口径守恒的成本分摊**：账单入库即按汇率折算为 CNY，标签归属（正常 / 未打标签 / 标签冲突）在入库时一次落定；预聚合按天覆盖写、不增量累加，重复跑不产生重复金额，负数退款行照常参与，金额可对平账单总额。
- **幂等到偏执**：六条业务唯一键（账单、同步窗口、日聚合、资产、事件、厂商消息）全部走"唯一键兜底 + upsert / 覆盖写 / 拒绝重复"，重复同步、重复扫描、并发触发都不脏数据。
- **凭据信封加密**：云账号 AK/SK 以 AES-256-GCM + HKDF 派生 + AAD 防挪用加密落库，日志层自动脱敏 AK / JWT / 键值，主密钥不落代码。
- **财务字段级隔离**：财务角色看到的成本数据中实例 ID 等敏感标识置空，权限按角色矩阵在序列化层统一收口。
- **平台自算检测**：厂商消息覆盖不到的两类风险由平台自己算——域名到期（T-30/T-7/T-1 + 过期）与项目预算超支，按业务键去重，重复扫描幂等。

## 🧱 技术栈

| 层 | 选型 |
| ---- | ---- |
| 语言 / 运行时 | Python 3.12 |
| Web 框架 | Django 5.2 + Django REST Framework 3.16 |
| 鉴权 | djangorestframework-simplejwt（JWT 登录 / 刷新 / 登出黑名单） |
| API 文档 | drf-spectacular（OpenAPI + Swagger UI） |
| 数据库 | PostgreSQL 17（psycopg 3），账单明细按 `bill_date` 分区 |
| 任务调度 | Celery 5.5 + Redis（beat 定时 + Redis 分布式互斥锁） |
| 加密 | cryptography（AES-256-GCM / HKDF） |
| 质量工具 | ruff（format + lint）、mypy（django/drf 插件）、pytest + pytest-django |
| 前端 | 待脚手架（规划 AntD 5 混合方案） |

## 📦 环境准备

- Python **3.12**（`>=3.12,<3.13`）
- [uv](https://github.com/astral-sh/uv)（本仓虚拟环境由 uv 管理，**环境内不含 pip**）
- PostgreSQL 17、Redis（Celery broker 与互斥锁）

## 🚀 快速开始

```bash
# 1. 克隆并进入后端目录
git clone https://github.com/sujx/syntime.git
cd syntime/backend

# 2. 建虚拟环境并安装开发依赖（Windows 路径示例；Linux/macOS 用 .venv/bin/python）
uv venv
uv pip install --python .venv/Scripts/python.exe -r requirements/dev.txt
```

3. 在 `backend/.env` 写入本地配置（**该文件已被 `.gitignore` 忽略，切勿提交真实凭据**）：

```dotenv
# Django
SYNTIME_SECRET_KEY=change-me
# 数据库（默认库名 syntime_dev、用户 syntime）
SYNTIME_DB_NAME=syntime_dev
SYNTIME_DB_USER=syntime
SYNTIME_DB_PASSWORD=change-me
SYNTIME_DB_HOST=localhost
SYNTIME_DB_PORT=5432
# AK/SK 信封加密主密钥：二选一
#   SYNTIME_MASTER_KEY_FILE=/abs/path/to/master.key   （密钥文件路径）
#   SYNTIME_MASTER_KEY=<base64 32 字节>               （直接给 base64）
# DEBUG 模式下若都未配置，会自动生成 backend/.masterkey_dev（已 gitignore）
# Celery（默认 redis://localhost:6379/0）
SYNTIME_CELERY_BROKER_URL=redis://localhost:6379/0
```

4. 初始化数据库与角色，然后启动：

```bash
python manage.py migrate          # 建表 + 字典/配置种子数据
python manage.py init_roles       # 幂等创建三角色 Group（成本管理员/云运维/财务人员）
python manage.py createsuperuser  # 建管理员账号
python manage.py shell -c "       # ← 给上面那个账号挂角色，否则登不进前端（见下）
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
u = get_user_model().objects.get(username='上一步的用户名')
u.groups.add(Group.objects.get(name='成本管理员'))
"
python manage.py runserver
```

⚠️ **`createsuperuser` 单独不够**：平台角色只认全局 Group（`common/permissions.py` 的 `get_role` 不看 `is_superuser`），无组的账号登录后 `/api/token/` 返回 `role=null`，前端会直接报「该账号未分配平台角色」。`/admin/` 用 superuser 照样能进，前端页面不行。

启动后：

- Swagger API 文档：<http://127.0.0.1:8000/api/docs/>
- OpenAPI schema：<http://127.0.0.1:8000/api/schema/>
- Django Admin：<http://127.0.0.1:8000/admin/>

5.（可选）跑定时任务：

```bash
celery -A config worker -l info   # 执行任务
celery -A config beat   -l info   # 调度：每月3日重算上月成本、每小时自算检测
```

## 🐳 容器部署（一条命令起全套）

不想在本机装 PostgreSQL / Redis / Node 工具链时，用仓库根的 `compose.yaml`：

```bash
cd syntime
cp .env.example .env      # 填 SYNTIME_SECRET_KEY / SYNTIME_DB_PASSWORD / SYNTIME_MASTER_KEY
docker compose up -d --build
```

起来的是 6 个容器：`db`(postgres:17-alpine) · `redis`(redis:8-alpine) · `init`(一次性 `migrate` + `init_roles`，幂等) · `web`(gunicorn×5 + WhiteNoise 同源托管前端) · `worker` · `beat`。前端在同一条命令里由镜像的 node 阶段构建（`tsc -b && vite build` 过不去就出不了镜像），宿主不需要装 Node。

```bash
docker compose --profile demo up -d   # 额外跑一次 seed_demo 灌演示数据
docker compose ps                      # 等 web 变 healthy
docker compose logs -f web worker beat
docker compose down                    # 停栈并保留数据；加 -v 连库带 beat 调度状态一起删
```

访问 <http://127.0.0.1:8000/>，Django Admin 在 `/admin/`。管理员账号不进容器初始化——`createsuperuser` 是交互式的，由你本人执行；**执行完还要给它挂一个角色组**，否则前端登录会被拒（原因见上面「初始化数据库与角色」那段末尾的 ⚠️）：

```bash
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py shell -c "
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
u = get_user_model().objects.get(username='上一步的用户名')
u.groups.add(Group.objects.get(name='成本管理员'))
"
```

**暴露面**：只有 `web` 发布端口，且只绑 `127.0.0.1`；`db` / `redis` 不发布任何宿主端口。要和已在跑 `backend/deploy_prod.sh`（占宿主 8000）的机器共存，`.env` 里改 `SYNTIME_WEB_PORT=8001` 即可。公网暴露需要先定 TLS 终结与防火墙——这两件不由 compose 文件替你决定。

**关键旋钮**（`.env.example` 内各有注释）：`SYNTIME_WEB_PORT`、`SYNTIME_WORKERS`（默认 5，PRD 4.1 的 P95 达标读数出自「5 并发 × 多进程」形状，调小会让 5 并发排队）、`SYNTIME_ALLOWED_HOSTS`、`NPM_REGISTRY`（国内换 npm 源）。

**主密钥**：`SYNTIME_MASTER_KEY` 缺失时栈照样能起，但一保存云账号 AK/SK 就抛 `ImproperlyConfigured`（它是信封加密的 KEK，见 `backend/common/crypto.py`）。因此 `init` 服务显式检查这一项并拒绝完成，把故障从"某次点击 500"提前到"部署当场"。

## 🧭 主要 API

所有接口返回统一信封 `{ code, message, data }`；错误码 `0` 成功、`40001` 参数错误、`40100` 未认证、`40300` 无权限、`40900` 冲突/任务进行中、`42900` 触发限流、`50000` 服务端错误。

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| POST | `/api/token/` | 登录，返回 JWT（附带 role / username） |
| POST | `/api/token/refresh/` | 刷新 access token |
| POST | `/api/token/verify/` | 校验 token |
| POST | `/api/auth/logout/` | 登出（token 进黑名单） |
| GET | `/api/cost/summary/` | 项目成本汇总（行转列、环比、预算占比、未分配成本归并） |
| GET | `/api/cost/details/` | 项目资源明细下钻（按实例聚合，财务角色屏蔽实例 ID） |
| GET | `/api/cost/trend/` | 成本趋势（连续逐日序列 + 等长比较区间 + 含预估标记） |

## 📁 项目结构

```
syntime/
├── compose.yaml    # 可移植容器栈：db/redis/init/web/worker/beat（+ demo profile 灌种子）
├── Dockerfile      # 多阶段：node:22-alpine 建前端 → python:3.12-slim 运行
├── .dockerignore   # 密钥与宿主构建产物不进镜像层
├── backend/
│   ├── apps/
│   │   ├── billing/    # 云账号、账单明细、汇率、资源类型字典、同步日志
│   │   ├── cost/       # 项目预算、成本日聚合、异步任务；查询 selector + 口径 services
│   │   ├── assets/     # 云资产台账（含域名资源）
│   │   ├── events/     # 事件、厂商消息流水、厂商映射；自算检测
│   │   ├── audit/      # 审计日志
│   │   └── core/       # 平台配置（platform_setting）等无业务归属项
│   ├── common/         # crypto 信封加密 / permissions 角色脱敏 / readers 两级回退
│   │                   # tasks 任务基类 / api 信封+异常+分页 / log_filters 脱敏
│   ├── providers/      # 厂商适配层基座（限速 + 注册表）
│   ├── config/         # settings 分环境（base/dev/prod/test）、celery、urls
│   ├── requirements/   # base / dev / prod 三件套
│   ├── tests/          # 接口与口径测试
│   └── pyproject.toml  # ruff / mypy / pytest 配置
├── db/schema/001_init.sql   # 15 张表 DDL 基准
└── frontend/                # 待脚手架
```

分层约定：`models`（表）→ `services`（写路径 + 纯口径函数）→ `selectors`（读路径）→ `serializers` → `views` → `tasks`。JSON 出参为 camelCase（手写，不依赖渲染器）。

## 📈 实现进度

**已完成并通过测试**

- 地基：信封加密、角色权限与字段脱敏、日志脱敏、两级回退读取器、Celery 任务基类（互斥锁 + 退避重试 + 审计钩子）、适配层限速基座
- API 基座：统一返回信封、异常码映射、分页、JWT 鉴权、三角色初始化
- 幂等写入层：六条唯一键的 upsert / 覆盖写 / 重复拒绝
- 成本查询接口 P0：汇总 / 明细下钻 / 趋势
- 成本预聚合任务：账单 → 日聚合覆盖写 + 每月全量重算
- 平台自算检测：域名到期、预算超支

**进行中 / 待开工**

- 云厂商同步适配器（账单 / 资产 / 消息）——本期仅阿里云，且需先完成 API 实测（Gate-P2a）再写映射，避免凭文档臆测
- 域名 CSV 批量导入、分区维护任务
- 前端（AntD 5 混合方案）、仪表盘与事件中心页面

## 🛠️ 开发与质量门

提交前需四道闸门全绿（在 `backend/` 下执行；uv 环境内已装好工具）：

```bash
ruff format --check .   # 格式
ruff check .            # lint（line-length 100）
mypy .                  # 类型检查（django + drf 插件）
pytest                  # 测试（DJANGO_SETTINGS_MODULE=config.settings.test）
```

> 跑 `pytest` 需要本机 PostgreSQL 可用（会建测试库），并通过 `backend/.env` 注入 `SYNTIME_DB_PASSWORD`。

## 🤝 贡献

欢迎提 Issue 与 PR。请遵循上面的分层约定与四道质量门，新增功能优先补测试（本仓采用 TDD：先写会失败的测试，再写实现）。

## 📝 License

[Apache License 2.0](LICENSE) © 2026 sujx@live.cn

允许免费商用、修改与私有化部署（与本项目「私有化部署、允许以公司名义提供实施服务」的定位一致）；分发时需保留版权与许可声明、修改文件需注明改动。详见 [LICENSE](LICENSE)。
