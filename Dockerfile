FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 系统依赖
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
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
