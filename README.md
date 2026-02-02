# PetitionLetter

L-1 签证申请文书智能生成系统 | L-1 Visa Petition Letter AI Generator

[English](#english) | [中文](#中文)

---

## English

### Overview

A 4-stage document processing pipeline for generating L-1 visa petition letters. The system processes supporting documents through OCR, analyzes content with LLM, extracts relationships, and generates professional petition paragraphs with proper exhibit citations.

### Architecture

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Stage 1   │    │   Stage 2   │    │   Stage 3   │    │   Stage 4   │
│     OCR     │ →  │  L1 Analyze │ →  │ L2 Relation │ →  │  L3 Write   │
│   Extract   │    │   Content   │    │   Extract   │    │  Petition   │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
     ↓                   ↓                   ↓                   ↓
  PDF/Image →      Entities &      →   Evidence      →   [Exhibit X]
  to Text          Key Points          Chains            Citations
```

### Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | FastAPI, SQLAlchemy, PyMuPDF, Pydantic |
| **Frontend** | Next.js 16, React 19, Tailwind CSS 4, TypeScript |
| **OCR** | DeepSeek-OCR (local model) |
| **LLM** | Ollama + Qwen3:30b-a3b (local inference) |
| **Database** | SQLite |

### Quick Start (RunPod A100)

```bash
# Clone repository
git clone https://github.com/yourusername/PetitionLetter.git
cd PetitionLetter

# One-click deployment
chmod +x deploy.sh
./deploy.sh
```

### External Access (Cloudflare Tunnel)

For remote access to your RunPod instance:

1. Install cloudflared:
   ```bash
   curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
   chmod +x cloudflared
   ```

2. Run tunnel with your token:
   ```bash
   ./cloudflared tunnel run --token <YOUR_TOKEN>
   ```

3. Configure frontend to use tunnel URL:
   ```bash
   # frontend/.env.local
   NEXT_PUBLIC_API_BASE_URL=https://your-tunnel.domain.com
   ```

### Configuration

This project runs **100% locally** with no cloud API dependencies.

| Component | Default | Description |
|-----------|---------|-------------|
| OCR | DeepSeek-OCR | Local vision model |
| LLM | Ollama + Qwen3 | Local language model |
| Storage | SQLite + Files | Local database and file storage |

### API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/upload` | POST | Upload documents and run OCR |
| `/api/documents/{project_id}` | GET | List project documents |
| `/api/analyze/{document_id}` | POST | L1: Analyze document content |
| `/api/analysis/{document_id}` | GET | Get analysis results |
| `/api/relationship/{project_id}` | POST | L2: Extract relationships |
| `/api/write/{project_id}` | POST | L3: Generate petition paragraphs |
| `/api/health` | GET | Health check |

### Project Structure

```
PetitionLetter/
├── backend/                 # FastAPI backend
│   ├── app/
│   │   ├── core/           # Configuration
│   │   ├── db/             # Database
│   │   ├── models/         # Data models
│   │   ├── routers/        # API routes
│   │   ├── services/       # Business logic
│   │   └── main.py         # Entry point
│   ├── .env.example        # Config template
│   └── requirements.txt
├── frontend/               # Next.js frontend
│   ├── src/
│   ├── .env.example
│   └── package.json
├── deploy.sh               # One-click deployment (RunPod)
└── README.md
```

---

## 中文

### 项目概述

L-1 签证申请文书智能生成 4 阶段流水线。系统通过 OCR 处理证明材料，使用 LLM 分析内容、提取关系，最终生成带有规范证据引用的申请文书段落。

### 系统架构

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   第1阶段   │    │   第2阶段   │    │   第3阶段   │    │   第4阶段   │
│     OCR     │ →  │  L1 分析    │ →  │  L2 关系    │ →  │  L3 撰写    │
│   文字提取  │    │  内容分析   │    │  关系提取   │    │  文书生成   │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

### 技术栈

| 层级 | 技术 |
|------|------|
| **后端** | FastAPI, SQLAlchemy, PyMuPDF, Pydantic |
| **前端** | Next.js 16, React 19, Tailwind CSS 4, TypeScript |
| **OCR** | DeepSeek-OCR（本地模型） |
| **LLM** | Ollama + Qwen3:30b-a3b（本地推理） |
| **数据库** | SQLite |

### 快速开始（RunPod A100 部署）

```bash
# 克隆仓库
git clone https://github.com/yourusername/PetitionLetter.git
cd PetitionLetter

# 一键部署
chmod +x deploy.sh
./deploy.sh
```

### 部署脚本选项

```bash
./deploy.sh              # 完整部署（首次安装）
./deploy.sh --start      # 仅启动服务
./deploy.sh --check      # 检查环境状态
./deploy.sh --update     # 更新代码和依赖
```

### 外网访问（Cloudflare Tunnel）

通过 Cloudflare Tunnel 实现远程访问 RunPod 实例：

1. 安装 cloudflared：
   ```bash
   curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
   chmod +x cloudflared
   ```

2. 使用你的 token 运行隧道：
   ```bash
   ./cloudflared tunnel run --token <YOUR_TOKEN>
   ```

3. 配置前端使用隧道地址：
   ```bash
   # frontend/.env.local
   NEXT_PUBLIC_API_BASE_URL=https://your-tunnel.domain.com
   ```

Token 获取方式：
1. 登录 https://one.dash.cloudflare.com/
2. 进入 Networks > Tunnels
3. 选择对应的 Tunnel，复制 token

### 配置说明（纯本地，无云端 API）

本项目 **100% 本地运行**，无需任何云端 API。

| 组件 | 默认配置 | 说明 |
|------|----------|------|
| OCR | DeepSeek-OCR | 本地视觉模型 |
| LLM | Ollama + Qwen3 | 本地语言模型 |
| 存储 | SQLite + 文件 | 本地数据库和文件存储 |

### API 文档

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/upload` | POST | 上传文档并执行 OCR |
| `/api/documents/{project_id}` | GET | 获取项目文档列表 |
| `/api/analyze/{document_id}` | POST | L1：分析文档内容 |
| `/api/analysis/{document_id}` | GET | 获取分析结果 |
| `/api/relationship/{project_id}` | POST | L2：提取关系 |
| `/api/write/{project_id}` | POST | L3：生成申请文书段落 |
| `/api/health` | GET | 健康检查 |

### 访问地址

- **前端界面**: http://localhost:3000
- **后端 API**: http://localhost:8000
- **API 文档**: http://localhost:8000/docs

---

## License

MIT
