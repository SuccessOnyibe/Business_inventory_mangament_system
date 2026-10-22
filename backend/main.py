from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return {"message": "Family Inventory Management API is running"}
