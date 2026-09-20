# ---------- 阶段 1：构建前端静态资源 ----------
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install
COPY frontend/ ./
# 输出到 /build/src/qoder2api/static（见 vite.config.ts outDir）
RUN npm run build

# ---------- 阶段 2：Python 运行时 ----------
FROM python:3.12-slim
WORKDIR /app

# 安装 Python 依赖（用系统 pip 安装项目本身，pypiwin32 已加 win32 标记不会装）
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# 前端静态资源
COPY --from=frontend /build/src/qoder2api/static ./src/qoder2api/static

# 可写目录（SQLite 数据库、日志）
ENV QODER_HOST=0.0.0.0 \
    QODER_PORT=5050 \
    HOME=/data
RUN mkdir -p /data/.qoder && \
    ln -s /data/.qoder /root/.qoder 2>/dev/null || true
VOLUME ["/data"]
EXPOSE 5050

CMD ["python", "-c", "from qoder2api.app import main; main()"]
