#!/bin/bash
set -e  # Detener el script si ocurre un error

# Variables
REPO_URL="https://github.com/tatoand97/arquitectura.git"
CLONE_DIR="/tmp/arquitectura"
APP_DIR="/var/www/arquitectura"
NGINX_CONF_DIR="/etc/nginx/conf.d"
NGINX_CONF_FILE="arquitectura.conf"
SERVICE_NAME="arquitectura"
LOG_DIR="/var/log/nginx"

# Actualizar el sistema
echo "Actualizando el sistema..."
sudo yum update -y

# Instalar dependencias
echo "Instalando Nginx, Git y Python3..."
sudo yum install -y nginx git python3 python3-pip python3-virtualenv

# Clonar el repositorio
if [ -d "$CLONE_DIR" ]; then
    echo "Eliminando directorio temporal existente..."
    rm -rf "$CLONE_DIR"
fi

echo "Clonando el repositorio desde $REPO_URL..."
git clone $REPO_URL $CLONE_DIR

# Crear directorio de la aplicación
echo "Creando el directorio de la aplicación en $APP_DIR..."
sudo mkdir -p $APP_DIR
sudo cp -r $CLONE_DIR/App/* $APP_DIR

# Configurar entorno virtual e instalar dependencias
echo "Configurando entorno virtual e instalando dependencias..."
cd $APP_DIR
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# Configurar permisos
echo "Configurando permisos para el directorio de la aplicación..."
sudo chown -R nginx:nginx $APP_DIR
sudo chmod -R 755 $APP_DIR

# Crear archivos de logs si no existen
echo "Creando archivos de logs para Nginx..."
sudo touch $LOG_DIR/arquitectura_access.log
sudo touch $LOG_DIR/arquitectura_error.log
sudo chown nginx:nginx $LOG_DIR/arquitectura_access.log $LOG_DIR/arquitectura_error.log
sudo chmod 644 $LOG_DIR/arquitectura_access.log $LOG_DIR/arquitectura_error.log

# Configurar Nginx
echo "Configurando Nginx..."
sudo bash -c "cat > $NGINX_CONF_DIR/$NGINX_CONF_FILE <<EOF
server {
    listen 80;
    server_name _;

    access_log $LOG_DIR/arquitectura_access.log;
    error_log $LOG_DIR/arquitectura_error.log;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /static/ {
        alias $APP_DIR/static/;
    }
}
EOF"

# Verificar configuración de Nginx
echo "Verificando configuración de Nginx..."
sudo nginx -t

# Reiniciar Nginx
echo "Reiniciando Nginx..."
sudo systemctl restart nginx

# Crear un archivo de servicio para Uvicorn
echo "Creando servicio systemd para Uvicorn..."
sudo bash -c "cat > /etc/systemd/system/$SERVICE_NAME.service <<EOF
[Unit]
Description=Uvicorn for FastAPI application
After=network.target

[Service]
User=nginx
Group=nginx
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF"

# Recargar systemd y arrancar el servicio
echo "Habilitando y arrancando el servicio Uvicorn..."
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME.service
sudo systemctl start $SERVICE_NAME.service

# Limpiar directorio temporal
echo "Limpiando directorio temporal..."
rm -rf $CLONE_DIR

echo "Configuración completada. El sitio está listo para recibir solicitudes por IP."
