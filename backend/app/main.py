import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import connect_to_mongo, close_mongo_connection
from app.routes import auth, outpass, admin, reports
from app.services.scheduler import start_scheduler, shutdown_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("homs_main")

app = FastAPI(
    title="Hostel Outpass Management System (H.O.M.S) API",
    description="Commercial-grade secure multi-tier workflow REST API with RBAC, Excel logging, and Audit Trails",
    version="1.0.0"
)

# CORS Policy configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to the web portal URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    logger.info("Initializing system...")
    await connect_to_mongo()
    start_scheduler()

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down system...")
    await close_mongo_connection()
    shutdown_scheduler()

# Register Routers
app.include_router(auth.router)
app.include_router(outpass.router)
app.include_router(admin.router)
app.include_router(reports.router)

@app.get("/")
async def root():
    return {
        "status": "online",
        "system": "Hostel Outpass Management System (H.O.M.S)",
        "message": "Welcome to H.O.M.S API. Access Swagger documentation at /docs"
    }
