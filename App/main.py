from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import redis
import boto3
import json
import logging
from pythonjsonlogger import jsonlogger
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.core import patch
from redis.exceptions import RedisError, ConnectionError
from decimal import Decimal

# Habilitar rastreo automático para boto3
patch(["boto3"])

# Configuración de AWS y Redis
REDIS_HOST = "fingerprintcache-h7s5ms.serverless.use2.cache.amazonaws.com"
REDIS_PORT = 6379
DYNAMODB_TABLE_NAME = "FingerprintRecords"
AWS_REGION = "us-east-2"
LAMBDA_FUNCTION_NAME = "matchingEngine"

# Inicializar Redis y AWS Resources
redis_client = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True, ssl=True)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMODB_TABLE_NAME)
lambda_client = boto3.client("lambda", region_name=AWS_REGION)

# Crear la aplicación FastAPI
app = FastAPI()

# Configurar logger para CloudWatch Logs
logger = logging.getLogger("fastapi")
log_handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
log_handler.setFormatter(formatter)
logger.addHandler(log_handler)
logger.setLevel(logging.INFO)

def decimal_to_standard(obj):
    """
    Convierte valores de tipo Decimal a int o float recursivamente.
    """
    if isinstance(obj, list):
        return [decimal_to_standard(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: decimal_to_standard(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    else:
        return obj

@app.get("/health")
async def health_check():
    """
    Endpoint de verificación del estado de la API.
    """
    try:
        redis_client.ping()
        logger.info("Redis está accesible.")
    except RedisError as e:
        logger.warning(f"Redis no está accesible: {str(e)}")
    return {"status": "ok", "message": "API is running"}

# Modelos de datos
class Minucia(BaseModel):
    x: int
    y: int
    angle: int
    type: str

class CompareRequest(BaseModel):
    cedula: str
    dedo: str
    minucia: Minucia

@app.post("/compare")
async def compare_minutiae(request: CompareRequest):
    """
    Compara la minucia recibida con la almacenada en el cache Redis o DynamoDB llamando a una función Lambda.
    """
    try:
        # Convertir cédula y dedo a clave única para Redis
        cache_key = f"fingerprint:{request.cedula}-{request.dedo}"
        logger.info(f"Verificando clave en Redis: {cache_key}")

        # Intentar obtener datos del cache Redis
        try:
            cached_data = redis_client.get(cache_key)
            if cached_data:
                logger.info(f"Datos encontrados en Redis para clave: {cache_key}")
                record = json.loads(cached_data)
            else:
                raise ValueError("Datos no encontrados en Redis.")
        except (RedisError, ValueError) as e:
            logger.warning(f"No se pudo obtener datos de Redis: {str(e)}. Consultando DynamoDB...")

            # Consultar DynamoDB
            cedula = int(request.cedula)
            response = table.get_item(Key={"cedula": cedula})
            if "Item" not in response:
                logger.warning(f"Registro no encontrado en DynamoDB para cédula: {cedula}")
                raise HTTPException(status_code=404, detail="Registro no encontrado en DynamoDB")
            
            # Obtener el registro del dedo especificado
            record = decimal_to_standard(response["Item"])
            finger = record.get("finger")
            minutiae_list = record.get("minutiae")

            if finger != request.dedo:
                logger.warning(f"Dedo solicitado ({request.dedo}) no coincide con el almacenado ({finger})")
                raise HTTPException(status_code=404, detail="Dedo no encontrado en el registro de DynamoDB")
            
            if not minutiae_list:
                logger.warning(f"Minucia no encontrada en el registro de DynamoDB para cédula: {cedula}")
                raise HTTPException(status_code=404, detail="Minucia no encontrada en el registro de DynamoDB")
            
            logger.info(f"Minucias encontradas en DynamoDB: {minutiae_list}")

            # Guardar los datos en Redis
            logger.info(f"Guardando datos en Redis para clave: {cache_key}")
            redis_client.set(cache_key, json.dumps(record))
            redis_client.expire(cache_key, 3600)  # Expira en 1 hora

        # Llamar a la función Lambda
        payload = {
            "received_minucia": request.minucia.dict(),
            "stored_minucia": record["minutiae"]
        }
        logger.info(f"Llamando a Lambda '{LAMBDA_FUNCTION_NAME}' con payload: {payload}")
        
        lambda_response = lambda_client.invoke(
            FunctionName=LAMBDA_FUNCTION_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload)
        )
        
        # Procesar la respuesta de Lambda
        lambda_result = json.loads(lambda_response["Payload"].read().decode("utf-8"))
        logger.info(f"Respuesta de Lambda: {lambda_result}")
        
        return {"result": lambda_result}

    except ValueError:
        logger.error(f"Error: La cédula {request.cedula} no es un número válido")
        raise HTTPException(status_code=400, detail="La cédula debe ser un número")
    
    except Exception as e:
        logger.error(f"Error procesando la solicitud: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
