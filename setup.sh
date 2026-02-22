#!/bin/bash
echo "========================================"
echo "PetitionLetter Setup (Mac/Linux)"
echo "========================================"
echo

# Get script directory (works for both direct run and source)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Step 1: Extract test data (if zip exists)
echo "[1/4] Checking test data..."
if [ -f "data/Test.zip" ]; then
    echo "Found data/Test.zip"
    mkdir -p "backend/data/projects"
    echo "Extracting to backend/data/projects/..."
    unzip -o "data/Test.zip" -d "backend/data/projects/"
    echo "Test data extracted successfully!"
else
    echo "No test data zip found at data/Test.zip"
    echo "You can add test data later by placing the zip file there and running this script again."
fi
echo

# Step 2: Backend setup
echo "[2/4] Setting up backend..."
cd backend
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp ".env.example" ".env"
    echo "Created .env from .env.example"
    echo "Please edit backend/.env and add your API keys!"
fi
pip install -r requirements.txt
cd ..
echo

# Step 3: Frontend setup
echo "[3/4] Setting up frontend..."
cd frontend/frontend
npm install
cd ../..
echo

# Step 4: Done
echo "[4/4] Setup complete!"
echo
echo "========================================"
echo "Next steps:"
echo "1. Edit backend/.env and add your DEEPSEEK_API_KEY or OPENAI_API_KEY"
echo "2. Start backend: cd backend && python -m uvicorn app.main:app --reload --port 8000"
echo "3. Start frontend: cd frontend/frontend && npm run dev"
echo "4. Open http://localhost:5173"
echo "========================================"
