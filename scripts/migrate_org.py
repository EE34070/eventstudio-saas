import os, json, datetime
from dotenv import load_dotenv; load_dotenv('/app/backend/.env')
from pymongo import MongoClient
P=MongoClient(os.environ['MONGO_URL_PROD'])['exclusivity']; L=MongoClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
SRC,DST='8cf7fa76-fec0-4f3c-b832-877a39c0e08b','c83e0726-3f8e-4b9b-822f-e4d1a6aab5cf'
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
lo,po=L.orgs.find_one({'id':SRC},{'_id':0}),P.orgs.find_one({'id':DST},{'_id':0})
json.dump({'org':po,'team':list(P.team.find({'org_id':DST},{'_id':0})),'users':list(P.users.find({'org_id':DST},{'_id':0}))},open('/root/backups/atlas-avant-reglages-%s.json'%now[:19].replace(':',''),'w'),default=str)
ch={k:v for k,v in lo.items() if k not in('id','slug','created_at','name') and po.get(k,'<absent>')!=v}
show=lambda k,v:'(renseigné)' if k=='iban' and v else repr(v)[:80]
for k in sorted(ch): print(f"{k:22} AVANT {show(k,po.get(k,'<absent>')):45} APRÈS {show(k,ch[k])}")
P.orgs.update_one({'id':DST},{'$set':ch})
print('inchangés identiques:',sorted(k for k in lo if k not in ch and k not in('id','slug','created_at','name')))
print('logo_url:',repr(lo.get('logo_url'))[:80],'| legal_mentions:',len(lo.get('legal_mentions') or ''),'car. | terms:',len(lo.get('terms') or ''),'car.')
U='user_3MXAyzSrLlJeQapkwSofpuEkMuL'
print(P.team.update_one({'id':'d48991be-'+P.team.find_one({'id':{'$regex':'^d48991be'}})['id'][9:],'org_id':DST},{'$set':{'name':'Florian Falgairolle','email':'contact@exclusivity-events.com','user_id':U,'active':True,'access_role':'admin'}}).modified_count,
      P.team.update_one({'id':{'$regex':'^cd7f71df'},'org_id':DST},{'$set':{'active':False,'user_id':None,'deactivated_at':now,'deactivated_reason':'remplacée par la fiche migrée'}}).modified_count,
      P.users.update_one({'user_id':U},{'$set':{'team_id':P.team.find_one({'id':{'$regex':'^d48991be'}})['id']}}).modified_count)
print([(t['id'][:8],t['name'],t.get('email'),t.get('active'),bool(t.get('user_id')),t.get('access_role')) for t in P.team.find({'org_id':DST})])
print([(u['user_id'][:12],u.get('env'),u.get('status'),(u.get('team_id') or '')[:8]) for u in P.users.find({'org_id':DST})])
