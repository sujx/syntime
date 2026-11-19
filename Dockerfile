# syntax=docker/dockerfile:1

# SynTime 可移植交付镜像：Django 后端 + 前端构建产物 + Celery 收在同一镜像，
# 由 compose.yaml 用不同 command 拉成 web / worker / beat / init / seed 五种角色。
# 构建上下文是 syntime/（见 compose.yaml 的 build.context: .），故本文件所有路径相对 syntime/。

# ── 阶段 1：前端构建 ──
# node:22-alpine 对齐 frontend/package.json 的 @types/node ^22 世代。
# 构建期不需要任何环境变量：前端以 baseURL "/api"（frontend/src/api/client.ts:69）同源请求，
# 深链与静态由运行期 Django + WhiteNoise 兜住，产物与后端解耦。
FROM node:22-alpine AS frontend
# 国内机器可 --build-arg NPM_REGISTRY=https://registry.npmmirror.com 换源；留空走官方源。
ARG NPM_REGISTRY=
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
  && npm ci
COPY frontend/ ./
# build = tsc -b && vite build：类型检查天然是构建门槛，过不了就出不了镜像。
RUN npm run build

# ── 阶段 2：运行时 ──
# python:3.12-slim 对齐本机 .venv 的 3.12.16 与 README 声明的 Python 3.12。
# psycopg[binary] 与 cryptography 都发 cp312 的 manylinux wheel，slim 自带 glibc，
# 因此不需要 apt 装 libpq-dev / build-essential 编译链。
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    TZ=Asia/Shanghai
WORKDIR /app/backend

# beat 的调度状态目录预建并 chown：命名卷首次挂载会继承镜像里该路径的属主，
# 不在镜像里建的话卷会以 root 落盘、非 root 的 beat 写不进去。
RUN useradd --create-home --uid 10001 syntime \
  && mkdir -p /var/lib/syntime-beat \
  && chown syntime:syntime /var/lib/syntime-beat

# 依赖层单独前置：requirements 未变时改代码不会触发重装。
COPY backend/requirements/ ./requirements/
RUN pip install --no-cache-dir -r requirements/prod.txt

COPY backend/ ./
# 落点必须是 /app/frontend/dist：prod.py:22 的 SPA_ROOT = BASE_DIR.parent / "frontend" / "dist"，
# 而 BASE_DIR = /app/backend（base.py:7 上溯三级）。
COPY --from=frontend /fe/dist /app/frontend/dist

# base.py:13 硬读 os.environ["SYNTIME_SECRET_KEY"]，collectstatic 需加载 settings 才能跑，
# 所以这行必须给值。它是行内前缀、仅本次 RUN 生效，不 ENV 进镜像、不参与运行期；
# collectstatic 也不连库。真实密钥由 compose.yaml 在运行时注入。
# 必须放构建期：init 容器的文件系统与 web 容器不共享，运行时收集会丢。
RUN SYNTIME_SECRET_KEY=build-time-dummy-not-a-secret \
    python manage.py collectstatic --noinput

USER syntime
EXPOSE 8000

# 兜底命令，便于脱离 compose 单跑；compose.yaml 会为每个角色各覆盖一次。
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", "--workers", "5", "--timeout", "60", \
     "--access-logfile", "-", "--error-logfile", "-"]
