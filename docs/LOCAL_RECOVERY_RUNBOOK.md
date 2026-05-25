// Sleeping Passenger



\# Terminal 1 — backend

cd C:\\Users\\akash\\sleeping-passenger-v1

python -m uvicorn scripts.api\_server:app --host 127.0.0.1 --port 8000 --reload



\# Terminal 2 — frontend, likely Admin PowerShell for port 80

cd C:\\Users\\akash\\sleeping-passenger-v1\\frontend

npm run dev:sleepingpassenger



\# Terminal 3 - Google Sheets Sync

cd C:\\Users\\akash\\sleeping-passenger-v1



$env:GOOGLE\_SHEET\_ID = "1pqLD4LNX5ftNppw6k6Ppl0DvNPvOhvtpVQjdRF9\_KsM"

$env:GOOGLE\_SERVICE\_ACCOUNT\_JSON = "C:\\Users\\akash\\sleeping-passenger-v1\\google-service-account.json"

$env:GOOGLE\_SHEET\_WORKSHEET\_NAME = "Sheet1"

$env:MVP\_RECONCILIATION\_ENDPOINT = "http://127.0.0.1:8000/reconciliation/auto-update"



python scripts\\sync\_google\_sheet\_reconciliation.py --loop --interval-minutes 30



\#Terminal 4 - All 5 Synthesis

cd "C:\\Users\\akash\\sleeping-passenger-v1"

powershell -ExecutionPolicy Bypass -File ".\\scripts\\run\_five\_model\_synthesis.ps1"



