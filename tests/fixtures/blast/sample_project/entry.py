from fastapi import FastAPI
from service import handle

app = FastAPI()


@app.get("/run")
def main():
    return handle()
