from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import redis
import boto3
import json
import logging
from pythonjsonlogger import jsonlogger
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.ext.fastapi.middleware import XRayMiddleware
from aws_xray_sdk.core import patch

# Habilitar rastreo automático para servicios específicos
patch(["boto3", "redis"])

# Configuración de AWS y Redis
REDIS_HOST = "your-elasticache-endpoint"
REDIS_PORT = 6379
DYNAMODB_TABLE_NAME = "your-dynamodb-table-name"
AWS_REGION = "your-aws-region"
LAMBDA_FUNCTION_NAME = "your-lambda-function-name"

# Inicializar Redis y AWS Resources
redis_client = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
lambda_client = boto3.client("lambda", region_name=AWS_REGION)

# Configurar tabla DynamoDB
table = dynamodb.Table(DYNAMODB_TABLE_NAME)

# Crear la aplicación FastAPI
app = FastAPI()

# Configurar X-Ray
xray_recorder.configure(
    service="FastAPI-ElastiCache-DynamoDB",
    sampling=True,
    context_missing="LOG_ERROR"
)
app.add_middleware(XRayMiddleware)

# Configurar logger para CloudWatch Logs
logger = logging.getLogger("fastapi")
log_handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
log_handler.setFormatter(formatter)
logger.addHandler(log_handler)
logger.setLevel(logging.INFO)

@app.middleware("http")
async def log_requests(request, call_next):
    logger.info(f"Request: {request.method} {request.url}")
    response = await call_next(request)
    logger.info(f"Response: {response.status_code}")
    return response

# Modelo de solicitud
class MinutiaeRequest(BaseModel):
    cedula: str
    minucias: str
    dedo: str
    
@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "API is running"}

# Ruta para verificar las minucias
@app.post("/verificar/")
async def verificar_minutias(request: MinutiaeRequest):
    try:
        # Clave del cache
        cache_key = f"{request.cedula}-{request.dedo}"

        # Verificar en Redis
        cached_data = redis_client.get(cache_key)

        if cached_data:
            # Si está en caché, enviar a Lambda
            logger.info("Dato encontrado en Redis. Enviando a Lambda.")
            payload = {
                "cedula": request.cedula,
                "minucias": request.minucias,
                "dedo": request.dedo
            }

            # Llamada a Lambda
            with xray_recorder.in_subsegment("Lambda-Invocation"):
                lambda_response = lambda_client.invoke(
                    FunctionName=LAMBDA_FUNCTION_NAME,
                    InvocationType="RequestResponse",
                    Payload=json.dumps(payload)
                )
                lambda_result = json.loads(lambda_response["Payload"].read().decode("utf-8"))
            return {"message": "Datos enviados a Lambda", "lambda_result": lambda_result}

        else:
            # Si no está en caché, buscar en DynamoDB
            logger.info("Dato no encontrado en Redis. Consultando DynamoDB.")
            response = table.get_item(Key={"cedula": request.cedula, "dedo": request.dedo})
            if "Item" not in response:
                raise HTTPException(status_code=404, detail="Registro no encontrado en DynamoDB")

            # Guardar en Redis
            logger.info("Guardando resultado en Redis.")
            redis_client.set(cache_key, json.dumps(response["Item"]))
            redis_client.expire(cache_key, 3600)  # Expira en 1 hora

            return {"message": "Datos cargados en caché", "data": response["Item"]}

    except Exception as e:
        logger.error(f"Error procesando la solicitud: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
