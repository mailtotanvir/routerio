import os
try:
    from pydantic_settings import BaseSettings
except ImportError:
    class BaseSettings:
        pass
from dotenv import load_dotenv

load_dotenv()

class RouterConfig:
    # Service Information
    APP_NAME: str = "routerio"
    VERSION: str = "1.0.0"
    HOST: str = os.getenv("ROUTERIO_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("ROUTERIO_PORT", 8000))
    
    # API Keys
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    
    # Settings
    # If no real keys are provided, we automatically fall back to "Simulated Provider Mode"
    # to allow beautiful, fully functional dry-runs of the dashboard.
    MOCK_MODE_BY_DEFAULT: bool = os.getenv("MOCK_MODE_BY_DEFAULT", "true").lower() in ("true", "1", "yes")
    
    # Cache Configuration
    CACHE_SIMILARITY_THRESHOLD: float = float(os.getenv("CACHE_SIMILARITY_THRESHOLD", 0.85))
    
    # Fallback sequence config
    DEFAULT_FALLBACK_CHAIN: list = ["anthropic/claude-3-5-sonnet", "openai/gpt-4o", "google/gemini-2.5-flash"]
    
    @property
    def is_mock_mode(self) -> bool:
        # If mock mode is explicitly true, or if no API keys are present at all
        if self.MOCK_MODE_BY_DEFAULT:
            return True
        return not (self.OPENAI_API_KEY or self.ANTHROPIC_API_KEY or self.GEMINI_API_KEY)

config = RouterConfig()
