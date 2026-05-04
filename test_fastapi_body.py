from fastapi import FastAPI
from picframe.api.models import AppConfig
app = FastAPI()
@app.put("/test")
def test(payload: AppConfig):
    return "ok"
print(app.openapi()["paths"]["/test"]["put"])
