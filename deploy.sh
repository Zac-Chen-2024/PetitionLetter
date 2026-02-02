#!/bin/bash
# =============================================================================
# PetitionLetter 一键部署脚本 (RunPod A100)
# =============================================================================
# 用法:
#   ./deploy.sh              # 完整部署（首次）
#   ./deploy.sh --start      # 仅启动服务
#   ./deploy.sh --check      # 检查环境状态
#   ./deploy.sh --update     # 更新代码和依赖
#   ./deploy.sh --stop       # 停止所有服务
# =============================================================================

set -e

# =============================================================================
# 配置
# =============================================================================
WORKSPACE="/workspace"
PROJECT_DIR="$WORKSPACE/PetitionLetter"
CONDA_DIR="$WORKSPACE/miniconda"
NODE_DIR="$WORKSPACE/nodejs"
OLLAMA_HOME="$WORKSPACE/.ollama"

# 版本
NODE_VERSION="20.18.0"
CONDA_VERSION="latest"

# 模型
OLLAMA_MODEL="qwen3:30b-a3b"
DEEPSEEK_OCR_MODEL="deepseek-ai/DeepSeek-OCR"

# 端口
BACKEND_PORT=8000
FRONTEND_PORT=3000
OLLAMA_PORT=11434

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# =============================================================================
# 工具函数
# =============================================================================

