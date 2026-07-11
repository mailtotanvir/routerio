import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.getenv("ROUTERIO_DB_PATH", os.path.join(os.path.dirname(__file__), "routerio.db"))

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Audit Logs Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            prompt TEXT NOT NULL,
            response TEXT NOT NULL,
            policy TEXT NOT NULL,
            selected_model TEXT NOT NULL,
            actual_model TEXT NOT NULL,
            provider TEXT NOT NULL,
            latency_ms REAL NOT NULL,
            prompt_tokens INTEGER NOT NULL,
            completion_tokens INTEGER NOT NULL,
            total_tokens INTEGER NOT NULL,
            cost USD REAL NOT NULL,
            cost_saved USD REAL NOT NULL,
            reasoning_trace TEXT NOT NULL,
            was_cached INTEGER NOT NULL DEFAULT 0,
            was_fallback INTEGER NOT NULL DEFAULT 0,
            fallback_reason TEXT
        )
    """)
    
    # 2. Circuit Breakers Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS circuit_breakers (
            provider TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'CLOSED', -- 'CLOSED', 'OPEN' (tripped), 'HALF-OPEN'
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            last_failure_time TEXT,
            last_error_message TEXT
        )
    """)
    
    # 3. Semantic Cache Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS semantic_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt TEXT UNIQUE NOT NULL,
            response TEXT NOT NULL,
            model TEXT NOT NULL,
            provider TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    
    # Initialize circuit breakers for major providers
    providers = ["openai", "anthropic", "google", "ollama"]
    for provider in providers:
        cursor.execute("""
            INSERT OR IGNORE INTO circuit_breakers (provider, status, consecutive_failures)
            VALUES (?, 'CLOSED', 0)
        """, (provider,))
        
    conn.commit()
    conn.close()

# Helper DB actions
def insert_audit_log(prompt, response, policy, selected_model, actual_model, provider, 
                     latency_ms, prompt_tokens, completion_tokens, cost, cost_saved, 
                     reasoning_trace, was_cached=0, was_fallback=0, fallback_reason=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    timestamp = datetime.utcnow().isoformat()
    cursor.execute("""
        INSERT INTO audit_logs (
            timestamp, prompt, response, policy, selected_model, actual_model, provider,
            latency_ms, prompt_tokens, completion_tokens, total_tokens, cost, cost_saved,
            reasoning_trace, was_cached, was_fallback, fallback_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        timestamp, prompt, response, policy, selected_model, actual_model, provider,
        latency_ms, prompt_tokens, completion_tokens, prompt_tokens + completion_tokens,
        cost, cost_saved, json.dumps(reasoning_trace), was_cached, was_fallback, fallback_reason
    ))
    conn.commit()
    conn.close()

def get_all_logs(limit=50):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_analytics_summary():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Total requests & stats
    cursor.execute("SELECT COUNT(*) as total_reqs, SUM(cost) as total_spent, SUM(cost_saved) as total_saved, AVG(latency_ms) as avg_lat FROM audit_logs")
    summary = dict(cursor.fetchone())
    
    # Cache hit rate
    cursor.execute("SELECT COUNT(*) as cache_hits FROM audit_logs WHERE was_cached = 1")
    cache_hits = cursor.fetchone()['cache_hits']
    
    # Provider breakdown
    cursor.execute("SELECT provider, COUNT(*) as count FROM audit_logs GROUP BY provider")
    providers = {row['provider']: row['count'] for row in cursor.fetchall()}
    
    conn.close()
    
    total = summary['total_reqs'] or 0
    return {
        "total_requests": total,
        "total_cost": round(summary['total_spent'] or 0.0, 5),
        "total_saved": round(summary['total_saved'] or 0.0, 5),
        "average_latency_ms": round(summary['avg_lat'] or 0.0, 2),
        "cache_hit_rate": round((cache_hits / total * 100) if total > 0 else 0.0, 1),
        "provider_distribution": providers
    }

def update_circuit_breaker(provider, status, consecutive_failures=0, last_error_message=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    last_failure_time = datetime.utcnow().isoformat() if last_error_message else None
    
    cursor.execute("""
        UPDATE circuit_breakers 
        SET status = ?, consecutive_failures = ?, last_failure_time = COALESCE(?, last_failure_time), last_error_message = COALESCE(?, last_error_message)
        WHERE provider = ?
    """, (status, consecutive_failures, last_failure_time, last_error_message, provider))
    conn.commit()
    conn.close()

def get_circuit_breakers():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM circuit_breakers")
    rows = {r['provider']: dict(r) for r in cursor.fetchall()}
    conn.close()
    return rows

# Initialize DB on import
init_db()
