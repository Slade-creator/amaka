"""AWS Lambda entry point (zip deploy, Function URL). Wraps the FastAPI app with Mangum."""
from mangum import Mangum

from .app import app

handler = Mangum(app, lifespan="auto")
