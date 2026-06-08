import requests, sys
try:
    r = requests.post('http://127.0.0.1:8000/api/send/f41fd9a8', timeout=30)
    print(r.status_code)
    print(r.text)
except Exception as e:
    print('ERROR', e)
    sys.exit(1)
