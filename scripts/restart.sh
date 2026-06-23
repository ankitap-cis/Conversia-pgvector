sudo systemctl stop celery-worker.service || true

cd /home/ubuntu/Conversia-backend

# Create venv only if it doesn't exist
if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3.10 -m venv venv
  sudo chown -R ubuntu:ubuntu venv
else
  echo "Using existing virtual environment"
fi

echo "Activating virtual environment"
source venv/bin/activate

echo "Upgrading pip & installing dependencies"
pip install --upgrade pip
pip install -r requirements.txt

echo "Running Alembic migrations"
alembic upgrade head

# Ensure Redis is running
echo "Ensuring Redis is running"
sudo systemctl enable redis-server
sudo systemctl start redis-server

# Start Chroma and Celery using systemd
echo "Restarting chroma-server and celery-worker services..."
sudo systemctl daemon-reload
sudo systemctl restart chroma-server.service
sudo systemctl restart celery-worker.service

echo "Restarting backend service"
sudo systemctl restart conversia-backend.service

echo "Deployment completed successfully!"
