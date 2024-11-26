from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import redis
import boto3
import json
import logging
from pythonjsonlogger import jsonlogger
from redis.exceptions import RedisError
from decimal import Decimal
import time
import uuid

# Configuración de AWS y Redis
REDIS_HOST = "fingerprintcache-h7s5ms.serverless.use2.cache.amazonaws.com"
REDIS_PORT = 6379
DYNAMODB_TABLE_NAME = "FingerprintRecords"
DYNAMODB_LOG_TABLE_NAME = "FingerprintLogs"
AWS_REGION = "us-east-2"
LAMBDA_FUNCTION_NAME = "matchingEngine"

# Inicializar Redis y AWS Resources
redis_client = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True, ssl=True)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMODB_TABLE_NAME)
log_table = dynamodb.Table(DYNAMODB_LOG_TABLE_NAME)
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

def save_log_to_dynamodb(level: str, message: str, trace_id: str, additional_data: dict = None):
    """
    Guarda un log en la tabla DynamoDB FingerprintLogs.
    """
    try:
        # Convertir valores adicionales a Decimal si es necesario
        def convert_to_decimal(data):
            if isinstance(data, dict):
                return {k: convert_to_decimal(v) for k, v in data.items()}
            elif isinstance(data, list):
                return [convert_to_decimal(v) for v in data]
            elif isinstance(data, float):
                return Decimal(str(data))  # Convertir float a Decimal
            else:
                return data

        additional_data = convert_to_decimal(additional_data) if additional_data else {}
        
        log_item = {
            "log_id": f"log-{int(time.time() * 1000)}", # Generar ID único basado en timestamp
            "trace_id": trace_id, # Añadir trace_id
            "timestamp": Decimal(str(time.time())), # Convertir timestamp a Decimal
            "level": level,
            "message": message,
            "additional_data": additional_data
        }
        log_table.put_item(Item=log_item)
        logger.info(f"Log guardado en DynamoDB: {log_item}")
    except Exception as e:
        logger.error(f"No se pudo guardar el log en DynamoDB: {str(e)}")

# Rutas de ejemplo para el servicio
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
    minucia: list[Minucia]

@app.post("/compare")
async def compare_minutiae(request: CompareRequest):
    """
    Compara las minucias recibidas con las almacenadas en el cache Redis o DynamoDB llamando a una función Lambda.
    """
    trace_id = str(uuid.uuid4()) # Generar un trace_id único para esta petición
    try:
        cache_key = f"fingerprint:{request.cedula}-{request.dedo}"
        logger.info(f"Verificando clave en Redis: {cache_key}")
        save_log_to_dynamodb("INFO", "Iniciando comparación de minucias.", trace_id, {"cache_key": cache_key})

        # Medir tiempo de consulta en Redis
        redis_start_time = time.time()
        try:
            cached_data = redis_client.get(cache_key)
            redis_duration = time.time() - redis_start_time
            logger.info(f"Tiempo para consultar Redis: {redis_duration:.4f} segundos.")
            save_log_to_dynamodb("INFO", "Consulta Redis completada.", trace_id, {"cache_key": cache_key, "duration": f"{redis_duration:.4f}"})

            if cached_data:
                logger.info(f"Datos encontrados en Redis para clave: {cache_key}")
                record = json.loads(cached_data)
            else:
                raise ValueError("Datos no encontrados en Redis.")
        except (RedisError, ValueError) as e:
            redis_duration = time.time() - redis_start_time
            logger.warning(f"No se pudo obtener datos de Redis: {str(e)}. Tiempo transcurrido: {redis_duration:.4f} segundos.")
            save_log_to_dynamodb("WARN", "Fallo al obtener datos de Redis.", trace_id, {"error": str(e), "duration": f"{redis_duration:.4f}"})

            # Consultar DynamoDB
            db_start_time = time.time()
            cedula = int(request.cedula)
            response = table.get_item(Key={"cedula": cedula})
            db_duration = time.time() - db_start_time
            logger.info(f"Tiempo para consultar DynamoDB: {db_duration:.4f} segundos.")
            save_log_to_dynamodb("INFO", "Consulta DynamoDB completada.", trace_id, {"cedula": cedula, "duration": f"{db_duration:.4f}"})
            if "Item" not in response:
                logger.warning(f"Registro no encontrado en DynamoDB para cédula: {cedula}")
                save_log_to_dynamodb("WARN", "Registro no encontrado en DynamoDB.", trace_id, {"cedula": cedula})
                raise HTTPException(status_code=404, detail="Registro no encontrado en DynamoDB")
            
            record = decimal_to_standard(response["Item"])
            logger.info(f"Minucias encontradas en DynamoDB: {record.get('minutiae')}")
            save_log_to_dynamodb("INFO", "Datos obtenidos de DynamoDB.", trace_id, {"record": record})

            # Guardar en Redis
            redis_save_start_time = time.time()
            redis_client.set(cache_key, json.dumps(record))
            redis_client.expire(cache_key, 3600)
            redis_save_duration = time.time() - redis_save_start_time
            logger.info(f"Tiempo para guardar en Redis: {redis_save_duration:.4f} segundos.")
            save_log_to_dynamodb("INFO", "Datos guardados en Redis.", {"cache_key": cache_key, "duration": f"{redis_save_duration:.4f}"})

        # Llamar a la función Lambda
        payload = {
            "received_minucia": [m.dict() for m in request.minucia],
            "stored_minucia": record["minutiae"]
        }
        lambda_start_time = time.time()
        lambda_response = lambda_client.invoke(
            FunctionName=LAMBDA_FUNCTION_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload)
        )
        lambda_duration = time.time() - lambda_start_time
        logger.info(f"Tiempo para llamar a Lambda: {lambda_duration:.4f} segundos.")
        save_log_to_dynamodb("INFO", "Llamada a Lambda completada.", trace_id, {"payload": payload, "duration": f"{lambda_duration:.4f}"})
        
        # Procesar la respuesta de Lambda
        lambda_result = json.loads(lambda_response["Payload"].read().decode("utf-8"))
        logger.info(f"Respuesta de Lambda: {lambda_result}")
        save_log_to_dynamodb("INFO", "Lambda ejecutada con éxito.", trace_id, {"lambda_result": lambda_result})

        return {"result": lambda_result}

    except ValueError:
        logger.error(f"Error: La cédula {request.cedula} no es un número válido")
        save_log_to_dynamodb("ERROR", "Cédula no válida.", trace_id, {"cedula": request.cedula})
        raise HTTPException(status_code=400, detail="La cédula debe ser un número")
    
    except Exception as e:
        logger.error(f"Error procesando la solicitud: {str(e)}")
        save_log_to_dynamodb("ERROR", "Error procesando solicitud.", trace_id, {"error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))