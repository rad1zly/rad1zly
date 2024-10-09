import requests

data = {"token":"5385761211:tJMRvqTC", "request":"fadhil raditya", "lang":"id"}
url = 'https://server.leakosint.com/'
response = requests.post(url, json=data)
print(response.json())
