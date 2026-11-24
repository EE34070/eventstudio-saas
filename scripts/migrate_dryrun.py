"""Simulation de migration aperçu -> Atlas. LECTURE SEULE : aucune écriture, ni en local ni en production."""
import os, re, json
from dotenv import load_dotenv; load_dotenv('/app/backend/.env')
from pymongo import MongoClient
L = MongoClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
P = MongoClient(os.environ['MONGO_URL_PROD'], serverSelectionTimeoutMS=15000)['exclusivity']
SRC, DST = '8cf7fa76-fec0-4f3c-b832-877a39c0e08b', 'c83e0726-3f8e-4b9b-822f-e4d1a6aab5cf'
SKIP = {'users', 'job_locks', 'sync_queue', 'channel_accounts', 'oauth_states', 'audit_logs', 'cron_runs', 'route_cache', 'orgs', 'module_defs', 'schema_migrations'}
lu = {u['user_id']: (u.get('email') or '').lower() for u in L.users.find({}, {'user_id': 1, 'email': 1})}
pu = {(u.get('email') or '').lower(): u['user_id'] for u in P.users.find({'env': 'live'})}
UID = re.compile(r'^user_[A-Za-z0-9]{20,}$')
unm, mapped = {}, {}
def scan(v, c):
    if isinstance(v, dict):
        for x in v.values(): scan(x, c)
    elif isinstance(v, list):
        for x in v: scan(x, c)
    elif isinstance(v, str) and UID.match(v):
        e = lu.get(v, '?')
        (mapped if e in pu else unm).setdefault((v, e), set()).add(c)
test = lambda d: any(isinstance(d.get(k), str) and d[k].startswith(('TEST_', 'QA ')) for k in ('name', 'title', 'label', 'company', 'last_name', 'first_name'))
print(f"{'collection':28}{'à copier':>9}{'exclus TEST':>12}{'conflits id':>12}{'déjà en prod':>13}")
tot = 0
for c in sorted(L.list_collection_names()):
    n = L[c].count_documents({'org_id': SRC})
    if not n: continue
    if c in SKIP:
        print(f"{c:28}{'—':>9}{'':>12}{'':>12}{'':>13}  EXCLUE ({n} doc.)"); continue
    docs = list(L[c].find({'org_id': SRC}, {'_id': 0}))
    keep = [d for d in docs if not test(d)]
    for d in keep: scan(d, c)
    ids = [d['id'] for d in keep if 'id' in d]
    conf = P[c].count_documents({'id': {'$in': ids}}) if ids else 0
    print(f"{c:28}{len(keep):>9}{len(docs) - len(keep):>12}{conf:>12}{P[c].count_documents({'org_id': DST}):>13}" + ('' if ids or not keep else '  (sans id : clé naturelle)'))
    tot += len(keep)
print('TOTAL à copier', tot)
print('Utilisateurs remappés :', sorted({e for (_, e) in mapped}))
print('Utilisateurs NON remappés :')
for (u, e), cs in sorted(unm.items(), key=lambda x: x[0][1]): print('  ', e, u[:14] + '…', sorted(cs))
fs = list(L.files.find({'org_id': SRC}, {'_id': 0, 'storage_path': 1, 'filename': 1}))
kinds = {}
for f in fs: kinds[(f.get('storage_path') or '')[:12]] = kinds.get((f.get('storage_path') or '')[:12], 0) + 1
print('Fichiers (préfixe du chemin de stockage) :', kinds, '| STORAGE_PROVIDER local =', os.environ.get('STORAGE_PROVIDER') or 'emergent')
print('Prod team :', [(t.get('name'), t.get('email'), t['id'][:8]) for t in P.team.find({'org_id': DST})])
print('Local team :', [(t.get('name'), t.get('email'), t['id'][:8]) for t in L.team.find({'org_id': SRC})])
for c in ('vehicles', 'warehouses'):
    print(c, 'prod :', [x.get('name') for x in P[c].find({'org_id': DST})], '| local :', [x.get('name') for x in L[c].find({'org_id': SRC})])
o2 = '5a130ab8-6fbf-4a09-989f-7c228d648ba7'
print('2e société locale « Exclusivity Events » (5a130ab8) :', {c: n for c in L.list_collection_names() if (n := L[c].count_documents({'org_id': o2}))})
print('Le Frenchie DJ en local :', L.orgs.count_documents({'name': {'$regex': 'frenchie', '$options': 'i'}}))
