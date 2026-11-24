"""Copie des fichiers de la société réelle de l'aperçu vers R2 (prod), puis upsert des fiches `files` dans Atlas. Aucune suppression."""
import os, sys, hashlib
sys.path.insert(0, '/app/backend')
from dotenv import load_dotenv; load_dotenv('/app/backend/.env')
import boto3
from botocore.config import Config
from pymongo import MongoClient
import routes_files as rf
L = MongoClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
P = MongoClient(os.environ['MONGO_URL_PROD'], serverSelectionTimeoutMS=15000)['exclusivity']
SRC, DST = '8cf7fa76-fec0-4f3c-b832-877a39c0e08b', 'c83e0726-3f8e-4b9b-822f-e4d1a6aab5cf'
B = os.environ['R2_PROD_BUCKET']
s3 = boto3.client('s3', config=Config(signature_version='s3v4'), endpoint_url=os.environ['R2_PROD_ENDPOINT'], aws_access_key_id=os.environ['R2_PROD_ACCESS_KEY'], aws_secret_access_key=os.environ['R2_PROD_SECRET_KEY'], region_name='auto')
ok, bad = 0, []
for f in L.files.find({'org_id': SRC}, {'_id': 0}):
    try:
        data = rf._get(f['storage_path'])
        data = data[0] if isinstance(data, tuple) else data
        key = f['storage_path'].replace(SRC, DST)
        assert DST in key and len(data) > 0
        try:
            s3.head_object(Bucket=B, Key=key); exists = True
        except Exception:
            exists = False
        if not exists:
            s3.put_object(Bucket=B, Key=key, Body=data, ContentType=f.get('content_type') or 'application/octet-stream')
        back = s3.get_object(Bucket=B, Key=key)['Body'].read()
        assert hashlib.sha256(back).digest() == hashlib.sha256(data).digest(), 'contenu différent'
        ex = P.files.find_one({'id': f['id']}, {'org_id': 1})
        assert not ex or ex['org_id'] == DST
        P.files.update_one({'id': f['id']}, {'$set': {**f, 'org_id': DST, 'storage_path': key}}, upsert=True)
        ok += 1
        print('OK ', f['filename'][:50], len(data), 'o', '(déjà présent)' if exists else '')
    except Exception as e:
        bad.append(f['filename']); print('KO ', f.get('filename'), type(e).__name__, str(e)[:150])
print('copiés', ok, '| échecs', bad, '| files Atlas', P.files.count_documents({'org_id': DST}))
