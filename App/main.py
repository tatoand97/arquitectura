from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import redis
import boto3
import json
import logging
from pythonjsonlogger import jsonlogger
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.core import patch

# Habilitar rastreo automático para boto3
patch(["boto3"])

# Configuración de AWS y Redis
REDIS_HOST = "your-elasticache-endpoint"
REDIS_PORT = 6379
DYNAMODB_TABLE_NAME = "FingerprintRecords"
AWS_REGION = "us-east-2"
LAMBDA_FUNCTION_NAME = "your-lambda-function-name"

# Inicializar Redis y AWS Resources
redis_client = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMODB_TABLE_NAME)

# Crear la aplicación FastAPI
app = FastAPI()

# Configurar logger para CloudWatch Logs
logger = logging.getLogger("fastapi")
log_handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
log_handler.setFormatter(formatter)
logger.addHandler(log_handler)
logger.setLevel(logging.INFO)

@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "API is running"}

# Endpoint para probar la conexión con DynamoDB
@app.get("/dynamo/{cedula}/{dedo}")
async def get_dynamo_record(cedula: str, dedo: str):
    """
    Consulta un registro específico en la tabla DynamoDB.
    :param cedula: La cédula del usuario.
    :param dedo: El dedo asociado al registro.
    :return: Registro encontrado en DynamoDB o error 404.
    """
    try:
        logger.info(f"Consultando DynamoDB para cedula: {cedula}, dedo: {dedo}")
        response = table.get_item(Key={"cedula": cedula, "dedo": dedo})
        
        if "Item" in response:
            logger.info(f"Registro encontrado en DynamoDB: {response['Item']}")
            return {"data": response["Item"]}
        else:
            logger.warning(f"Registro no encontrado en DynamoDB para cedula: {cedula}, dedo: {dedo}")
            raise HTTPException(status_code=404, detail="Registro no encontrado")
    
    except Exception as e:
        logger.error(f"Error al consultar DynamoDB: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

