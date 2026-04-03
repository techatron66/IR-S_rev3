#!/bin/bash

# IR-S Attendance System Startup Script
# This script starts all three services for local development

echo "🚀 Starting IR-S Attendance System..."
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found!"
    echo "Please run: cp .env.example .env"
    echo "Then edit .env with your local IP address"
    exit 1
fi

# Load environment variables
source .env
echo "✅ Loaded configuration from .env"

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
    echo "✅ Activated virtual environment"
else
    echo "⚠️  Warning: venv not found, using system Python"
fi

echo ""
echo "📋 Starting services..."
echo "   1. AI Server (Port 8001)"
echo "   2. Student App (Port 8002)"
echo "   3. Professor Dashboard (Port 8000)"
echo ""

# Function to start a service in background
start_service() {
    local name=$1
    local command=$2
    echo "▶️  Starting $name..."
    $command &
    local pid=$!
    echo "   PID: $pid"
    sleep 2
    if kill -0 $pid 2>/dev/null; then
        echo "   ✅ $name started successfully"
    else
        echo "   ❌ $name failed to start"
    fi
    echo ""
}

# Start services
start_service "AI Server" "python 2_gpu_server.py"
start_service "Student App" "python 3_student_app.py"
start_service "Professor Dashboard" "python 1_prof_dash.py"

echo "🎉 All services started!"
echo ""
echo "📱 Phone Access:"
echo "   Student App: $STUDENT_URL"
echo ""
echo "💻 Professor Dashboard:"
echo "   Local: http://localhost:8000"
echo "   Network: $PROF_SERVER"
echo ""
echo "Press Ctrl+C to stop all services"

# Wait for interrupt
trap 'echo ""; echo "🛑 Stopping all services..."; pkill -f "python.*1_prof_dash\|python.*2_gpu_server\|python.*3_student_app"; echo "✅ All services stopped"; exit 0' INT
wait