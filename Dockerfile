# Imagen base para Python
FROM python:3.9-slim

# Variables de entorno para evitar errores interactivos en apt
ENV DEBIAN_FRONTEND=noninteractive

# Directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    nginx \
    curl \
    git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copiar el contenido de App al directorio de trabajo
COPY App/ /app/

# Configurar entorno virtual e instalar dependencias
RUN python3 -m venv venv && \
    . venv/bin/activate && \
    pip install --upgrade pip && \
    pip install -r requirements.txt

# Copiar configuración de Nginx
COPY App/arquitectura.conf /etc/nginx/conf.d/arquitectura.conf

# Exponer el puerto 80
EXPOSE 80

# Comando de inicio para supervisar Nginx y Uvicorn
CMD ["sh", "-c", "nginx && /app/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000"]
