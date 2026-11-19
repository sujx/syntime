#!/usr/bin/env bash
# 本机生产形态启动器（2026-11-18 拍板：gunicorn + WhiteNoise，不装 nginx、不用 root）。
#
# 前置（都要已就绪，本脚本不做初始化）：
#   1) postgres 与 redis 已在跑；生产库已建好并完成 migrate / init_roles / seed_demo
#   2) 前端已构建：cd ../frontend && npm run build   （产物 dist/ 由 WhiteNoise 挂到站点根）
#   3) 依赖已装：uv pip install --python .venv/bin/python -r requirements/prod.txt
#   4) 密钥来自 backend/.env（SYNTIME_SECRET_KEY / SYNTIME_DB_PASSWORD，不入库）
#
# 只绑 127.0.0.1 是有意的：本机没有 TLS 终结与防火墙决策，公网暴露需要先定这两件。
# worker 默认 5 不是随手取的：PRD 4.1「闲置资源查询」的门槛口径就是「5 并发 × 多进程」
# （单进程 5 线程实测 5851ms，加线程不绕开 GIL）。2026-11-19 在本形状复测 5 并发 P95
# = 2808ms ⇒ 未达标（见规格 §8.3），因此 5 只是门槛口径与实测形状，不是「已验证达标」。
# 换小 worker 数只会让 5 并发出现排队，连这个可比的读数都不剩了。
set -euo pipefail
cd "$(dirname "$0")"

export DJANGO_SETTINGS_MODULE=config.settings.prod
export SYNTIME_DB_NAME="${SYNTIME_DB_NAME:-syntime_prod}"
export SYNTIME_ALLOWED_HOSTS="${SYNTIME_ALLOWED_HOSTS:-localhost,127.0.0.1}"

mkdir -p logs
exec .venv/bin/gunicorn config.wsgi:application \
  --bind "${SYNTIME_BIND:-127.0.0.1:8000}" \
  --workers "${SYNTIME_WORKERS:-5}" \
  --timeout 60 \
  --pid logs/gunicorn.pid \
  --access-logfile logs/gunicorn.access.log \
  --error-logfile logs/gunicorn.error.log \
  "$@"
