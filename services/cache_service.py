import math
import re
from datetime import datetime
from database import get_db_connection
from config import config

class SemanticCacheService:
    def __init__(self):
        self.threshold = config.CACHE_SIMILARITY_THRESHOLD

    def _tokenize_and_vectorize(self, text: str) -> dict:
        # Lowercase, clean punctuation, and split into words
        words = re.findall(r'\w+', text.lower())
        vector = {}
        for word in words:
            vector[word] = vector.get(word, 0) + 1
        return vector

    def _calculate_cosine_similarity(self, vec1: dict, vec2: dict) -> float:
        intersection = set(vec1.keys()) & set(vec2.keys())
        numerator = sum([vec1[x] * vec2[x] for x in intersection])

        sum1 = sum([vec1[x]**2 for x in vec1.keys()])
        sum2 = sum([vec2[x]**2 for x in vec2.keys()])
        denominator = math.sqrt(sum1) * math.sqrt(sum2)

        if not denominator:
            return 0.0
        return float(numerator) / denominator

    def lookup(self, prompt: str) -> dict:
        """
        Looks up if there's a cached response that is semantically similar
        to the incoming prompt. Returns a dictionary with cached details if found, else None.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT prompt, response, model, provider FROM semantic_cache")
        cached_entries = cursor.fetchall()
        conn.close()

        if not cached_entries:
            return None

        incoming_vec = self._tokenize_and_vectorize(prompt)
        best_similarity = 0.0
        best_match = None

        for entry in cached_entries:
            cached_prompt = entry["prompt"]
            cached_vec = self._tokenize_and_vectorize(cached_prompt)
            similarity = self._calculate_cosine_similarity(incoming_vec, cached_vec)

            if similarity > best_similarity:
                best_similarity = similarity
                best_match = entry

        if best_similarity >= self.threshold and best_match:
            return {
                "text": best_match["response"],
                "provider": best_match["provider"],
                "actual_model": best_match["model"],
                "similarity": round(best_similarity, 3)
            }

        return None

    def store(self, prompt: str, response: str, model: str, provider: str):
        """
        Stores a new entry in the semantic cache.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        created_at = datetime.utcnow().isoformat()
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO semantic_cache (prompt, response, model, provider, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (prompt, response, model, provider, created_at))
            conn.commit()
        except Exception as e:
            # Silently catch duplicate errors or constraint violations
            pass
        finally:
            conn.close()
            
    def clear_cache(self):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM semantic_cache")
        conn.commit()
        conn.close()
