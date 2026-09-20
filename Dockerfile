# 注意：base 镜像**固定 digest**，不要改回浮动 tag（`python:3.11-slim`）。
#
# 浮动 tag 的代价：每次构建 Docker 都要去 registry 校验 "3.11-slim 现在是哪个"，
# 上游一发新版（哪怕只是重新打包），digest 就变，于是从 base 往下的**所有层**
# （apt 装中文字体、装 uv、装全部 Python 依赖）全部缓存失效、重跑一遍。
# 2026-09-20 实际踩过：一次只改了 3 行 Python 的部署，因为 base 变了，
# `pip install uv` 一层就跑了 7 分钟，整次部署约 10 分钟。
#
# 固定 digest 后，base 永远命中同一块，部署只重做 `COPY . .` 之后的层 → 1-2 分钟。
# 升级 Python 补丁版本时**手动**换掉下面这串 sha256（先从构建日志或
# `docker manifest inspect python:3.11-slim` 取新 digest）。
FROM python:3.11-slim@sha256:da047cb8f9d1d98e5c070f5300ba9f7274e33b8fc0e5be5ed88740aed1b95ba9 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 系统依赖（含中文字体，供 Pillow 对阵图渲染使用）
# 换国内 apt 源加速
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources \
 && apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates fonts-wqy-microhei \
 && rm -rf /var/lib/apt/lists/*

# 安装 uv（使用国内源加速）
RUN pip install uv -i https://mirrors.aliyun.com/pypi/simple/

# 拷贝依赖清单并安装（使用国内源加速）
COPY pyproject.toml README.md ./
RUN uv pip install --system --index-url https://mirrors.aliyun.com/pypi/simple/ .

# 拷贝源码
COPY . .

RUN mkdir -p /app/data /app/logs

EXPOSE 8080

# 默认启动：先跑迁移 + seed，再启动 bot
CMD ["sh", "-c", "alembic upgrade head && python scripts/seed_turtle_soup.py && python scripts/seed_foods.py && python -m src.bot"]
