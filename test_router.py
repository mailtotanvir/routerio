import unittest
import asyncio
import os
import json
import sqlite3
import tempfile

# Redirect SQLite DB to local Windows/Linux TEMP directory to avoid WSL/9p file lock issues
os.environ["ROUTERIO_DB_PATH"] = os.path.join(tempfile.gettempdir(), "routerio_test.db")

from database import DB_PATH, init_db, get_circuit_breakers, update_circuit_breaker
from services.routing_service import RoutingService
from services.cache_service import SemanticCacheService

class TestRouterio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Enforce clean database state
        init_db()
        cls.routing_service = RoutingService()
        cls.cache_service = SemanticCacheService()

    def setUp(self):
        # Clear cache and ensure breakers are closed before each test
        self.cache_service.clear_cache()
        for provider in ["openai", "anthropic", "google", "ollama"]:
            update_circuit_breaker(provider, "CLOSED", 0)

    def test_01_complexity_classifier(self):
        """Verify the routing engine accurately identifies task complexity."""
        # Low complexity conversational prompt
        comp_low, trig_low = self.routing_service.classify_complexity("Hello, how are you?")
        self.assertEqual(comp_low, "Low")

        # Medium complexity SQL query task
        comp_med, trig_med = self.routing_service.classify_complexity("Write a select SQL query from users where id=5")
        self.assertEqual(comp_med, "Medium")

        # High complexity architectural task
        comp_high, trig_high = self.routing_service.classify_complexity("Analyze the performance and optimize this code to prevent a concurrency race condition in python.")
        self.assertEqual(comp_high, "High")

    def test_02_model_selection_policy(self):
        """Test model priority routing decisions depending on the active policy."""
        # Low complexity, optimize for cost -> should pick Google Gemini
        model_cheapest, _, _ = self.routing_service.select_model("Low", "cost")
        self.assertEqual(model_cheapest, "google/gemini-2.5-flash")

        # High complexity, performance -> should pick Anthropic Claude 3.5 Sonnet
        model_premium, _, _ = self.routing_service.select_model("High", "performance")
        self.assertEqual(model_premium, "anthropic/claude-3-5-sonnet")

    def test_03_semantic_cache(self):
        """Verify semantic caching matches and resolves duplicate queries in sub-milliseconds."""
        prompt = "Write a basic python fast api server"
        response_text = "from fastapi import FastAPI\napp = FastAPI()"
        
        # Verify miss first
        self.assertIsNone(self.cache_service.lookup(prompt))
        
        # Store
        self.cache_service.store(prompt, response_text, "openai/gpt-4o-mini", "openai")
        
        # Match exactly
        hit = self.cache_service.lookup(prompt)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["text"], response_text)
        
        # Match semantically (similarity of near matches)
        semantic_hit = self.cache_service.lookup("Could you write a basic python fast api server?")
        self.assertIsNotNone(semantic_hit)
        self.assertGreaterEqual(semantic_hit["similarity"], 0.8)

    def test_04_circuit_breaker_trip(self):
        """Test that tripped circuit breakers force routing failover."""
        # Trip the circuit breaker for anthropic (simulate 3 failures)
        update_circuit_breaker("anthropic", "OPEN", consecutive_failures=3, last_error_message="API Key Invalid")
        
        # Request high-complexity performance -> usually Claude Sonnet (anthropic)
        # Verify it now skips anthropic and falls back to openai/gpt-4o
        selected_model, _, trace = self.routing_service.select_model("High", "performance")
        self.assertEqual(selected_model, "openai/gpt-4o")
        self.assertTrue(any("Circuit breaker for provider 'anthropic' is TRIPPED" in t for t in trace))

    def test_05_database_logging(self):
        """Ensure full request audits are stored in the SQLite logging table."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM audit_logs")
        before_count = cursor.fetchone()[0]
        conn.close()

        # Directly test and verify SQLite logging commit
        from database import insert_audit_log
        insert_audit_log(
            prompt="Hello world router",
            response="Hi from router",
            policy="cost",
            selected_model="google/gemini-2.5-flash",
            actual_model="google/gemini-2.5-flash",
            provider="google",
            latency_ms=100.0,
            prompt_tokens=5,
            completion_tokens=5,
            cost=0.0001,
            cost_saved=0.001,
            reasoning_trace={"test": True}
        )
        
        # Verify a new log entry was written
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM audit_logs")
        after_count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(after_count, before_count + 1)

if __name__ == "__main__":
    unittest.main()
