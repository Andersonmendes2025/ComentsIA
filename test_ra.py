import requests

# SEU Authorization Basic vindo do RA
AUTH_BASIC = "Basic SEU_BASE64_AQUI"

url = "https://app.hugme.com.br/api/auth/oauth/token?grant_type=client_credentials"

headers = {
    "Authorization": AUTH_BASIC
}

response = requests.post(url, headers=headers)

print("STATUS:", response.status_code)
print("RESPOSTA:")
print(response.json())
