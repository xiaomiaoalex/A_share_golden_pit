# A股黄金坑股票数据库 Docker镜像
FROM python:3.11-slim

LABEL maintainer="Golden Pit Database"
LABEL description="A股黄金坑股票数据库 - 价值投资筛选系统"

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV TZ=Asia/Shanghai

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libxml2-dev \
    libxslt1-dev \
    libffi-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 创建必要的目录
RUN mkdir -p data/db output logs

# 初始化数据库
RUN python main.py tier3-migrate

# 默认命令
CMD ["python", "main.py", "--help"]
