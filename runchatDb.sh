pm2 start --name chatdb \
  /home/$user/apps/551-ChatDB/.venv/bin/python -- \
  -m streamlit run app.py \
  --server.port=8501 \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --server.enableCORS=false \
  --server.enableXsrfProtection=false
