import requests, json, sys
try:
    r = requests.post('http://127.0.0.1:8000/api/run', json={"domain":"stripe.com","limit":1,"dry_run":False}, timeout=30)
    print(r.status_code)
    try:
        print(r.json())
    except Exception:
        print(r.text)
except Exception as e:
    print('ERROR', e)
    sys.exit(1)
