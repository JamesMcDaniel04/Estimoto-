from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import urlparse
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .auth import dev_allowed, make_dev_token
from .bridge import router as bridge_router
from .config import Settings
from .customer_routes import router as customer_router
from .models import Base, Customer, Provider, Vehicle
from .upload_limit import PhotoBodyLimit


def create_app(settings: Settings | None = None, *, auth_verifier=None, auth_client=None, bridge_transport=None):
    settings = settings or Settings()
    if not settings.database_url:
        raise ValueError("DATABASE_URL is required")
    if settings.environment == "production":
        if settings.supabase_url and not settings.supabase_url.startswith("https://"):
            raise ValueError("Production Supabase URL must use HTTPS")
        if settings.bridge_url and not settings.bridge_url.startswith("https://"):
            raise ValueError("Production bridge URL must use HTTPS")
    origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    for origin in origins:
        parsed = urlparse(origin)
        if origin == "*" or parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("CORS_ORIGINS must contain explicit HTTP origins")
    app = FastAPI(title="Estimoto + API", version="1.0")
    app.add_middleware(PhotoBodyLimit)
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                           allow_methods=["GET", "POST", "PUT", "DELETE"],
                           allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])

    @app.exception_handler(RequestValidationError)
    def validation_error(_request, _exc):
        return JSONResponse(status_code=422, content={"detail": "Invalid request fields."})
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})
    if settings.database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def sqlite_pragmas(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
    if settings.environment == "test":
        Base.metadata.create_all(engine)
    app.state.engine = engine
    app.state.settings = settings
    app.state.session_factory = sessionmaker(engine, expire_on_commit=False)
    app.state.auth_verifier = auth_verifier
    app.state.auth_client = auth_client
    app.state.bridge_transport = bridge_transport
    app.include_router(customer_router)
    app.include_router(bridge_router)

    @app.post("/v1/dev/session")
    def dev_session():
        if not dev_allowed(settings):
            raise HTTPException(404, "Not found.")
        with app.state.session_factory() as db:
            c = db.get(Customer, "demo-customer")
            if c is None:
                c = Customer(id="demo-customer", email="demo@example.test", name="Alex Demo", postal_code="80202", demo=True)
                db.add(c)
                db.add(Vehicle(customer_id=c.id, year=2020, make="Demo", model="Sedan", nickname="My demo car"))
            if db.get(Provider, "demo-provider") is None:
                db.add(Provider(id="demo-provider", source_id="fictional-demo", name="Demo Dent Care", kind="shop",
                                specialties=["pdr"], postal_codes=["80202"], city="Denver", address="", phone="",
                                mobile_service=False, accepting_requests=True, public_visible=True, demo_only=True, description="Fictional demo provider"))
            db.commit()
        return {"access_token": make_dev_token(settings), "demo": True}

    return app
