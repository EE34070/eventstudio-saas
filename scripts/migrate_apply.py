"""Migration aperçu -> Atlas (étape 2). Upsert sur l'id, aucune suppression. Fichiers et fiche société traités à part."""
import os, re, sys, json, datetime
sys.path.insert(0, '/app/backend')
from dotenv import load_dotenv; load_dotenv('/app/backend/.env')
from pymongo import MongoClient
L = MongoClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
P = MongoClient(os.environ['MONGO_URL_PROD'], serverSelectionTimeoutMS=15000)['exclusivity']
SRC, DST = '8cf7fa76-fec0-4f3c-b832-877a39c0e08b', 'c83e0726-3f8e-4b9b-822f-e4d1a6aab5cf'
SKIP = {'users', 'job_locks', 'sync_queue', 'channel_accounts', 'oauth_states', 'audit_logs', 'cron_runs', 'route_cache', 'orgs', 'module_defs',
        'messages', 'conversations', 'provider_categories', 'files'}
NAT = {'counters': ('key',), 'stock_levels': ('product_id', 'warehouse_id'), 'dj_digests': ('at',), 'quote_label_map': ('key',), 'menu_prefs': ('user_id',), 'tax_estimates': ('month',)}
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
lu = {u['user_id']: (u.get('email') or '').lower() for u in L.users.find({}, {'user_id': 1, 'email': 1})}
pu = {(u.get('email') or '').lower(): u['user_id'] for u in P.users.find({'env': 'live'})}
UID = re.compile(r'^user_[A-Za-z0-9]{20,}$')
def remap(v):
    if isinstance(v, dict): return {k: remap(x) for k, x in v.items()}
    if isinstance(v, list): return [remap(x) for x in v]
    if isinstance(v, str) and UID.match(v): return pu.get(lu.get(v, '?'))
    return v
before = {c: P[c].count_documents({}) for c in P.list_collection_names()}
# doublons Atlas non référencés : désactivés, jamais supprimés
r = P.warehouses.update_one({'id': 'f65b1db3-1682-4be2-87d6-31788bd9f68e', 'org_id': DST}, {'$set': {'active': False, 'is_default': False, 'deactivated_at': now, 'deactivated_reason': 'doublon migration'}})
print('entrepôt Atlas désactivé', r.modified_count)
r = P.team.update_one({'id': 'f8cecd67-bdf4-42da-a538-8418c750c026', 'org_id': DST, 'user_id': None}, {'$set': {'active': False, 'deactivated_at': now, 'deactivated_reason': 'doublon migration'}})
print('fiche Damien Atlas désactivée', r.modified_count)
r = P.users.update_one({'user_id': 'user_3MJNEivzz0QGUEbRiUn5cc7Cl8K', 'org_id': DST, 'env': 'preview'}, {'$set': {'status': 'disabled', 'disabled_at': now}})
print('compte contact@ du 19/11 désactivé', r.modified_count)
done = {}
for c in sorted(L.list_collection_names()):
    if c in SKIP: continue
    n = 0
    for d in L[c].find({'org_id': SRC}, {'_id': 0}):
        d = remap(d); d['org_id'] = DST
        if c == 'team':
            d['user_id'] = None
            for k in [k for k in d if k.startswith('invite')]: d.pop(k)
        if c == 'menu_prefs' and not d.get('user_id'): continue
        if 'id' in d:
            ex = P[c].find_one({'id': d['id']}, {'org_id': 1})
            assert not ex or ex['org_id'] == DST, (c, d['id'])
            f = {'id': d['id']}
        else:
            f = {'org_id': DST, **{k: d[k] for k in NAT[c]}}
        P[c].update_one(f, {'$set': d}, upsert=True); n += 1
    if n: done[c] = n
import server
for c, models in server.INDEXES.items():
    for m in models:
        try: P[c].create_indexes([m])
        except Exception as e: print('INDEX', c, m.document['name'], str(e)[:120])
after = {c: P[c].count_documents({}) for c in P.list_collection_names()}
print(f"{'collection':28}{'avant':>7}{'copiés':>8}{'après':>7}")
for c in sorted(after):
    if after[c] != before.get(c, 0) or c in done: print(f"{c:28}{before.get(c, 0):>7}{done.get(c, 0):>8}{after[c]:>7}" + ('' if after[c] == before.get(c, 0) + done.get(c, 0) else '  <-- écart'))
print('TOTAL copiés', sum(done.values()))
enc = {c: L[c].count_documents({'org_id': SRC, '$or': [{'ssn_encrypted': {'$nin': [None, '']}}, {'iban_encrypted': {'$nin': [None, '']}}]}) for c in ('employee_files', 'provider_profiles')}
print('champs chiffrés avec la clé de l’aperçu :', enc)
print('events', P.events.count_documents({'org_id': DST}), 'quotes', P.quotes.count_documents({'org_id': DST}), 'contacts', P.contacts.count_documents({'org_id': DST}))
print('comptes contact@ :', [(u['user_id'][:12], u.get('env'), u.get('status'), u.get('team_id', '')[:8]) for u in P.users.find({'email': 'contact@exclusivity-events.com'})])
print('entrepôts par défaut DST :', P.warehouses.count_documents({'org_id': DST, 'is_default': True}))
