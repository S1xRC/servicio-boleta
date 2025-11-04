# handler.py
import json
import os
import io
import boto3
import jwt
from fpdf import FPDF
from datetime import datetime
from sqlalchemy import create_engine, text


DB_USER = os.environ.get('DB_USER')
DB_PASS = os.environ.get('DB_PASS')
DB_HOST = os.environ.get('DB_HOST')
DB_NAME = os.environ.get('DB_NAME')
DB_PORT = os.environ.get('DB_PORT', '5432')
DB_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DB_URL)


S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
s3_client = boto3.client('s3')

def get_user_id_from_token(event):
    """
    Extrae el user_id (sub) del token JWT en el header de Authorization.
    """
    try:

        auth_header = event['headers'].get('authorization') or event['headers'].get('Authorization')
        if not auth_header:
            raise Exception("Authorization header faltante")
            
        token = auth_header.split(' ')[1]
        
        decoded = jwt.decode(token, options={"verify_signature": False})
        
        return decoded['sub']
        
    except Exception as e:
        print(f"Error de autenticación: {e}")
        return None

def generate_invoice(event, context):
    try:

        user_id = get_user_id_from_token(event)
        if not user_id:
            return {
                "statusCode": 401,
                "body": json.dumps({"error": "No autorizado"})
            }
        request_id = event['pathParameters']['requestId']

        with engine.connect() as conn:
            query = text(
                "SELECT r.buy_order_id, r.amount, r.transaction_date, r.authorization_code, "
                "p.name AS property_name "
                "FROM requests r "
                "JOIN properties p ON r.url = p.url "
                "WHERE r.request_id = :req_id AND r.user_id = :u_id AND r.status = 'COMPLETED'"
            )
            result = conn.execute(query, {"req_id": request_id, "u_id": user_id}).fetchone()

            if not result:
                return {
                    "statusCode": 404,
                    "body": json.dumps({"error": "Boleta no encontrada o no autorizada"})
                }


        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 16)
        
        pdf.cell(200, 10, txt="Boleta de Reserva - Grupo 7", ln=True, align='C')
        pdf.ln(10)

        pdf.set_font("Arial", size=12)
        pdf.cell(200, 10, txt=f"Usuario: {user_id}", ln=True)
        pdf.ln(5)
        
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(200, 10, txt="Detalle de la Compra", ln=True)
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 10, txt=f"Propiedad: {result.property_name}", ln=True)
        pdf.cell(200, 10, txt=f"Orden de Compra: {result.buy_order_id}", ln=True)
        pdf.cell(200, 10, txt=f"Monto: {result.amount} CLP", ln=True)
        pdf.cell(200, 10, txt=f"Autorización: {result.authorization_code}", ln=True)
        
        if result.transaction_date:
            pdf.cell(200, 10, txt=f"Fecha: {result.transaction_date.strftime('%Y-%m-%d')}", ln=True)

        pdf_bytes = pdf.output(dest='S')
        pdf_stream = io.BytesIO(pdf_bytes)
        
        file_key = f"boletas/{user_id}/{result.buy_order_id}.pdf"
        
        s3_client.upload_fileobj(
            pdf_stream,
            S3_BUCKET_NAME,
            file_key
        )
        
        download_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET_NAME, 'Key': file_key},
            ExpiresIn=3600
        )
        
        return {
            "statusCode": 200,
            "body": json.dumps({"download_url": download_url})
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": f"Error interno del servidor: {str(e)}"})
        }