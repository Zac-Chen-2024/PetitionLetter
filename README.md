# PetitionLetter

EB-1A 签证申请文书智能生成系统 | Immigration Petition Letter AI Generator

[English](#english) | [中文](#中文)

---

## English

### Quick Start

#### Prerequisites

- Python 3.10+
- Node.js 18+
- DeepSeek API Key (or OpenAI API Key)

#### 1. Clone

```bash
git clone https://github.com/Zac-Chen-2024/PetitionLetter2.0.git
cd PetitionLetter2.0
```

#### 2. One-Click Setup (Recommended)

**Windows:**
```bash
# If you have test data, place "Test.zip" in data/ folder first
setup.bat
```

**Mac/Linux:**
```bash
chmod +x setup.sh
# If you have test data, place "Test.zip" in data/ folder first
./setup.sh
```

The script will:
- Extract test data to `backend/data/projects/` (if `data/Test.zip` exists)
- Install backend dependencies
- Install frontend dependencies
- Create `.env` from template

#### 3. Manual Setup (Alternative)

##### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your DEEPSEEK_API_KEY or OPENAI_API_KEY
python -m uvicorn app.main:app --reload --port 8000
```

##### Frontend (New Terminal)

```bash
cd frontend/frontend

# Install dependencies
npm install

# Start frontend dev server
npm run dev
```

#### 4. Access

| Service | URL |
|---------|-----|
| **Frontend** | http://localhost:5173 |
| **Backend API** | http://localhost:8000 |
| **API Docs** | http://localhost:8000/docs |

### Project Structure

```
PetitionLetter2.0/
├── backend/
│   ├── app/
│   │   ├── routers/           # API routes
│   │   │   ├── arguments.py   # Argument/SubArgument CRUD
│   │   │   └── writing.py     # Letter generation
│   │   ├── services/          # Business logic
│   │   │   ├── legal_argument_organizer.py
│   │   │   ├── subargument_generator.py
│   │   │   ├── petition_writer_v3.py
│   │   │   ├── snippet_recommender.py
│   │   │   └── llm_client.py
│   │   └── main.py
│   ├── data/projects/         # Project data (auto-created)
│   ├── requirements.txt
│   └── .env.example
│
└── frontend/frontend/
    ├── src/
    │   ├── components/
    │   │   ├── ArgumentGraph.tsx      # Writing Tree
    │   │   ├── EvidenceCardPool.tsx   # Evidence Cards
    │   │   ├── LetterPanel.tsx        # Generated letter
    │   │   └── DocumentViewer.tsx     # PDF viewer
    │   ├── context/AppContext.tsx     # Global state
    │   └── types/index.ts
    └── package.json
```

### Features

#### Core Workflow

```
PDF Documents → OCR → Evidence Extraction → Argument Organization → Letter Generation
```

#### Three-Panel Layout

| Panel | Description |
|-------|-------------|
| **Evidence Cards** (Left) | Snippet cards + PDF preview |
| **Writing Tree** (Center) | Interactive argument graph |
| **Letter Panel** (Right) | Generated petition text |

#### EB-1A Standards Supported

| Standard | Code | Description |
|----------|------|-------------|
| Membership | §204.5(h)(3)(ii) | Outstanding achievement associations |
| Published Material | §204.5(h)(3)(iii) | Major media coverage |
| Original Contribution | §204.5(h)(3)(v) | Contributions of major significance |
| Leading Role | §204.5(h)(3)(viii) | Critical role in distinguished orgs |
| Awards | §204.5(h)(3)(i) | Nationally recognized prizes |

### Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | FastAPI, Pydantic, PyMuPDF |
| **Frontend** | React 18, TypeScript, Tailwind CSS, Vite |
| **LLM** | DeepSeek API / OpenAI API |

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/arguments/{project_id}` | GET | Get all arguments |
| `/api/arguments/{project_id}/generate` | POST | Generate arguments |
| `/api/arguments/{project_id}/subarguments` | POST | Create SubArgument |
| `/api/arguments/{project_id}/subarguments/{id}` | PUT | Update SubArgument |
| `/api/arguments/{project_id}/subarguments/{id}` | DELETE | Delete SubArgument |
| `/api/write/v3/{project_id}/{standard}` | POST | Generate letter section |

### Environment Variables

Create `backend/.env`:

```env
# Required: At least one LLM provider
DEEPSEEK_API_KEY=sk-xxx
OPENAI_API_KEY=sk-xxx

# Optional
LLM_PROVIDER=deepseek  # or "openai"
```

---

## 中文

### 一键部署

#### 环境要求

- Python 3.10+
- Node.js 18+
- DeepSeek API Key（或 OpenAI API Key）

#### 1. 克隆仓库

```bash
git clone https://github.com/Zac-Chen-2024/PetitionLetter2.0.git
cd PetitionLetter2.0
```

#### 2. 一键部署脚本（推荐）

**Windows:**
```bash
# 如有测试数据，先将 "Test.zip" 放入 data/ 文件夹
setup.bat
```

**Mac/Linux:**
```bash
chmod +x setup.sh
# 如有测试数据，先将 "Test.zip" 放入 data/ 文件夹
./setup.sh
```

脚本会自动：
- 解压测试数据到 `backend/data/projects/`（如果 `data/Test.zip` 存在）
- 安装后端依赖
- 安装前端依赖
- 从模板创建 `.env` 文件

#### 3. 手动部署（备选）

##### 后端
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY 或 OPENAI_API_KEY
python -m uvicorn app.main:app --reload --port 8000
```

##### 前端（新开终端）
```bash
cd frontend/frontend
npm install
npm run dev
```

#### 4. 访问地址

| 服务 | 地址 |
|------|------|
| **前端界面** | http://localhost:5173 |
| **后端 API** | http://localhost:8000 |
| **API 文档** | http://localhost:8000/docs |

### 项目结构

```
PetitionLetter2.0/
├── backend/                   # 后端
│   ├── app/
│   │   ├── routers/           # API 路由
│   │   │   ├── arguments.py   # 论点/次级子论点 CRUD
│   │   │   └── writing.py     # 文书生成
│   │   ├── services/          # 业务逻辑
│   │   │   ├── legal_argument_organizer.py
│   │   │   ├── subargument_generator.py
│   │   │   ├── petition_writer_v3.py
│   │   │   ├── snippet_recommender.py
│   │   │   └── llm_client.py
│   │   └── main.py
│   ├── data/projects/         # 项目数据（自动创建）
│   ├── requirements.txt
│   └── .env.example
│
└── frontend/frontend/         # 前端
    ├── src/
    │   ├── components/
    │   │   ├── ArgumentGraph.tsx      # Writing Tree（论点图）
    │   │   ├── EvidenceCardPool.tsx   # 证据卡片池
    │   │   ├── LetterPanel.tsx        # 生成文书面板
    │   │   └── DocumentViewer.tsx     # PDF 预览器
    │   ├── context/AppContext.tsx     # 全局状态管理
    │   └── types/index.ts
    └── package.json
```

### 核心功能

#### 处理流程

```
PDF 文档 → OCR 识别 → 证据提取 → 论点组织 → 文书生成
```

#### 三栏布局

| 面板 | 说明 |
|------|------|
| **Evidence Cards**（左） | 证据片段卡片 + PDF 预览 |
| **Writing Tree**（中） | 交互式论点图 |
| **Letter Panel**（右） | 生成的申请文书 |

#### 支持的 EB-1A 标准

| 标准 | 法规引用 | 说明 |
|------|----------|------|
| Membership | §204.5(h)(3)(ii) | 杰出成就协会会员资格 |
| Published Material | §204.5(h)(3)(iii) | 主要媒体报道 |
| Original Contribution | §204.5(h)(3)(v) | 重大原创贡献 |
| Leading Role | §204.5(h)(3)(viii) | 著名组织关键角色 |
| Awards | §204.5(h)(3)(i) | 国家/国际认可奖项 |

### 技术栈

| 层级 | 技术 |
|------|------|
| **后端** | FastAPI, Pydantic, PyMuPDF |
| **前端** | React 18, TypeScript, Tailwind CSS, Vite |
| **LLM** | DeepSeek API / OpenAI API |

### 主要 API 端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/arguments/{project_id}` | GET | 获取所有论点 |
| `/api/arguments/{project_id}/generate` | POST | 生成论点 |
| `/api/arguments/{project_id}/subarguments` | POST | 创建次级子论点 |
| `/api/arguments/{project_id}/subarguments/{id}` | PUT | 更新次级子论点 |
| `/api/arguments/{project_id}/subarguments/{id}` | DELETE | 删除次级子论点 |
| `/api/write/v3/{project_id}/{standard}` | POST | 生成文书段落 |

### 环境变量配置

创建 `backend/.env` 文件：

```env
# 必需：至少配置一个 LLM 服务
DEEPSEEK_API_KEY=sk-xxx
OPENAI_API_KEY=sk-xxx

# 可选
LLM_PROVIDER=deepseek  # 或 "openai"
```

---

## License

MIT
