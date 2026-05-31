import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

load_dotenv()

from app.routers import device, web, otp

app = FastAPI(title="SmartLock API", docs_url=None, redoc_url=None)

app.include_router(device.router, prefix="/api")
app.include_router(web.router,    prefix="/api")
app.include_router(otp.router,    prefix="/api")

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def serve_ui():
    path = "static/index.html"
    if not os.path.exists(path):
        from fastapi.responses import JSONResponse
        return JSONResponse({"status": "ok"})
    return FileResponse(path)

@app.get("/ceg")
def serve_ceg():
    return FileResponse("static/ceg/index.html")

@app.get("/ceg/nene")
def serve_ceg_nene():
    return FileResponse("static/ceg/nene/index.html")

@app.get("/ceg/naran")
def serve_ceg_naran():
    return FileResponse("static/ceg/naran/index.html")
