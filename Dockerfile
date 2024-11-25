# Imagen base
FROM python:3.9-slim

# Variables de entorno para evitar errores interactivos
ENV DEBIAN_FRONTEND=noninteractive

# Directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    nginx \
    curl \
    git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Eliminar configuración predeterminada de Nginx
RUN rm -f /etc/nginx/sites-enabled/default

# Copiar la configuración personalizada de Nginx
COPY arquitectura /etc/nginx/sites-available/arquitectura

# Crear enlace simbólico para habilitar el sitio
RUN ln -s /etc/nginx/sites-available/arquitectura /etc/nginx/sites-enabled/

# Copiar archivos de la aplicación
COPY . /app/

# Configurar entorno virtual e instalar dependencias
RUN python3 -m venv venv && \
    . venv/bin/activate && \
    pip install --upgrade pip && \
    pip install -r requirements.txt

# Exponer el puerto 80
EXPOSE 80

# Comando para iniciar Nginx y Uvicorn
CMD ["sh", "-c", "nginx && /app/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000"]
