# middleware.py
from starlette.middleware.base import BaseHTTPMiddleware
from logger import actor_email_ctx, subject_email_ctx
from starlette.requests import Request
from logger import *
import jwt


class ImpersonationContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, secret_key, algorithm="HS256"):
        super().__init__(app)
        self.secret_key = secret_key
        self.algorithm = algorithm

    async def dispatch(self, request: Request, call_next):
        token = request.headers.get("authorization", "").replace("Bearer ", "")
        actor_email_ctx.set("anonymous")
        subject_email_ctx.set("anonymous")
        action_ctx.set(None)

        actor_email = "anonymous"
        subject_email = "anonymous"
        impersonated = False

        if token:
            try:
                payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
                subject_email = payload.get("email")
                actor_email = payload.get("original_user_email", subject_email)

                actor_email_ctx.set(actor_email)
                subject_email_ctx.set(subject_email)

                impersonated = payload.get("impersonated", False)
            except jwt.PyJWTError:
                pass
        
        if impersonated and actor_email != subject_email:
            action_ctx.set(f"{request.method} {request.url.path}")

        response = await call_next(request)

        return response