print_banner() {
    echo -e "${BLUE}"
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║                                                               ║"
    echo "║   ██████╗ ███████╗████████╗██╗████████╗██╗ ██████╗ ███╗   ██╗ ║"
    echo "║   ██╔══██╗██╔════╝╚══██╔══╝██║╚══██╔══╝██║██╔═══██╗████╗  ██║ ║"
    echo "║   ██████╔╝█████╗     ██║   ██║   ██║   ██║██║   ██║██╔██╗ ██║ ║"
    echo "║   ██╔═══╝ ██╔══╝     ██║   ██║   ██║   ██║██║   ██║██║╚██╗██║ ║"
    echo "║   ██║     ███████╗   ██║   ██║   ██║   ██║╚██████╔╝██║ ╚████║ ║"
    echo "║   ╚═╝     ╚══════╝   ╚═╝   ╚═╝   ╚═╝   ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ║"
    echo "║                                                               ║"
    echo "║          L-1 Visa Petition Letter AI Generator                ║"
    echo "║                                                               ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}▶ $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

# =============================================================================
# 环境检测函数
# =============================================================================

ensure_workspace() {
    if [ ! -d "$WORKSPACE" ]; then
        log_warn "/workspace 不存在，创建中（非 RunPod 环境）..."
        sudo mkdir -p "$WORKSPACE"
        sudo chown $USER:$USER "$WORKSPACE"
    fi
}

check_gpu() {
    log_step "检查 GPU"
    if command -v nvidia-smi &> /dev/null; then
        nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
        log_info "GPU 检测成功"
        return 0
    else
        log_warn "未检测到 NVIDIA GPU"
        return 1
    fi
}

check_conda() {
    log_step "检查 Miniconda"

    if [ -f "$CONDA_DIR/bin/conda" ]; then
        log_info "Miniconda 已安装: $CONDA_DIR"
        source "$CONDA_DIR/etc/profile.d/conda.sh"
        conda --version
        return 0
    fi

    log_info "安装 Miniconda..."
    wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh
    bash /tmp/miniconda.sh -b -p "$CONDA_DIR"
    rm /tmp/miniconda.sh

    source "$CONDA_DIR/etc/profile.d/conda.sh"
    conda init bash 2>/dev/null || true

    log_info "Miniconda 安装完成"
    conda --version
}

check_node() {
    log_step "检查 Node.js"

    if [ -f "$NODE_DIR/bin/node" ]; then
        log_info "Node.js 已安装: $NODE_DIR"
        export PATH="$NODE_DIR/bin:$PATH"
        node --version
        npm --version
        return 0
    fi

    log_info "安装 Node.js v$NODE_VERSION..."
    mkdir -p "$NODE_DIR"
    wget -q "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-x64.tar.xz" -O /tmp/node.tar.xz
    tar -xf /tmp/node.tar.xz -C "$NODE_DIR" --strip-components=1
    rm /tmp/node.tar.xz

    export PATH="$NODE_DIR/bin:$PATH"

    log_info "Node.js 安装完成"
    node --version
    npm --version
}

check_ollama() {
    log_step "检查 Ollama"

    export OLLAMA_HOME="$OLLAMA_HOME"

    if command -v ollama &> /dev/null; then
        log_info "Ollama 已安装"
        ollama --version
        return 0
    fi

    log_info "安装 Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh

    log_info "Ollama 安装完成"
    ollama --version
}

# =============================================================================
# 服务安装函数
# =============================================================================

setup_backend() {
    log_step "配置后端环境"

    source "$CONDA_DIR/etc/profile.d/conda.sh"

    # 创建/激活 conda 环境
    if ! conda env list | grep -q "petition"; then
        log_info "创建 conda 环境: petition"
        conda create -n petition python=3.11 -y
    fi

    conda activate petition

    # 安装依赖
    log_info "安装 Python 依赖..."
    cd "$PROJECT_DIR/backend"
    pip install -r requirements.txt -q

    log_info "后端依赖安装完成"
}

setup_frontend() {
    log_step "配置前端环境"

    export PATH="$NODE_DIR/bin:$PATH"

    cd "$PROJECT_DIR/frontend"

    if [ ! -d "node_modules" ]; then
        log_info "安装前端依赖..."
        npm install
    else
        log_info "前端依赖已存在，跳过安装"
    fi

    log_info "前端依赖安装完成"
}

setup_env() {
    log_step "配置环境变量"

    # Backend .env
    if [ ! -f "$PROJECT_DIR/backend/.env" ]; then
        log_info "创建 backend/.env"
        cat > "$PROJECT_DIR/backend/.env" << 'EOF'
# ===================
# OCR 配置（本地 DeepSeek-OCR）
# ===================
OCR_PROVIDER=deepseek
DEEPSEEK_OCR_VENV=/workspace/miniconda/envs/deepseek-ocr
DEEPSEEK_OCR_MODEL=deepseek-ai/DeepSeek-OCR

# ===================
# LLM 配置（本地 Ollama）
# ===================
LLM_PROVIDER=ollama
LLM_MODEL=qwen3:30b-a3b
LLM_API_BASE=http://localhost:11434/v1
EOF
    else
        log_info "backend/.env 已存在，跳过"
    fi

    # Frontend .env.local
    if [ ! -f "$PROJECT_DIR/frontend/.env.local" ]; then
        log_info "创建 frontend/.env.local"
        cat > "$PROJECT_DIR/frontend/.env.local" << 'EOF'
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
EOF
    else
        log_info "frontend/.env.local 已存在，跳过"
    fi

    # 持久化 PATH 到 /workspace/.bashrc
    if ! grep -q "PetitionLetter" "$WORKSPACE/.bashrc" 2>/dev/null; then
        log_info "配置持久化环境变量..."
        cat >> "$WORKSPACE/.bashrc" << EOF

# ===================
# PetitionLetter 环境
# ===================
export PATH="$NODE_DIR/bin:\$PATH"
export OLLAMA_HOME="$OLLAMA_HOME"
source "$CONDA_DIR/etc/profile.d/conda.sh"
conda activate petition 2>/dev/null || true
EOF
    fi

    log_info "环境变量配置完成"
}

pull_model() {
    log_step "下载 Ollama 模型"

    export OLLAMA_HOME="$OLLAMA_HOME"

    # 检查 Ollama 是否运行
    if ! pgrep -x "ollama" > /dev/null; then
        log_info "启动 Ollama 服务..."
        nohup ollama serve > /tmp/ollama.log 2>&1 &
        sleep 5
    fi

    # 检查模型是否已下载
    if ollama list 2>/dev/null | grep -q "$OLLAMA_MODEL"; then
        log_info "模型 $OLLAMA_MODEL 已存在"
    else
        log_info "下载模型 $OLLAMA_MODEL（这可能需要一些时间）..."
        ollama pull "$OLLAMA_MODEL"
    fi

    log_info "模型准备完成"
}

# =============================================================================
# 服务管理函数
# =============================================================================

start_services() {
    log_step "启动所有服务"

    # 设置环境
    source "$CONDA_DIR/etc/profile.d/conda.sh"
    export PATH="$NODE_DIR/bin:$PATH"
    export OLLAMA_HOME="$OLLAMA_HOME"

    # 1. 启动 Ollama
    if ! pgrep -x "ollama" > /dev/null; then
        log_info "启动 Ollama..."
        nohup ollama serve > /tmp/ollama.log 2>&1 &
        sleep 3
    else
        log_info "Ollama 已在运行"
    fi

    # 2. 启动后端
    if ! lsof -i:$BACKEND_PORT > /dev/null 2>&1; then
        log_info "启动后端服务 (端口 $BACKEND_PORT)..."
        conda activate petition
        cd "$PROJECT_DIR/backend"
        nohup python run.py > /tmp/backend.log 2>&1 &
        sleep 3
    else
        log_info "后端已在运行 (端口 $BACKEND_PORT)"
    fi

    # 3. 启动前端
    if ! lsof -i:$FRONTEND_PORT > /dev/null 2>&1; then
        log_info "启动前端服务 (端口 $FRONTEND_PORT)..."
        cd "$PROJECT_DIR/frontend"
        nohup npm run dev > /tmp/frontend.log 2>&1 &
        sleep 5
    else
        log_info "前端已在运行 (端口 $FRONTEND_PORT)"
    fi

    log_info "所有服务已启动"
}

stop_services() {
    log_step "停止所有服务"

    # 停止前端
    if lsof -i:$FRONTEND_PORT > /dev/null 2>&1; then
        log_info "停止前端..."
        fuser -k $FRONTEND_PORT/tcp 2>/dev/null || true
    fi

    # 停止后端
    if lsof -i:$BACKEND_PORT > /dev/null 2>&1; then
        log_info "停止后端..."
        fuser -k $BACKEND_PORT/tcp 2>/dev/null || true
    fi

    # 停止 Ollama
    if pgrep -x "ollama" > /dev/null; then
        log_info "停止 Ollama..."
        pkill -x ollama || true
    fi

    log_info "所有服务已停止"
}

show_status() {
    log_step "服务状态"

    echo -e "\n┌──────────────────┬──────────┬─────────────────────────┐"
    echo -e "│ 服务             │ 状态     │ 地址                    │"
    echo -e "├──────────────────┼──────────┼─────────────────────────┤"

    # Ollama
    if pgrep -x "ollama" > /dev/null; then
        echo -e "│ Ollama           │ ${GREEN}运行中${NC}   │ http://localhost:$OLLAMA_PORT   │"
    else
        echo -e "│ Ollama           │ ${RED}已停止${NC}   │ -                       │"
    fi

    # Backend
    if lsof -i:$BACKEND_PORT > /dev/null 2>&1; then
        echo -e "│ Backend (FastAPI)│ ${GREEN}运行中${NC}   │ http://localhost:$BACKEND_PORT    │"
    else
        echo -e "│ Backend (FastAPI)│ ${RED}已停止${NC}   │ -                       │"
    fi

    # Frontend
    if lsof -i:$FRONTEND_PORT > /dev/null 2>&1; then
        echo -e "│ Frontend (Next)  │ ${GREEN}运行中${NC}   │ http://localhost:$FRONTEND_PORT    │"
    else
        echo -e "│ Frontend (Next)  │ ${RED}已停止${NC}   │ -                       │"
    fi

    echo -e "└──────────────────┴──────────┴─────────────────────────┘"

    # 环境状态
    echo -e "\n┌──────────────────┬──────────────────────────────────┐"
    echo -e "│ 组件             │ 路径                             │"
    echo -e "├──────────────────┼──────────────────────────────────┤"

    if [ -f "$CONDA_DIR/bin/conda" ]; then
        echo -e "│ Miniconda        │ ${GREEN}✓${NC} $CONDA_DIR"
    else
        echo -e "│ Miniconda        │ ${RED}✗${NC} 未安装"
    fi

    if [ -f "$NODE_DIR/bin/node" ]; then
        echo -e "│ Node.js          │ ${GREEN}✓${NC} $NODE_DIR"
    else
        echo -e "│ Node.js          │ ${RED}✗${NC} 未安装"
    fi

    if command -v ollama &> /dev/null; then
        echo -e "│ Ollama           │ ${GREEN}✓${NC} $(which ollama)"
    else
        echo -e "│ Ollama           │ ${RED}✗${NC} 未安装"
    fi

    echo -e "└──────────────────┴──────────────────────────────────┘"

    # GPU 状态
    if command -v nvidia-smi &> /dev/null; then
        echo -e "\n${BLUE}GPU 状态:${NC}"
        nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader
    fi
}

update_project() {
    log_step "更新项目"

    cd "$PROJECT_DIR"

    # 更新代码
    if [ -d ".git" ]; then
        log_info "拉取最新代码..."
        git pull
    fi

    # 更新依赖
    setup_backend
    setup_frontend

    log_info "更新完成"
}

# =============================================================================
# 完整部署
# =============================================================================

full_deploy() {
    print_banner

    log_info "开始完整部署..."

    ensure_workspace
    check_gpu || true
    check_conda
    check_node
    check_ollama
    setup_backend
    setup_frontend
    setup_env
    pull_model
    start_services
    show_status

    echo -e "\n${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}部署完成！${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "\n访问地址:"
    echo -e "  前端: ${BLUE}http://localhost:$FRONTEND_PORT${NC}"
    echo -e "  后端: ${BLUE}http://localhost:$BACKEND_PORT${NC}"
    echo -e "  API 文档: ${BLUE}http://localhost:$BACKEND_PORT/docs${NC}"
    echo -e "\n日志文件:"
    echo -e "  后端: /tmp/backend.log"
    echo -e "  前端: /tmp/frontend.log"
    echo -e "  Ollama: /tmp/ollama.log"
}

# =============================================================================
# 主入口
# =============================================================================

main() {
    case "${1:-}" in
        --start)
            print_banner
            start_services
            show_status
            ;;
        --stop)
            print_banner
            stop_services
            ;;
        --check)
            print_banner
            show_status
            ;;
        --update)
            print_banner
            update_project
            ;;
        --help|-h)
            print_banner
            echo "用法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  (无参数)    完整部署（首次安装）"
            echo "  --start     仅启动服务"
            echo "  --stop      停止所有服务"
            echo "  --check     检查环境状态"
            echo "  --update    更新代码和依赖"
            echo "  --help      显示此帮助"
            ;;
        *)
            full_deploy
            ;;
    esac
}

main "$@"
