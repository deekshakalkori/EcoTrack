
import requests

url = "http://127.0.0.1:5000/api/login"

user = {
    "email": "teststudent@example.com",
    "password": "EcoTrack123"
}

response = requests.post(url, json=user)

print("Status:", response.status_code)
print("Response:", response.json())
