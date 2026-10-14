import json
import logging
from contextlib import asynccontextmanager
from time import monotonic
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyCookie
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from labpass.auth import (
    authenticate,
    csrf_token,
    hash_password,
    login,
    logout,
    register,
    require_csrf,
    valid_token,
)
from labpass.config import Settings
from labpass.db import make_engine, make_sessions
from labpass.models import AuthSession, Booking, EmailDelivery, OutboxEvent, User, Workshop
from labpass.rules import DomainError
from labpass.schemas import (
    AuthView,
    BookingCreate,
    BookingView,
    CapacityUpdate,
    Login,
    Registration,
    UserView,
    WorkshopCreate,
    WorkshopView,
)
from labpass.services import cancel_booking, change_capacity, create_booking, lock_user

logger = logging.getLogger("labpass")


def create_app(settings: Settings | None = None, *, engine=None) -> FastAPI:
    settings = settings or Settings.from_env()
    owns_engine = engine is None
    engine = engine if engine is not None else make_engine(settings.database_url)
    sessions = make_sessions(engine)

    def write_origin(request: Request):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if (
                request.headers.get("origin") != settings.public_origin
                or request.headers.get("sec-fetch-site") == "cross-site"
            ):
                raise DomainError(403, "origin_not_allowed")

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            if owns_engine:
                engine.dispose()

    app = FastAPI(
        title="LabPass booking API",
        description="Cookie sessions. Writes require Origin and X-CSRF-Token after login.",
        lifespan=lifespan,
        dependencies=[Depends(write_origin)],
    )

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        request.state.request_id = str(uuid4())
        started = monotonic()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request.state.request_id
            response.headers["Cache-Control"] = "no-store"
            return response
        finally:
            route = request.scope.get("route")
            logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request.state.request_id,
                        "method": request.method,
                        "route": getattr(route, "path", "unmatched"),
                        "status": status,
                        "duration_ms": round((monotonic() - started) * 1000, 2),
                    }
                )
            )

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse(status_code=exc.status, content={"detail": exc.code})

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        # Pydantic errors ordinarily include the submitted input, including passwords.
        errors = [
            {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(PoolTimeoutError)
    @app.exception_handler(OperationalError)
    async def unavailable(request, exc):
        # Do not expose/log connection strings, SQL parameters, or database exceptions.
        return JSONResponse(
            status_code=503,
            content={"detail": "database_unavailable_retry_same_key"},
            headers={"Retry-After": "1"},
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        logger.error(
            json.dumps(
                {
                    "event": "database_error",
                    "request_id": request.state.request_id,
                    "error_type": type(exc).__name__,
                }
            )
        )
        return JSONResponse(status_code=500, content={"detail": "database_error"})

    cookie_scheme = APIKeyCookie(name=settings.cookie_name, auto_error=False)

    def identity(
        request: Request,
        token: Annotated[str | None, Depends(cookie_scheme)],
        x_csrf_token: Annotated[str | None, Header(max_length=64)] = None,
    ) -> UUID:
        with sessions() as session:
            principal = authenticate(session, token)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            require_csrf(token, x_csrf_token)
        request.state.principal = principal
        return principal.user_id

    CurrentUser = Annotated[UUID, Depends(identity)]
    PageSize = Annotated[int, Query(ge=1, le=100)]
    Offset = Annotated[int, Query(ge=0)]

    @app.post("/api/auth/register", response_model=UserView, status_code=201)
    def registration(body: Registration):
        encoded = hash_password(body.password.get_secret_value())
        with sessions.begin() as session:
            result = UserView.model_validate(register(session, body.email, encoded))
        return result

    @app.post("/api/auth/login", response_model=AuthView)
    def sign_in(body: Login, request: Request, response: Response):
        with sessions.begin() as session:
            user, token, expiry = login(
                session,
                body.email,
                body.password.get_secret_value(),
                request.cookies.get(settings.cookie_name),
                settings.session_ttl_seconds,
            )
            result = AuthView(
                user=UserView.model_validate(user), csrf_token=csrf_token(token), expires_at=expiry
            )
        # Set the cookie only after the database commit succeeds.
        response.set_cookie(
            settings.cookie_name,
            token,
            max_age=settings.session_ttl_seconds,
            path="/",
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
        )
        return result

    @app.get("/api/auth/me", response_model=AuthView)
    def me(request: Request, user_id: CurrentUser):
        principal = request.state.principal
        return AuthView(
            user=UserView(id=principal.user_id, email=principal.email, is_admin=principal.is_admin),
            csrf_token=csrf_token(request.cookies[settings.cookie_name]),
            expires_at=principal.expires_at,
        )

    @app.post("/api/auth/logout", status_code=204)
    def sign_out(
        request: Request,
        response: Response,
        x_csrf_token: Annotated[str | None, Header(max_length=64)] = None,
    ):
        token = request.cookies.get(settings.cookie_name)
        if valid_token(token):
            require_csrf(token, x_csrf_token)
        with sessions.begin() as session:
            logout(session, token)
        response.delete_cookie(
            settings.cookie_name,
            path="/",
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
        )

    @app.get("/api/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/api/health/ready")
    def ready():
        with sessions() as session:
            session.execute(select(Workshop.id).limit(1))
            session.execute(select(User.id, User.password_hash).limit(1))
            session.execute(select(AuthSession.token_hash).limit(1))
            session.execute(select(OutboxEvent.publish_attempts).limit(1))
            session.execute(select(EmailDelivery.event_id).limit(1))
        return {"status": "ok"}

    @app.get("/api/workshops", response_model=list[WorkshopView])
    def workshops(limit: PageSize = 50, offset: Offset = 0):
        with sessions() as session:
            rows = session.scalars(
                select(Workshop).order_by(Workshop.id).limit(limit).offset(offset)
            )
            return [WorkshopView.from_workshop(row) for row in rows]

    @app.get("/api/workshops/{workshop_id}", response_model=WorkshopView)
    def workshop(workshop_id: UUID):
        with sessions() as session:
            row = session.get(Workshop, workshop_id)
            if row is None:
                raise DomainError(404, "workshop_not_found")
            return WorkshopView.from_workshop(row)

    @app.post("/api/bookings", response_model=BookingView)
    def book(
        body: BookingCreate,
        user_id: CurrentUser,
        request: Request,
        idempotency_key: Annotated[
            str, Header(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
        ],
    ):
        with sessions.begin() as session:
            row = create_booking(session, user_id, body.workshop_id, idempotency_key)
            result = BookingView.model_validate(row)
            event_id = session.scalar(
                select(OutboxEvent.id).where(OutboxEvent.booking_id == row.id)
            )
        logger.info(
            json.dumps(
                {
                    "event": "booking_request_committed",
                    "request_id": request.state.request_id,
                    "booking_id": str(result.id),
                    "event_id": str(event_id),
                }
            )
        )
        return result

    @app.get("/api/bookings", response_model=list[BookingView])
    def history(user_id: CurrentUser, limit: PageSize = 50, offset: Offset = 0):
        with sessions() as session:
            if session.get(User, user_id) is None:
                raise DomainError(401, "unknown_user")
            rows = session.scalars(
                select(Booking)
                .where(Booking.user_id == user_id)
                .order_by(Booking.created_at.desc(), Booking.id)
                .limit(limit)
                .offset(offset)
            )
            return [BookingView.model_validate(row) for row in rows]

    @app.post("/api/bookings/{booking_id}/cancel", response_model=BookingView)
    def cancel(booking_id: UUID, user_id: CurrentUser, request: Request):
        with sessions.begin() as session:
            result = BookingView.model_validate(cancel_booking(session, user_id, booking_id))
        logger.info(
            json.dumps(
                {
                    "event": "cancellation_request_committed",
                    "request_id": request.state.request_id,
                    "booking_id": str(result.id),
                }
            )
        )
        return result

    @app.post("/api/admin/workshops", response_model=WorkshopView, status_code=201)
    def add_workshop(body: WorkshopCreate, user_id: CurrentUser):
        with sessions.begin() as session:
            if not lock_user(session, user_id).is_admin:
                raise DomainError(403, "admin_required")
            row = Workshop(title=body.title, capacity=body.capacity)
            session.add(row)
            session.flush()
            result = WorkshopView.from_workshop(row)
        return result

    @app.patch("/api/admin/workshops/{workshop_id}/capacity", response_model=WorkshopView)
    def update_capacity(workshop_id: UUID, body: CapacityUpdate, user_id: CurrentUser):
        with sessions.begin() as session:
            result = WorkshopView.from_workshop(
                change_capacity(session, user_id, workshop_id, body.capacity)
            )
        return result

    return app
